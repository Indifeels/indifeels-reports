"""Auto-reconcile delayed Shopify Customer Journey attribution.

Runs every 15 minutes and can refresh one order on demand. It waits for
Shopify's asynchronous customerJourneySummary.ready signal, then:
- stores the journey for the Order Attribution screen;
- finds the earliest attributable paid touch (Facebook/Instagram or Google);
- if there is no paid touch, falls back to the earliest organic/search/social touch;
- writes source + campaign/ad-set details to Shopify and Supabase;
- never overwrites attribution that is already saved manually.

Direct-only, repeat/offline, phone, WhatsApp and other ambiguous orders remain
pending for manual attribution.

Environment:
  SHOPIFY_TOKEN, SYNC_READ_TOKEN
Optional:
  SHOPIFY_SHOP, ORDER_ID, ORDER_ATTRIBUTION_CALLBACK
"""
import json
import os
import re
import urllib.request
from datetime import datetime

SHOP = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
TOKEN = os.environ["SHOPIFY_TOKEN"]
SYNC_TOKEN = os.environ["SYNC_READ_TOKEN"]
ORDER_ID = os.environ.get("ORDER_ID", "").strip()
API = f"https://{SHOP}/admin/api/2026-04/graphql.json"
CALLBACK = os.environ.get(
    "ORDER_ATTRIBUTION_CALLBACK",
    "https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/order-attribution-callback",
)

VISIT = """
  id
  occurredAt
  source
  sourceDescription
  referrerUrl
  landingPage
  utmParameters { source medium campaign term content }
"""

ATTR_FIELDS = """
  sourceField: metafield(namespace:"custom",key:"order_source"){value}
  platformField: metafield(namespace:"custom",key:"attribution_platform"){value}
  campaignField: metafield(namespace:"custom",key:"attribution_campaign"){value}
  campaignIdField: metafield(namespace:"custom",key:"attribution_campaign_id"){value}
  adsetField: metafield(namespace:"custom",key:"attribution_ad_set"){value}
  adsetIdField: metafield(namespace:"custom",key:"attribution_ad_set_id"){value}
"""

ONE = f"""query OrderJourney($id:ID!){{
  order(id:$id){{
    id name createdAt
    {ATTR_FIELDS}
    customerJourneySummary{{
      ready daysToConversion customerOrderIndex
      firstVisit{{{VISIT}}}
      lastVisit{{{VISIT}}}
      moments(first:50){{
        nodes{{
          ... on CustomerVisit{{{VISIT}}}
        }}
      }}
    }}
  }}
}}"""

MANY = f"""query RecentOrderJourneys($first:Int!){{
  orders(first:$first, sortKey:CREATED_AT, reverse:true){{
    nodes{{
      id name createdAt
      {ATTR_FIELDS}
      customerJourneySummary{{
        ready daysToConversion customerOrderIndex
        firstVisit{{{VISIT}}}
        lastVisit{{{VISIT}}}
        moments(first:50){{
          nodes{{
            ... on CustomerVisit{{{VISIT}}}
          }}
        }}
      }}
    }}
  }}
}}"""

SET_METAFIELDS = """mutation SetOrderAttributionMetafields($metafields:[MetafieldsSetInput!]!){
  metafieldsSet(metafields:$metafields){
    metafields{id namespace key value type}
    userErrors{field message code}
  }
}"""


def post_json(url, payload, headers=None, timeout=90):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=h,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def shopify(query, variables):
    out = post_json(
        API,
        {"query": query, "variables": variables},
        {"X-Shopify-Access-Token": TOKEN},
        timeout=120,
    )
    if out.get("errors"):
        raise RuntimeError("Shopify GraphQL: " + json.dumps(out["errors"])[:1000])
    return out.get("data") or {}


def shopify_set(order_id, values):
    fields = []
    for key, value in values.items():
        if value is None or str(value).strip() == "":
            continue
        fields.append({
            "ownerId": order_id,
            "namespace": "custom",
            "key": key,
            "type": "single_line_text_field",
            "value": str(value)[:500],
        })
    if not fields:
        return
    data = shopify(SET_METAFIELDS, {"metafields": fields})
    errs = ((data.get("metafieldsSet") or {}).get("userErrors") or [])
    if errs:
        raise RuntimeError("Shopify metafield update rejected: " + json.dumps(errs)[:1000])


def norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def clean_visit(v):
    if not isinstance(v, dict):
        return None
    u = v.get("utmParameters") or {}
    return {
        "id": v.get("id"),
        "occurred_at": v.get("occurredAt"),
        "source": v.get("source"),
        "source_description": v.get("sourceDescription"),
        "referrer_url": v.get("referrerUrl"),
        "landing_page": v.get("landingPage"),
        "utm": {
            "source": u.get("source"),
            "medium": u.get("medium"),
            "campaign": u.get("campaign"),
            "term": u.get("term"),
            "content": u.get("content"),
        } if u else None,
    }


def visits(summary):
    raw = []
    if isinstance(summary.get("firstVisit"), dict):
        raw.append(summary["firstVisit"])
    raw.extend(x for x in ((summary.get("moments") or {}).get("nodes") or []) if isinstance(x, dict))
    if isinstance(summary.get("lastVisit"), dict):
        raw.append(summary["lastVisit"])

    out, seen = [], set()
    for v in raw:
        c = clean_visit(v)
        if not c:
            continue
        key = c.get("id") or json.dumps(
            [c.get("occurred_at"), c.get("source"), c.get("landing_page"), c.get("utm")],
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    out.sort(key=lambda x: str(x.get("occurred_at") or ""))
    return out


def platform_of(v):
    u = v.get("utm") or {}
    hay = " ".join(str(x or "") for x in (
        v.get("source"), v.get("source_description"), v.get("referrer_url"),
        u.get("source"), u.get("medium"), u.get("campaign"), u.get("content"),
    )).lower()
    if any(x in hay for x in ("facebook", "instagram", "m.facebook", "l.instagram", " fb ", "meta")):
        return "Facebook"
    if "google" in hay or "gclid" in hay:
        return "Google"
    return None


def is_organic(v):
    u = v.get("utm") or {}
    vals = " ".join(str(x or "") for x in (
        u.get("source"), u.get("medium"), u.get("campaign"), u.get("content"),
        v.get("source"), v.get("source_description"), v.get("referrer_url"),
    )).lower()
    if "sag_organic" in vals or "sag organic" in vals or "organic" in vals:
        return True
    p = platform_of(v)
    medium = str(u.get("medium") or "").lower()
    if p == "Google" and medium in ("", "organic", "product_sync"):
        # product_sync + sag_organic is a common Shopify Google free-listing path.
        return not any(x in vals for x in ("cpc", "ppc", "paid", "ads", "adwords"))
    if p == "Facebook" and (not u or medium in ("social", "organic", "referral")):
        return True
    # Other recognized search engines are organic unless a paid marker exists.
    if any(x in vals for x in ("bing.com", "yahoo.com", "duckduckgo.com")):
        return not any(x in vals for x in ("cpc", "ppc", "paid"))
    return False


def is_paid(v):
    u = v.get("utm") or {}
    if not u or is_organic(v):
        return False
    p = platform_of(v)
    if p not in ("Facebook", "Google"):
        return False
    vals = " ".join(str(x or "") for x in (
        u.get("source"), u.get("medium"), u.get("campaign"), u.get("term"), u.get("content"),
        v.get("source_description"),
    )).lower()
    if any(x in vals for x in ("cpc", "ppc", "paid", "tracked", "non tracked", "non-tracked", "sales", "campaign")):
        return True
    if p == "Facebook" and (u.get("campaign") or u.get("term") or u.get("content")):
        return str(u.get("medium") or "").lower() not in ("social", "organic", "referral")
    if p == "Google" and str(u.get("medium") or "").lower() not in ("", "organic", "product_sync"):
        return True
    return False


def first_attributable(summary):
    vs = visits(summary)
    paid = [v for v in vs if is_paid(v)]
    if paid:
        return paid[0], "paid"
    organic = [v for v in vs if is_organic(v)]
    if organic:
        return organic[0], "organic"
    return None, None


def catalog_index(rows):
    return [r for r in rows if r.get("platform") in ("Facebook", "Google") and r.get("campaign_name")]


def unique_hit(hits):
    keys = {
        (str(x.get("campaign_id") or ""), str(x.get("adset_id") or ""), str(x.get("campaign_name") or ""))
        for x in hits
    }
    return hits[0] if len(keys) == 1 and hits else None


def match_catalog(v, platform, catalog):
    u = v.get("utm") or {}
    rows = [x for x in catalog if x.get("platform") == platform]

    # Strongest key for Meta in this store: utm_term is the ad-set id.
    term = str(u.get("term") or "").strip()
    if term:
        hit = unique_hit([x for x in rows if str(x.get("adset_id") or "") == term])
        if hit:
            return hit, "catalog_adset_id"

    campaign_raw = str(u.get("campaign") or "").strip()
    medium_raw = str(u.get("medium") or "").strip()

    # Google often sends the campaign id directly in utm_campaign.
    if campaign_raw.isdigit():
        hit = unique_hit([x for x in rows if str(x.get("campaign_id") or "") == campaign_raw])
        if hit:
            return hit, "catalog_campaign_id"

    # Facebook in this account normally uses utm_medium=campaign name,
    # utm_campaign=ad-set name.
    if platform == "Facebook":
        if campaign_raw:
            hit = unique_hit([x for x in rows if norm(x.get("adset_name")) == norm(campaign_raw)])
            if hit:
                return hit, "catalog_adset_name"
        if medium_raw:
            hit = unique_hit([x for x in rows if norm(x.get("campaign_name")) == norm(medium_raw)])
            if hit:
                return hit, "catalog_campaign_name"
    else:
        for raw in (campaign_raw, medium_raw):
            if not raw:
                continue
            hit = unique_hit([x for x in rows if norm(x.get("campaign_name")) == norm(raw)])
            if hit:
                return hit, "catalog_campaign_name"

    # Conservative normalized-prefix match for renamed/date-suffixed campaigns.
    for raw in ((medium_raw, campaign_raw) if platform == "Facebook" else (campaign_raw, medium_raw)):
        n = norm(raw)
        if len(n) < 10:
            continue
        hits = []
        for x in rows:
            c = norm(x.get("campaign_name"))
            if len(c) >= 10 and (c.startswith(n) or n.startswith(c)):
                hits.append(x)
        ids = {str(x.get("campaign_id") or "") for x in hits}
        if len(ids) == 1 and hits:
            return hits[0], "catalog_campaign_prefix"

    return None, None


def raw_paid_fields(v, platform):
    u = v.get("utm") or {}
    if platform == "Facebook":
        return {
            "campaign_platform": "Facebook",
            "campaign_id": None,
            "campaign_name": u.get("medium") or u.get("campaign"),
            "adset_id": u.get("term"),
            "adset_name": u.get("campaign") if u.get("campaign") != u.get("medium") else None,
        }
    # Google: utm_campaign may be either a campaign ID or a human-readable campaign.
    raw = str(u.get("campaign") or "").strip()
    return {
        "campaign_platform": "Google",
        "campaign_id": raw if raw.isdigit() else None,
        "campaign_name": raw or u.get("medium"),
        "adset_id": None,
        "adset_name": None,
    }


def attribution_for(order, catalog):
    summary = order.get("customerJourneySummary") or {}
    if summary.get("ready") is not True:
        return None

    # Never replace anything already saved in Shopify. Manual attribution wins.
    if str((order.get("sourceField") or {}).get("value") or "").strip():
        return None

    v, kind = first_attributable(summary)
    if not v:
        return None
    u = v.get("utm") or {}

    if kind == "organic":
        return {
            "order_source": "Organic Orders",
            "campaign_platform": None,
            "campaign_id": None,
            "campaign_name": None,
            "adset_id": None,
            "adset_name": None,
            "utm_source": u.get("source"),
            "utm_medium": u.get("medium"),
            "utm_campaign": u.get("campaign"),
            "utm_content": u.get("content"),
            "utm_term": u.get("term"),
            "attribution_match_method": "first_online_touch_organic",
        }

    platform = platform_of(v)
    if platform not in ("Facebook", "Google"):
        return None
    source = "FB Online Orders - WEB" if platform == "Facebook" else "Google Online Orders - WEB"
    hit, how = match_catalog(v, platform, catalog)
    fields = raw_paid_fields(v, platform)
    if hit:
        fields = {
            "campaign_platform": platform,
            "campaign_id": hit.get("campaign_id"),
            "campaign_name": hit.get("campaign_name"),
            "adset_id": hit.get("adset_id"),
            "adset_name": hit.get("adset_name"),
        }

    return {
        "order_source": source,
        **fields,
        "utm_source": u.get("source"),
        "utm_medium": u.get("medium"),
        "utm_campaign": u.get("campaign"),
        "utm_content": u.get("content"),
        "utm_term": u.get("term"),
        "attribution_match_method": "first_paid_touch_" + (how or "shopify_utm"),
    }


def to_journey_update(order):
    summary = order.get("customerJourneySummary") or {}
    ready = summary.get("ready") is True
    vs = visits(summary) if ready else []
    journey = {
        "order_name": order.get("name"),
        "order_created_at": order.get("createdAt"),
        "ready": ready,
        "days_to_conversion": summary.get("daysToConversion"),
        "customer_order_index": summary.get("customerOrderIndex"),
        "first_visit": clean_visit(summary.get("firstVisit")) if ready else None,
        "last_visit": clean_visit(summary.get("lastVisit")) if ready else None,
        "moments": vs,
    }
    return {
        "order_id": order.get("id"),
        "ready": ready,
        "journey": journey,
    }


def main():
    if ORDER_ID:
        data = shopify(ONE, {"id": ORDER_ID})
        orders = [data.get("order")] if data.get("order") else []
    else:
        data = shopify(MANY, {"first": 100})
        orders = ((data.get("orders") or {}).get("nodes") or [])

    orders = [o for o in orders if isinstance(o, dict) and o.get("id")]
    if not orders:
        print("No Shopify orders returned.")
        return

    # Store the full delayed journey first so the dashboard updates even when
    # an order still needs manual attribution.
    journey_updates = [to_journey_update(o) for o in orders]
    jout = post_json(
        CALLBACK,
        {"mode": "journey", "token": SYNC_TOKEN, "updates": journey_updates},
        timeout=90,
    )
    if not jout.get("ok"):
        raise RuntimeError("Journey callback failed: " + json.dumps(jout)[:1000])

    # Reuse the existing Windsor-derived catalogue rather than hitting Windsor
    # every 15 minutes.
    cout = post_json(CALLBACK, {"mode": "catalog_export", "token": SYNC_TOKEN}, timeout=90)
    if not cout.get("ok"):
        raise RuntimeError("Catalogue read failed: " + json.dumps(cout)[:1000])
    catalog = catalog_index(cout.get("rows") or [])

    auto_updates = []
    warnings = []
    for order in orders:
        a = attribution_for(order, catalog)
        if not a:
            continue

        values = {
            "order_source": a.get("order_source"),
            "attribution_platform": a.get("campaign_platform"),
            "attribution_campaign": a.get("campaign_name"),
            "attribution_campaign_id": a.get("campaign_id"),
            "attribution_ad_set": a.get("adset_name"),
            "attribution_ad_set_id": a.get("adset_id"),
        }
        try:
            shopify_set(order["id"], values)
        except Exception as exc:
            warnings.append(f'{order.get("name")}: {exc}')
            continue

        auto_updates.append({
            "order_id": order["id"],
            **a,
        })

    if auto_updates:
        aout = post_json(
            CALLBACK,
            {"mode": "auto_attribution", "token": SYNC_TOKEN, "updates": auto_updates},
            timeout=90,
        )
        if not aout.get("ok"):
            raise RuntimeError("Auto-attribution callback failed: " + json.dumps(aout)[:1000])

    ready = sum(1 for x in journey_updates if x["ready"])
    print(
        f"Order journey refresh: checked {len(orders)}, ready {ready}, "
        f"journey updates {jout.get('updated', 0)}, auto-attributed {len(auto_updates)}."
    )
    if warnings:
        print("Auto-attribution warnings:", " | ".join(warnings[:10]))


if __name__ == "__main__":
    main()
