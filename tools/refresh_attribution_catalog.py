"""Refresh ad attribution choices and auto-fill Shopify order attribution.

This job:
1. fetches recent Meta campaign/ad-set and Google campaign/ad-group metadata;
2. publishes that searchable catalogue to Supabase;
3. reads recent Shopify Customer Journey / UTM details;
4. auto-fills blank paid campaign attribution only when the UTM can be matched
   confidently to the live ad catalogue;
5. never overwrites campaign/source values already saved on the Shopify order.

Environment:
  WINDSOR_API_KEY, SYNC_READ_TOKEN, SHOPIFY_TOKEN
Optional:
  SHOPIFY_SHOP, WINDSOR_FACEBOOK_ACCOUNT, WINDSOR_GOOGLE_ACCOUNT
"""
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta

KEY = os.environ["WINDSOR_API_KEY"]
TOKEN = os.environ["SYNC_READ_TOKEN"]
SHOPIFY_TOKEN = os.environ["SHOPIFY_TOKEN"]
SHOP = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
SHOPIFY_API = f"https://{SHOP}/admin/api/2026-04/graphql.json"
CALLBACK = os.environ.get(
    "ORDER_ATTRIBUTION_CALLBACK",
    "https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/order-attribution-callback",
)
DATE_TO = date.today().isoformat()
DATE_FROM = (date.today() - timedelta(days=90)).isoformat()


def post_json(url, payload, headers=None, timeout=180):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=h,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch(connector, account, fields):
    q = urllib.parse.urlencode({
        "api_key": KEY,
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "fields": ",".join(fields),
        "select_accounts": account,
    })
    with urllib.request.urlopen(
        "https://connectors.windsor.ai/" + connector + "?" + q,
        timeout=240,
    ) as r:
        x = json.load(r)
    rows = x.get("data", x) if isinstance(x, dict) else x
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"Windsor returned no {connector} rows")
    return rows


def latest(rows, platform, ad_name_key, ad_id_key, ad_status_key):
    out = {}
    for r in rows:
        cid = str(r.get("campaign_id") or "").strip()
        cname = str(r.get("campaign") or "").strip()
        if not cid or not cname:
            continue
        aid = str(r.get(ad_id_key) or "").strip()
        aname = str(r.get(ad_name_key) or "").strip()
        d = str(r.get("date") or "")
        k = platform + "|" + cid + "|" + aid
        row = {
            "option_key": k,
            "platform": platform,
            "campaign_id": cid,
            "campaign_name": cname,
            "campaign_status": str(r.get("campaign_status") or "").strip() or None,
            "adset_id": aid or None,
            "adset_name": aname or None,
            "adset_status": str(r.get(ad_status_key) or "").strip() or None,
            "last_seen_date": d or None,
        }
        if k not in out or d >= str(out[k].get("last_seen_date") or ""):
            out[k] = row
    return list(out.values())


def norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def unique_campaigns(rows, platform):
    by_id = {}
    for r in rows:
        if r["platform"] != platform:
            continue
        old = by_id.get(r["campaign_id"])
        if not old or str(r.get("last_seen_date") or "") >= str(old.get("last_seen_date") or ""):
            by_id[r["campaign_id"]] = r
    return list(by_id.values())


def name_match(value, candidates, field):
    """Return one confident exact/prefix normalized name match, else None."""
    n = norm(value)
    if len(n) < 8:
        return None, None
    exact = [x for x in candidates if norm(x.get(field)) == n]
    ids = {(x.get("campaign_id"), x.get("adset_id")) for x in exact}
    if len(ids) == 1 and exact:
        return exact[0], "exact_name"
    prefix = [
        x for x in candidates
        if min(len(n), len(norm(x.get(field)))) >= 12
        and (norm(x.get(field)).startswith(n) or n.startswith(norm(x.get(field))))
    ]
    ids = {(x.get("campaign_id"), x.get("adset_id")) for x in prefix}
    if len(ids) == 1 and prefix:
        return prefix[0], "normalized_prefix"
    return None, None


