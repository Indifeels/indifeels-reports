"""Fix product visibility in Shopify.

Actions:
  check      Verify the GitHub Shopify token scopes.
  fix-one    Set one product ACTIVE and publish it to all normal Indifeels sales channels.
  fix-all    Re-scan live Shopify and fix every in-stock UNLISTED product and every active
             in-stock product hidden from one or more normal sales channels.
  ignore     Archive one product so it no longer appears in this visibility report.
  delete     Permanently delete one product from Shopify.

Stock/inventory is never mutated by this script.

Env:
  SHOPIFY_TOKEN
  SHOPIFY_SHOP
  FIX_ACTION      fix-one | fix-all | ignore | delete (optional when CLI command is supplied)
  PRODUCT_ID      gid://shopify/Product/... for fix-one, ignore or delete
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

SHOP = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
API = f"https://{SHOP}/admin/api/2026-04/graphql.json"

PUBLICATIONS = [
    ("Online Store", "gid://shopify/Publication/260418306405"),
    ("Shop", "gid://shopify/Publication/260418371941"),
    ("Point of Sale", "gid://shopify/Publication/260418404709"),
    ("Google & YouTube", "gid://shopify/Publication/261314052453"),
    ("Facebook & Instagram", "gid://shopify/Publication/261314150757"),
]

FILTERS = [
    "status:unlisted inventory_total:>0",
    "status:active inventory_total:>0 published_status:unpublished",
    "status:active inventory_total:>0 published_status:shop-72-hidden",
    "status:active inventory_total:>0 published_status:pos-hidden",
    "status:active inventory_total:>0 published_status:google-hidden",
    "status:active inventory_total:>0 published_status:facebook-ads-hidden",
]

SCOPES = """query FixScopes { currentAppInstallation { accessScopes { handle } } }"""
PRODUCTS = """query FixCandidates($after:String,$q:String!){
 products(first:100,after:$after,query:$q,sortKey:ID){
  pageInfo{hasNextPage endCursor}
  nodes{id title status totalInventory}
 }
}"""
UPDATE = """mutation FixProductStatus($product:ProductUpdateInput!){
 productUpdate(product:$product){
  product{id status}
  userErrors{field message}
 }
}"""
PUBLISH = """mutation PublishProduct($id:ID!,$input:[PublicationInput!]!){
 publishablePublish(id:$id,input:$input){
  userErrors{field message}
 }
}"""
DELETE = """mutation DeleteProduct($input:ProductDeleteInput!){
 productDelete(input:$input,synchronous:true){
  deletedProductId
  userErrors{field message}
 }
}"""


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for attempt in range(5):
        req = urllib.request.Request(
            API,
            body,
            {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": os.environ["SHOPIFY_TOKEN"],
            },
        )
        try:
            out = json.load(urllib.request.urlopen(req, timeout=90))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"Shopify API returned HTTP {exc.code}") from exc
        if out.get("errors"):
            if any("THROTTLED" in json.dumps(x) for x in out["errors"]) and attempt < 4:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError("Shopify query error: " + json.dumps(out["errors"])[:500])
        return out
    raise RuntimeError("Shopify API kept throttling")


def access_scopes():
    rows = gql(SCOPES)["data"]["currentAppInstallation"]["accessScopes"]
    return {x["handle"] for x in rows}


def require_scopes(needed=None):
    scopes = access_scopes()
    needed = set(needed or {"write_products", "write_publications"})
    missing = sorted(needed - scopes)
    print(json.dumps({
        "required": sorted(needed),
        "available_required": sorted(needed & scopes),
        "missing": missing,
    }))
    if missing:
        raise RuntimeError("Shopify token is missing required scope(s): " + ", ".join(missing))
    return scopes


def fetch(search):
    out, after = [], None
    while True:
        page = gql(PRODUCTS, {"q": search, "after": after})["data"]["products"]
        out.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return out
        after = page["pageInfo"]["endCursor"]


def candidates():
    merged = {}
    for search in FILTERS:
        for product in fetch(search):
            merged[product["id"]] = product
    return sorted(merged.values(), key=lambda x: (x.get("title") or "").lower())


def errors(payload):
    return payload.get("userErrors") or []


def product_id_from_env():
    product_id = os.environ.get("PRODUCT_ID", "").strip()
    if not product_id.startswith("gid://shopify/Product/"):
        raise RuntimeError("PRODUCT_ID is missing or invalid")
    return product_id


def archive_product(product_id):
    out = gql(UPDATE, {"product": {"id": product_id, "status": "ARCHIVED"}})["data"]["productUpdate"]
    if errors(out):
        raise RuntimeError("Could not archive product: " + "; ".join(x["message"] for x in errors(out)))


def delete_product(product_id):
    out = gql(DELETE, {"input": {"id": product_id}})["data"]["productDelete"]
    if errors(out):
        raise RuntimeError("Could not delete product: " + "; ".join(x["message"] for x in errors(out)))


def fix_product(product_id):
    up = gql(UPDATE, {"product": {"id": product_id, "status": "ACTIVE"}})["data"]["productUpdate"]
    if errors(up):
        raise RuntimeError("Could not set ACTIVE: " + "; ".join(x["message"] for x in errors(up)))
    pub = gql(PUBLISH, {
        "id": product_id,
        "input": [{"publicationId": pid} for _, pid in PUBLICATIONS],
    })["data"]["publishablePublish"]
    if errors(pub):
        raise RuntimeError("Could not publish to all channels: " + "; ".join(x["message"] for x in errors(pub)))


def main():
    action = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FIX_ACTION", "")).strip()
    if action == "check":
        require_scopes()
        print("visibility fix scopes: ok")
        return

    if action == "ignore":
        require_scopes({"write_products"})
        product_id = product_id_from_env()
        archive_product(product_id)
        print(json.dumps({"ignored": 1, "product_id": product_id}))
        return

    if action == "delete":
        require_scopes({"write_products"})
        product_id = product_id_from_env()
        delete_product(product_id)
        print(json.dumps({"deleted": 1, "product_id": product_id}))
        return

    if action == "fix-one":
        require_scopes({"write_products", "write_publications"})
        product_id = product_id_from_env()
        fix_product(product_id)
        print(json.dumps({"fixed": 1, "product_id": product_id}))
        return

    if action == "fix-all":
        require_scopes({"write_products", "write_publications"})
        rows = candidates()
        fixed, failed = 0, []
        for product in rows:
            try:
                fix_product(product["id"])
                fixed += 1
            except Exception as exc:
                failed.append({"id": product["id"], "title": product.get("title"), "error": str(exc)[:300]})
            time.sleep(0.12)
        print(json.dumps({"candidates": len(rows), "fixed": fixed, "failed": failed}))
        if failed:
            raise RuntimeError(f"{len(failed)} product(s) could not be fully fixed")
        return

    raise RuntimeError("FIX_ACTION must be fix-one, fix-all, ignore or delete")


if __name__ == "__main__":
    main()
