"""Refresh Shopify Customer Journey details used by Order Attribution.

Runs every 15 minutes and can also refresh one order on demand.
Environment:
  SHOPIFY_TOKEN, SYNC_READ_TOKEN
Optional:
  SHOPIFY_SHOP, ORDER_ID, ORDER_ATTRIBUTION_CALLBACK
"""
import json
import os
import urllib.request

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
  occurredAt
  source
  sourceDescription
  referrerUrl
  landingPage
  utmParameters { source medium campaign term content }
"""

ONE = f"""query OrderJourney($id:ID!){{
  order(id:$id){{
    id name createdAt
    customerJourneySummary{{
      ready daysToConversion customerOrderIndex
      firstVisit{{{VISIT}}}
      lastVisit{{{VISIT}}}
    }}
  }}
}}"""

MANY = f"""query RecentOrderJourneys($first:Int!){{
  orders(first:$first, sortKey:CREATED_AT, reverse:true){{
    nodes{{
      id name createdAt
      customerJourneySummary{{
        ready daysToConversion customerOrderIndex
        firstVisit{{{VISIT}}}
        lastVisit{{{VISIT}}}
      }}
    }}
  }}
}}"""


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
    )
    if out.get("errors"):
        raise RuntimeError("Shopify GraphQL: " + json.dumps(out["errors"])[:1000])
    return out.get("data") or {}


def clean_visit(v):
    if not isinstance(v, dict):
        return None
    u = v.get("utmParameters") or {}
    return {
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


def to_update(order):
    summary = order.get("customerJourneySummary") or {}
    ready = summary.get("ready") is True
    journey = {
        "order_name": order.get("name"),
        "order_created_at": order.get("createdAt"),
        "ready": ready,
        "days_to_conversion": summary.get("daysToConversion"),
        "customer_order_index": summary.get("customerOrderIndex"),
        "first_visit": clean_visit(summary.get("firstVisit")) if ready else None,
        "last_visit": clean_visit(summary.get("lastVisit")) if ready else None,
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

    updates = [to_update(o) for o in orders if isinstance(o, dict) and o.get("id")]
    if not updates:
        print("No Shopify orders returned.")
        return

    out = post_json(
        CALLBACK,
        {"mode": "journey", "token": SYNC_TOKEN, "updates": updates},
        timeout=90,
    )
    if not out.get("ok"):
        raise RuntimeError("Journey callback failed: " + json.dumps(out)[:1000])

    ready = sum(1 for x in updates if x["ready"])
    print(f"Order journey refresh: checked {len(updates)}, ready {ready}, queue updates {out.get('updated', 0)}.")


if __name__ == "__main__":
    main()