def platform_of(visit):
    u = (visit or {}).get("utmParameters") or {}
    s = " ".join([
        str(u.get("source") or ""),
        str((visit or {}).get("source") or ""),
        str((visit or {}).get("sourceDescription") or ""),
        str((visit or {}).get("referrerUrl") or ""),
    ]).lower()
    if any(x in s for x in ("facebook", "instagram", "fb.", "meta")):
        return "Facebook"
    if "google" in s:
        return "Google"
    return None


def match_visit(visit, catalog):
    u = (visit or {}).get("utmParameters") or {}
    if not u:
        return None
    platform = platform_of(visit)
    if platform not in ("Facebook", "Google"):
        return None

    # Highest-confidence rule: a UTM ID that is an exact current ad-set/ad-group ID.
    term = str(u.get("term") or "").strip()
    if term:
        id_hits = [x for x in catalog if x["platform"] == platform and x.get("adset_id") == term]
        ids = {(x["campaign_id"], x.get("adset_id")) for x in id_hits}
        if len(ids) == 1 and id_hits:
            return id_hits[0], 100, "utm_term_exact_adset_id"

    # Meta setup commonly carries the ad-set name in utm_campaign.
    if platform == "Facebook":
        adsets = [x for x in catalog if x["platform"] == "Facebook" and x.get("adset_name")]
        hit, how = name_match(u.get("campaign"), adsets, "adset_name")
        if hit:
            return hit, 95 if how == "exact_name" else 92, "utm_campaign_" + how + "_adset"

    # Campaign lookup. Google commonly has a normalized campaign slug without
    # the date suffix, so unique normalized-prefix matching is allowed.
    campaigns = unique_campaigns(catalog, platform)
    for field, score in (("campaign", 90), ("medium", 86)):
        hit, how = name_match(u.get(field), campaigns, "campaign_name")
        if hit:
            return hit, score if how == "exact_name" else score - 3, f"utm_{field}_{how}_campaign"

    return None


