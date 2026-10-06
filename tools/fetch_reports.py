"""Fetch read-only inputs for IndiFeels Daily and Monthly reports.
No write actions are performed against Windsor or Shopify.
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

OUT=sys.argv[1]
os.makedirs(OUT,exist_ok=True)
tz=ZoneInfo("Australia/Sydney")
if os.environ.get("REPORT_NOW"):
    report_now=datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(tz)
    end=report_now.date().isoformat()
else:
    end=(datetime.now(tz).date()-timedelta(days=1)).isoformat()
start=os.environ.get("REPORT_START","2026-03-01")
acct=os.environ.get("WINDSOR_FACEBOOK_ACCOUNT","1634084963432990")

fields="date,campaign,campaign_id,campaign_status,campaign_start_time,spend,impressions,clicks,reach,actions_onsite_conversion_messaging_conversation_started_7d"
params=urllib.parse.urlencode({"api_key":os.environ["WINDSOR_API_KEY"],"date_from":start,"date_to":end,"fields":fields,"select_accounts":acct})
with urllib.request.urlopen("https://connectors.windsor.ai/facebook?"+params,timeout=120) as r:
    w=json.load(r)
rows=w.get("data",w) if isinstance(w,dict) else w
if not isinstance(rows,list) or not rows:
    raise RuntimeError("Windsor returned no Meta rows")
# This report is strictly Non-Tracked Meta messaging campaigns. Never mix Tracked campaigns.
rows=[r for r in rows if ("non tracked" in (r.get("campaign") or "").lower().replace("-"," ") and "tracked |" not in (r.get("campaign") or "").lower().replace("non tracked",""))]
if not rows:
    raise RuntimeError("Windsor returned no Non-Tracked Meta rows")
w = dict(w, data=rows) if isinstance(w,dict) else rows
json.dump(w,open(os.path.join(OUT,"windsor_01.json"),"w"))

# Ad-set level rows for the Daily report's expandable ad sets (separate file: monthly.py reads windsor*.json only).
afields="date,campaign,campaign_id,campaign_status,campaign_start_time,adset_id,adset_name,adset_status,spend,actions_onsite_conversion_messaging_conversation_started_7d"
aparams=urllib.parse.urlencode({"api_key":os.environ["WINDSOR_API_KEY"],"date_from":start,"date_to":end,"fields":afields,"select_accounts":acct})
with urllib.request.urlopen("https://connectors.windsor.ai/facebook?"+aparams,timeout=180) as r:
    aw=json.load(r)
arows=aw.get("data",aw) if isinstance(aw,dict) else aw
if not isinstance(arows,list):
    raise RuntimeError("Windsor returned an unexpected ad-set response")
arows=[r for r in arows if ("non tracked" in (r.get("campaign") or "").lower().replace("-"," ") and "tracked |" not in (r.get("campaign") or "").lower().replace("non tracked",""))]
json.dump({"data":arows},open(os.path.join(OUT,"adset_01.json"),"w"))
print("ad-set rows:",len(arows))

shop=os.environ.get("SHOPIFY_SHOP","bvdxj3-r8.myshopify.com")
api="https://"+shop+"/admin/api/2026-04/graphql.json"
q='''query($after:String,$query:String!){ orders(first:250,after:$after,query:$query,sortKey:PROCESSED_AT){ pageInfo{hasNextPage endCursor} nodes{id name processedAt cancelledAt sourceName m:metafield(namespace:"custom",key:"order_source"){value} t:currentTotalPriceSet{shopMoney{amount currencyCode}} } } }'''
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
