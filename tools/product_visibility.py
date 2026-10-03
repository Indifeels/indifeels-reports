"""Build the encrypted Product visibility report for the Indifeels dashboard.

Section 1: UNLISTED products with stock available.
Section 2: ACTIVE products with stock where one or more merchant sales channels are off.

Env:
  SHOPIFY_TOKEN  Admin API token with read_products access
  SHOPIFY_SHOP   myshopify domain
  STOCK_KEY      base64 AES-256 key reused from the Stock report access group

Writes:
  r/product-visibility.bin
  r/product-visibility.meta.bin
  r/status.json
"""
import base64
import datetime as dt
import gzip
import html
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RDIR = os.path.join(ROOT, "r")
TOOLS = os.path.join(ROOT, "tools")
SHOP = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
API = f"https://{SHOP}/admin/api/2026-04/graphql.json"
RID = "product-visibility"
NOW = dt.datetime.now(ZoneInfo("Australia/Sydney"))

PRODUCTS = """
query ProductVisibility($after:String,$q:String!){
  products(first:100,after:$after,query:$q,sortKey:TITLE){
    pageInfo{hasNextPage endCursor}
    nodes{
      id title handle status totalInventory onlineStoreUrl publishedAt
      featuredMedia{preview{image{url}}}
      variants(first:100){nodes{id title sku inventoryQuantity}}
      unpublishedPublications(first:50){nodes{id catalog{title}}}
    }
  }
}
"""

SALES_CHANNEL_FILTERS = [\n    ("Online Store", "published_status:unpublished"),\n    ("Shop", "published_status:shop-72-hidden"),\n    ("Point of Sale", "published_status:pos-hidden"),\n    ("Google & YouTube", "published_status:google-hidden"),\n    ("Facebook & Instagram", "published_status:facebook-ads-hidden"),\n]


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
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
            raise RuntimeError("Shopify query error: " + json.dumps(out["errors"])[:240])
        return out
    raise RuntimeError("Shopify API kept throttling")


def fetch_products(search):
    rows, after = [], None
    while True:
        data = gql(PRODUCTS, {"after": after, "q": search})["data"]["products"]
        rows.extend(data["nodes"])
        if not data["pageInfo"]["hasNextPage"]:
            return rows
        after = data["pageInfo"]["endCursor"]


def e(value):
    return html.escape(str(value or ""), quote=True)


def in_stock_variants(product):
    return [
        v
        for v in product.get("variants", {}).get("nodes", [])
        if (v.get("inventoryQuantity") or 0) > 0
    ]


def channel_issue_products():
    """Return active in-stock products grouped with merchant sales channels that are off.

    Uses Shopify's published_status product-search filter, which only requires read_products.
    This avoids requiring read_publications on the GitHub Actions token.
    """
    merged = {}
    for channel, visibility_filter in SALES_CHANNEL_FILTERS:
        for product in fetch_products(f"status:active inventory_total:>0 {visibility_filter}"):
            row = merged.setdefault(product["id"], {"product": product, "channels": []})
            if channel not in row["channels"]:
                row["channels"].append(channel)
    return sorted(
        [(row["product"], row["channels"]) for row in merged.values()],
        key=lambda x: (x[0].get("title") or "").lower(),
    )