def journey_visits(summary):
    if not summary or not summary.get("ready"):
        return []
    out = []
    seen = set()
    for v in [summary.get("firstVisit")] + [
        x for x in ((summary.get("moments") or {}).get("nodes") or [])
    ] + [summary.get("lastVisit")]:
        if not isinstance(v, dict):
            continue
        key = json.dumps({
            "occurredAt": v.get("occurredAt"),
            "source": v.get("source"),
            "utm": v.get("utmParameters"),
            "landing": v.get("landingPage"),
        }, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


ORDER_JOURNEY_QUERY = """query AutoAttributionOrders($first:Int!){
  orders(first:$first, sortKey:CREATED_AT, reverse:true){
    nodes{
      id name createdAt
      sourceField: metafield(namespace:"custom",key:"order_source"){value}
      platformField: metafield(namespace:"custom",key:"attribution_platform"){value}
      campaignField: metafield(namespace:"custom",key:"attribution_campaign"){value}
      campaignIdField: metafield(namespace:"custom",key:"attribution_campaign_id"){value}
      adsetField: metafield(namespace:"custom",key:"attribution_ad_set"){value}
      adsetIdField: metafield(namespace:"custom",key:"attribution_ad_set_id"){value}
      customerJourneySummary{
        ready
        firstVisit{
          source sourceDescription referrerUrl landingPage
          utmParameters{source medium campaign content term}
        }
        lastVisit{
          source sourceDescription referrerUrl landingPage
          utmParameters{source medium campaign content term}
        }
        moments(first:20){
          nodes{
            occurredAt
            ... on CustomerVisit{
              source sourceDescription referrerUrl landingPage
              utmParameters{source medium campaign content term}
            }
          }
        }
      }
    }
  }
}"""

SET_METAFIELDS = """mutation SetOrderAttributionMetafields($metafields:[MetafieldsSetInput!]!){
  metafieldsSet(metafields:$metafields){
    metafields{id namespace key value type}
    userErrors{field message code}
  }
}"""


def shopify_graphql(query, variables):
    out = post_json(
        SHOPIFY_API,
        {"query": query, "variables": variables},
        {"X-Shopify-Access-Token": SHOPIFY_TOKEN},
        timeout=180,
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
    data = shopify_graphql(SET_METAFIELDS, {"metafields": fields})
    errs = ((data.get("metafieldsSet") or {}).get("userErrors") or [])
    if errs:
        raise RuntimeError("Shopify metafield update rejected: " + json.dumps(errs)[:1000])


fb = fetch(
    "facebook",
    os.environ.get("WINDSOR_FACEBOOK_ACCOUNT", "1634084963432990"),
    ["date","campaign","campaign_id","campaign_status","adset_name","adset_id","adset_status"],
)
google = fetch(
    "google_ads",
    os.environ.get("WINDSOR_GOOGLE_ACCOUNT", "788-887-6041"),
    ["date","campaign","campaign_id","campaign_status","ad_group_name","ad_group_id","ad_group_status"],
)

rows = (
    latest(fb, "Facebook", "adset_name", "adset_id", "adset_status")
    + latest(google, "Google", "ad_group_name", "ad_group_id", "ad_group_status")
)
if not any(x["platform"] == "Facebook" for x in rows):
    raise RuntimeError("No Facebook attribution choices produced")
if not any(x["platform"] == "Google" for x in rows):
    raise RuntimeError("No Google attribution choices produced")

result = post_json(CALLBACK, {"mode":"catalog","token":TOKEN,"rows":rows}, timeout=180)
if not result.get("ok"):
    raise RuntimeError("Catalogue publish failed")

orders = (shopify_graphql(ORDER_JOURNEY_QUERY, {"first": 100}).get("orders") or {}).get("nodes") or []
updates = []
errors = []

for order in orders:
    # Never replace a campaign already saved in Shopify.
    campaign_exists = bool((order.get("campaignField") or {}).get("value"))
    source_exists = bool((order.get("sourceField") or {}).get("value"))

    best = None
    for visit in journey_visits(order.get("customerJourneySummary")):
        m = match_visit(visit, rows)
        if not m:
            continue
        hit, score, method = m
        if best is None or score > best[1]:
            best = (visit, score, method, hit)

    if not best:
        continue

    visit, score, method, hit = best
    utm = visit.get("utmParameters") or {}
    platform = hit["platform"]

    # A confident match to the ad catalogue means the order came through that
    # paid platform. Only fill the broad source when it is currently blank.
    auto_source = None
    if not source_exists:
        if platform == "Facebook":
            auto_source = "FB Online Orders - WEB"
        elif platform == "Google":
            auto_source = "Google Online Orders - WEB"

    values = {}
    if not campaign_exists:
        values.update({
            "attribution_platform": platform,
            "attribution_campaign": hit["campaign_name"],
            "attribution_campaign_id": hit["campaign_id"],
            "attribution_ad_set": hit.get("adset_name"),
            "attribution_ad_set_id": hit.get("adset_id"),
        })
    if auto_source:
        values["order_source"] = auto_source

    try:
        shopify_set(order["id"], values)
    except Exception as exc:
        errors.append(f'{order.get("name")}: {exc}')
        continue

    updates.append({
        "order_id": order["id"],
        "order_source": auto_source,
        "campaign_platform": platform,
        "campaign_id": hit["campaign_id"],
        "campaign_name": hit["campaign_name"],
        "adset_id": hit.get("adset_id"),
        "adset_name": hit.get("adset_name"),
        "utm_source": utm.get("source"),
        "utm_medium": utm.get("medium"),
        "utm_campaign": utm.get("campaign"),
        "utm_content": utm.get("content"),
        "utm_term": utm.get("term"),
        "attribution_match_method": method,
    })

if updates:
    result = post_json(
        CALLBACK,
        {"mode":"auto_attribution","token":TOKEN,"updates":updates},
        timeout=180,
    )
    if not result.get("ok"):
        raise RuntimeError("Auto-attribution queue update failed")

print(
    "Attribution catalogue refreshed:",
    sum(1 for x in rows if x["platform"] == "Facebook"), "Facebook rows,",
    sum(1 for x in rows if x["platform"] == "Google"), "Google rows;",
    "auto-matched", len(updates), "recent Shopify orders.",
)
if errors:
    print("Auto-attribution warnings:", " | ".join(errors[:10]))
