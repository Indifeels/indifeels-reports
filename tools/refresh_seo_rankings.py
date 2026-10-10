"""Refresh saved SEO snapshots using finalized Windsor Search Console data."""
import json,os,re,urllib.parse,urllib.request,urllib.error
from datetime import datetime,timedelta,date
from zoneinfo import ZoneInfo
from collections import defaultdict
CALLBACK="https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/seo-rank-refresh"
def post(body):
    body["token"]=os.environ["SYNC_READ_TOKEN"]
    req=urllib.request.Request(CALLBACK,json.dumps(body).encode(),{"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=120) as r: result=json.load(r)
    except urllib.error.HTTPError as e:
        detail=json.loads(e.read()).get("error","unknown callback error")
        raise RuntimeError("SEO callback HTTP "+str(e.code)+": "+str(detail)) from None
    if result.get("error"): raise RuntimeError(result["error"])
    return result
def fetch(fields,start,end):
    params=urllib.parse.urlencode({"api_key":os.environ["WINDSOR_API_KEY"],"select_accounts":"sc-domain:indifeels.com","fields":",".join(fields),"date_from":start,"date_to":end,"include_fresh_data":"false"})
    try:
        with urllib.request.urlopen("https://connectors.windsor.ai/searchconsole?"+params,timeout=300) as r: raw=json.load(r)
    except Exception:
        # Do not log request URLs containing the API key.
        raise RuntimeError("Windsor Search Console request failed") from None
    rows=raw.get("data") if isinstance(raw,dict) else raw
    if not isinstance(rows,list) or not rows: raise RuntimeError("Windsor returned no usable Search Console rows")
    if isinstance(raw,dict) and any(raw.get(k) for k in ("next","next_page","next_page_token","has_more","error")): raise RuntimeError("Incomplete Windsor response")
    return rows
def norm(v):return re.sub(r"[^a-z0-9]+","",str(v or "").lower())
def path(v):return urllib.parse.urlsplit(str(v)).path.rstrip("/")
def aggregate(rows):
    imp=sum(float(r.get("impressions") or 0) for r in rows)
    clicks=sum(float(r.get("clicks") or 0) for r in rows)
    weighted=sum(float(r["position"])*float(r.get("impressions") or 0) for r in rows if r.get("position") is not None)
    weight=sum(float(r.get("impressions") or 0) for r in rows if r.get("position") is not None)
    return int(round(clicks)),int(round(imp)),weighted/weight if weight else None
def main():
    today=datetime.now(ZoneInfo("Australia/Melbourne")).date()
    daily=fetch(["date","clicks","impressions"],(today-timedelta(days=10)).isoformat(),(today-timedelta(days=1)).isoformat())
    through=max(date.fromisoformat(r["date"][:10]) for r in daily if float(r.get("impressions") or 0)>0)
    if through<today-timedelta(days=10):raise RuntimeError("GSC cutoff is stale")
    start=(through-timedelta(days=27)).isoformat();end=through.isoformat()
    products=post({"mode":"export"})["products"]
    if not products:raise RuntimeError("No tracked products")
    pages=fetch(["date","page","clicks","impressions","position"],start,end)
    queries=fetch(["date","page","query","clicks","impressions","position"],start,end)
    pp=defaultdict(list);qq=defaultdict(list)
    for r in pages:
        if start<=r["date"][:10]<=end:pp[path(r["page"])].append(r)
    for r in queries:
        if start<=r["date"][:10]<=end:qq[path(r["page"])].append(r)
    updates=[];matched=0
    for p in products:
        key=path(p["url"]);rs=pp[key]
        if rs:matched+=1
        clicks,imp,pos=aggregate(rs)
        byq=defaultdict(list)
        for r in qq[key]:byq[str(r["query"])].append(r)
        qs=[]
        for q,qr in byq.items():
            c,i,v=aggregate(qr)
            if i:qs.append({"q":q,"clicks":c,"impressions":i,"position":v})
        qs.sort(key=lambda x:(-x["impressions"],-x["clicks"],x["q"]))
        target=[r for r in qq[key] if norm(r["query"])==norm(p["target_keyword"]) and norm(p["target_keyword"])]
        tc,ti,tp=aggregate(target)
        top=qs[0] if qs else {}
        updates.append({"category_id":p["category_id"],"handle":p["handle"],"clicks":clicks,"impressions":imp,"avg_position":pos,"target_position":tp,"target_impressions":ti,"top_query":top.get("q"),"top_query_position":top.get("position"),"top_query_impressions":top.get("impressions",0),"top_queries":qs})
    if not matched:raise RuntimeError("No tracked products matched; preserving saved report")
    result=post({"mode":"publish","snapshot":today.isoformat(),"through":end,"rows":updates})
    print(json.dumps(result));print("Matched products:",matched,"of",len(products),"window",start,"to",end)
if __name__=="__main__":main()
