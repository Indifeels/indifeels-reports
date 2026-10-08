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

# Top ad (by spend) per ad set: its thumbnail is shown next to the ad set. Best effort only, never fails the report.
# Saved as adthumbs_01.json (not windsor*/adset*). Thumbnail bytes are embedded (base64) because Meta image links expire.
try:
    import base64
    tparams=urllib.parse.urlencode({"api_key":os.environ["WINDSOR_API_KEY"],"date_from":start,"date_to":end,"fields":"campaign,adset_id,ad_id,ad_name,thumbnail_url,spend","select_accounts":acct})
    with urllib.request.urlopen("https://connectors.windsor.ai/facebook?"+tparams,timeout=600) as r:
        tw=json.load(r)
    trows=tw.get("data",tw) if isinstance(tw,dict) else tw
    used={str(r.get("adset_id")) for r in arows}
    best={}
    for r in trows:
        k=str(r.get("adset_id"))
        if k in used and r.get("thumbnail_url") and float(r.get("spend") or 0)>=float((best.get(k) or {}).get("spend") or -1): best[k]=r
    bestn={}
    for r in trows:
        k=str(r.get("adset_id"))
        if k in used and r.get("ad_name") and float(r.get("spend") or 0)>=float((bestn.get(k) or {}).get("spend") or -1): bestn[k]=r
    json.dump({k:r["ad_name"] for k,r in bestn.items()},open(os.path.join(OUT,"adnames_01.json"),"w"))
    thumbs={}
    for k,r in best.items():
        e={"n":r.get("ad_name") or "","u":r["thumbnail_url"]}
        try:
            rq=urllib.request.Request(r["thumbnail_url"],headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(rq,timeout=25) as ir:
                bts=ir.read(8_000_001)
            if 0<len(bts)<=8_000_000:
                # Meta serves these at up to 1024px (often >60KB), which used to miss the size cap and leave the ad set blank.
                # Centre-crop to a square and shrink to 200px JPEG (~10-20KB, sharp at 88px on a retina screen).
                try:
                    import io
                    from PIL import Image
                    im=Image.open(io.BytesIO(bts)).convert("RGB"); w_,h_=im.size; s_=min(w_,h_)
                    im=im.crop(((w_-s_)//2,(h_-s_)//2,(w_-s_)//2+s_,(h_-s_)//2+s_)).resize((200,200),Image.LANCZOS)
                    buf=io.BytesIO(); im.save(buf,"JPEG",quality=82,optimize=True)
                    e["b"]=base64.b64encode(buf.getvalue()).decode()
                except Exception:
                    if len(bts)<=120000: e["b"]=base64.b64encode(bts).decode()
        except Exception: pass
        thumbs[k]=e
    json.dump(thumbs,open(os.path.join(OUT,"adthumbs_01.json"),"w"))
    print("ad thumbnails:",len(thumbs),"embedded:",sum(1 for v in thumbs.values() if v.get("b")))
except Exception as e:
    print("ad thumbnails skipped:",e)

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
# Product variants and stock, used for the stock bar on each ad set (best effort, never fails the report).
try:
    pq='''query($after:String){ products(first:25,after:$after,query:"status:active"){ pageInfo{hasNextPage endCursor} nodes{ title handle featuredImage{url} variants(first:25){nodes{title inventoryQuantity}} } } }'''
    pn=[]; pa=None
    while True:
        body=json.dumps({"query":pq,"variables":{"after":pa}}).encode()
        req=urllib.request.Request(api,body,{"Content-Type":"application/json","X-Shopify-Access-Token":os.environ["SHOPIFY_TOKEN"]})
        with urllib.request.urlopen(req,timeout=120) as r:
            px=json.load(r)
        if px.get("errors"): raise RuntimeError(json.dumps(px["errors"])[:300])
        pc=px["data"]["products"]
        for n_ in pc["nodes"]:
            pn.append({"t":n_["title"],"h":n_["handle"],"i":((n_.get("featuredImage") or {}).get("url") or ""),"v":[[v["title"],v["inventoryQuantity"]] for v in n_["variants"]["nodes"]]})
        if not pc["pageInfo"]["hasNextPage"]: break
        pa=pc["pageInfo"]["endCursor"]; time.sleep(.3)
    json.dump(pn,open(os.path.join(OUT,"adstock_01.json"),"w"))
    print("product stock:",len(pn),"products")
except Exception as e:
    print("product stock skipped:",e)
print("inputs ready through",end,":",len(rows),"Meta rows,",len(nodes),"Shopify orders")
