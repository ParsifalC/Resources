#!/usr/bin/env python3
"""One-shot anonymous audit of RackNerd giveaway rounds; no retries, no login."""
from datetime import datetime,timezone,timedelta
import re
import time
from lowendtalk_monitor import fetch_page,classify_reply

first=fetch_page(1)
last=max(first.pages)
print("CURRENT_PAGE_COUNT",last,flush=True)
if last>45:
    print("STOP: page bound exceeded",flush=True)
    raise SystemExit(2)
pages={}
for p in [18,22,23]+list(range(24,last+1)):
    if pages:time.sleep(1.5)
    r=fetch_page(p)
    pages[p]=r.comments
    print("PAGE",p,"COUNT",len(r.comments),
          "ID_RANGE",(r.comments[0]["id"],r.comments[-1]["id"]) if r.comments else None,flush=True)
announcements=[]
all_dustinc=[]
for p in sorted(pages):
    for i,r in enumerate(pages[p]):
        if r["author"]!="dustinc":continue
        raw=r.get("own_text") or r["text"]
        cat,keyword=classify_reply(raw)
        is_round=bool(re.search(r'RackNerd\\s*&\\s*AdminBolt Giveaway!|the next 10 (?:eligible )?comments|next (?:ten|10) eligible comments',raw,re.I))
        rec=(p,i,r["id"],r.get("created_at"),cat,keyword,raw)
        all_dustinc.append(rec)
        if is_round: announcements.append(rec)
print("ROUNDS_POSTED",len(announcements),flush=True)
for p,i,id,dt,cat,key,t in announcements:
    print("GIVEAWAY",id,"PAGE",p,"INDEX",i,"UTC",dt,"CLASS",cat,
          "KEYWORD",repr(key),"TEXT",repr(t[:1900]),flush=True)
for a,b in zip(announcements,announcements[1:]):
    ap,ai,aid,adt,*_=a;bp,bi,bid,bdt,*_=b
    if all(p in pages for p in range(ap,bp+1)):
        num=sum(1 for p in range(ap,bp+1) for r in pages[p] if aid<r["id"]<bid)
        print("ROUND_GAP",aid,bid,"COUNT",num,"MODE","full-scan",flush=True)
    else:
        print("ROUND_GAP",aid,bid,"COUNT",30*(bp-ap)+bi-ai-1,"MODE","page-arithmetic",flush=True)
print("DUSTINC_LAST_25",flush=True)
for p,i,id,dt,cat,key,t in all_dustinc[-25:]:
    print("DUSTINC",id,"UTC",dt,"CLASS",cat,"KEYWORD",repr(key),"TEXT",repr(t[:450]),flush=True)
latest=pages[last][-1]
print("LATEST",latest["id"],latest["author"],latest.get("created_at"),flush=True)
