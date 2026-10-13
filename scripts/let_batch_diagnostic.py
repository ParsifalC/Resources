#!/usr/bin/env python3
"""Single anonymous status check of recent LET giveaway announcements. No retries."""
import time
from lowendtalk_monitor import fetch_page, classify_reply
first=fetch_page(1)
last=max(first.pages)
print("LAST_PAGE",last,flush=True)
if last>85: raise ValueError("Thread too large for bounded diagnostic")
start=min(last,37)
records={}
for n in range(start,last+1):
    if n>start:time.sleep(1.2)
    p=fetch_page(n)
    print("PAGE",n,"ROWS",len(p.comments),"LAST_ID",p.comments[-1]["id"],flush=True)
    for r in p.comments:records[r["id"]]=r
if last>=2:
    print("LATEST_COMMENT",max(records),records[max(records)].get("created_at"),flush=True)
dus=[]
for r in sorted(records.values(),key=lambda x:x["id"]):
    if r["author"]!="dustinc": continue
    t=r.get("own_text") or r["text"]
    c,k=classify_reply(t)
    if "racknerd & adminbolt giveaway!" in t.casefold() and "free" in t.casefold():
        print("BATCH",r["id"],r.get("created_at"),"KEYWORD",repr(k),"TEXT",repr(t[:1800]),flush=True)
    dus.append((r["id"],r.get("created_at"),c,repr(t[:550])))
print("LATEST_DUSTINC_POSTS",flush=True)
for row in dus[-32:]:print("HOST",*row,flush=True)
print("DONE",flush=True)
