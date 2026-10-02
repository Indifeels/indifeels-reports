"""Fetch read-only inputs for IndiFeels Daily and Monthly reports.
No write actions are performed against Windsor or Shopify.
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

OUT=sys.argv[1]
os.makedirs(OUT,exist_ok=True)
end=(datetime.now(ZoneInfo("Australia/Sydney")).date()-timedelta(days=1)).isoformat()
start=os.environ.get("REPORT_START","2026-03-01")
acct=os.environ.get("WINDSOR_FACEBOOK_ACCOUNT","1634084963432990")

fields="date,campaign,campaign_id,campaign_status,campaign_start_time,spend,impressions,clicks,reach,actions_onsite_conversion_messaging_conversation_started_7d"
params=urllib.parse.urlencode({"api_key":os.environ["WINDSOR_API_KEY"],"date_from":start,"date_to":end,"fields":fields,"select_accounts":acct})
with urllib.request.urlopen("https://connectors.windsor.ai/facebook?"+params,timeout=120) as r:
    w=json.load(r)
rows=w.get("data",w) if isinstance(w,dict) else w
if not isinstance(rows,list) or not rows:
    raise RuntimeError("Windsor returned no Meta rows")
json.dump(w,open(os.path.join(OUT,"windsor_01.json"),"w"))

shop=os.environ.get("SHOPIFY_SHOP","bvdxj3-r8.myshopify.com")
api="https://"+shop+"/admin/api/2026-04/graphql.json"
q='''query($after:String,$query:String!){ orders(first:250,after:$after,query:$query,sortKey:PROCESSED_AT){ pageInfo{hasNextPage endCursor} nodes{name processedAt cancelledAt sourceName m:metafield(namespace:"custom",key:"order_source"){value} t:currentTotalPriceSet{shopMoney{amount currencyCode}} } } }'''
nodes=[]; after=None
while True:
    body=json.dumps({"query":q,"variables":{"after":after,"query":"processed_at:>="+start}}).encode()
    req=urllib.request.Request(api,body,{"Content-Type":"application/json","X-Shopify-Access-Token":os.environ["SHOPIFY_TOKEN"]})
    with urllib.request.urlopen(req,timeout=120) as r:
        x=json.load(r)
    if x.get("errors"):
        raise RuntimeError("Shopify GraphQL error: "+json.dumps(x["errors"])[:300])
    c=x["data"]["orders"]; nodes.extend(c["nodes"])
    if not c["pageInfo"]["hasNextPage"]: break
    after=c["pageInfo"]["endCursor"]; time.sleep(.3)
if not nodes:
    raise RuntimeError("Shopify returned no orders")
json.dump({"data":{"orders":{"nodes":nodes}}},open(os.path.join(OUT,"shopify_01.json"),"w"))
print("inputs ready through",end,":",len(rows),"Meta rows,",len(nodes),"Shopify orders")
