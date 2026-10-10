#!/usr/bin/env python3
"""Anonymous one-shot audit: count actual discussion comments between giveaway rounds."""
import time
from datetime import datetime, timezone, timedelta
from lowendtalk_monitor import fetch_page, classify_reply

target_ids=(4878613,4878728,4879099,4879274,4879585)
loaded={}
def get(page):
    if page not in loaded:
        if loaded: time.sleep(2.5)
        parsed=fetch_page(page)
        loaded[page]=parsed
        print("PAGE",page,"COMMENTS",len(parsed.comments),"ID_RANGE",
              (parsed.comments[0]["id"],parsed.comments[-1]["id"]) if parsed.comments else None,
              "LAST",max(parsed.pages),flush=True)
    return loaded[page]

first=get(1)
latest=max(first.pages)
# The known announcements span early pages through page 14.
for p in (3,6,7,9,10,11,12,13,14):
    get(p)
def discover():
    found={}
    for page,parsed in loaded.items():
        for index,row in enumerate(parsed.comments):
            if row['id'] in target_ids:
                found[row['id']]=(page,index,row)
    return found
found=discover()
remaining=[x for x in target_ids if x not in found]
print("INITIAL_TARGETS_FOUND", sorted(found),"MISSING",remaining,flush=True)
if remaining:
    for p in range(2,min(latest,16)+1):
        if p not in loaded:
            get(p)
            found=discover()
            if all(x in found for x in target_ids):break
if latest>14 and latest<=21:
    get(latest)
    for p in range(15,latest):
        if p not in loaded and p>=17: get(p)
print("LAST_PAGE",latest,flush=True)
print("BATCH_POSITIONS")
for id in target_ids:
    if id not in found:
        print("MISSING_ANNOUNCEMENT",id)
        continue
    page,index,row=found[id]
    print("BATCH",id,"PAGE",page,"INDEX_0",index,"POSTED_UTC",row.get("created_at"),"AUTHOR",row.get("author"),
          "TEXT",repr((row.get("own_text") or row.get("text"))[:180]),flush=True)
print("INTERVALS")
for a,b in zip(target_ids,target_ids[1:]):
    if a not in found or b not in found: continue
    pa,ia,ra=found[a]
    pb,ib,rb=found[b]
    if any(p not in loaded for p in range(pa,pb+1)):
        # A complete 30-comment non-final page makes the index arithmetic exact.
        if any(len(loaded[p].comments)!=30 for p in (pa,pb)):
            print("INSUFFICIENT_PAGE_COUNTS",a,b);continue
        count=30*(pb-pa)+(ib-ia)-1
        source="30_PER_PAGE"
    else:
        middle=[]
        for p in range(pa,pb+1):
            middle.extend(row for row in loaded[p].comments if a<row['id']<b)
        count=len(middle);source="FULL_SCAN"
    posts=(datetime.fromisoformat(rb["created_at"])-datetime.fromisoformat(ra["created_at"]))
    print("GAP",a,b,"REPLIES",count,"SOURCE",source,
          "INCLUDING_NEXT_ANNOUNCEMENT",count+1,"ELAPSED",str(posts),flush=True)
print("LATEST_ANNOUNCEMENTS")
for p in sorted(loaded):
    if p>=15:
        for r in loaded[p].comments:
            if r['author']=='dustinc':
                category,keyword=classify_reply(r.get('own_text') or r['text'])
                if category=='giveaway':
                    print("NEW_GIVEAWAY",r['id'],r.get('created_at'),repr(keyword),flush=True)
