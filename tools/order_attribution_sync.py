"""Sync an order attribution choice and optional contact details to Shopify.
Environment: SHOPIFY_TOKEN, SHOPIFY_SHOP, ORDER_ID, ORDER_SOURCE, optional ORDER_EMAIL / ORDER_PHONE, CALLBACK_TOKEN.
"""
import json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOP = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
API = f"https://{SHOP}/admin/api/2026-04/graphql.json"

MUTATION = """mutation UpdateOrderAttribution($input:OrderInput!){
  orderUpdate(input:$input){
    order{
      id email phone
      metafield(namespace:"custom",key:"order_source"){value}
    }
    userErrors{field message}
  }
}"""

def post(url, payload, headers):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=45) as res:
        return json.load(res) if res.headers.get_content_type() == "application/json" else {}

def callback(ok, error=""):
    cfg = open(os.path.join(ROOT, "config.js"), encoding="utf-8").read()
    url = re.search(r'url:\s*"([^"]+)"', cfg).group(1)
    key = re.search(r'key:\s*"([^"]+)"', cfg).group(1)
    post(
        url + "/functions/v1/order-attribution-callback",
        {
            "order_id": os.environ["ORDER_ID"],
            "token": os.environ["CALLBACK_TOKEN"],
            "ok": bool(ok),
            "error": str(error)[:500],
        },
        {"Content-Type": "application/json", "apikey": key},
    )

def main():
    for k in ("SHOPIFY_TOKEN", "ORDER_ID", "ORDER_SOURCE", "CALLBACK_TOKEN"):
        if not os.environ.get(k):
            raise RuntimeError(f"{k} is missing")

    order_input = {
        "id": os.environ["ORDER_ID"],
        "metafields": [{
            "namespace": "custom",
            "key": "order_source",
            "type": "single_line_text_field",
            "value": os.environ["ORDER_SOURCE"],
        }],
    }
    email = os.environ.get("ORDER_EMAIL", "").strip()
    phone = os.environ.get("ORDER_PHONE", "").strip()
    if email:
        order_input["email"] = email
    if phone:
        order_input["phone"] = phone

    out = post(
        API,
        {"query": MUTATION, "variables": {"input": order_input}},
        {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": os.environ["SHOPIFY_TOKEN"],
        },
    )
    if out.get("errors"):
        raise RuntimeError("Shopify GraphQL error: " + json.dumps(out["errors"])[:500])
    user_errors = (((out.get("data") or {}).get("orderUpdate") or {}).get("userErrors") or [])
    if user_errors:
        raise RuntimeError("Shopify rejected update: " + "; ".join(x.get("message", "") for x in user_errors)[:500])

if __name__ == "__main__":
    try:
        main()
        callback(True)
        print("Order source/contact details synced to Shopify.")
    except Exception as e:
        try:
            callback(False, e)
        except Exception as cb:
            print("Callback failed:", cb, file=sys.stderr)
        print("FAILED:", e, file=sys.stderr)
        raise
