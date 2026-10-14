#!/usr/bin/env python3
"""One-off read-only scan of the latest LowEndTalk giveaway pages."""
import time
from lowendtalk_monitor import fetch_page, classify_reply
first=fetch_page(1)
last=max(first.pages)
start=max(1,last-17)
print("PAGES",last,"SCAN_FROM",start,flush=True)
if last>110:raise SystemExit("Too many pages for this check")
rows={}
for n in range(start,last+1):
    p=fetch_page(n)
    for r in p.comments:rows[r["id"]]=r
    print("PAGE",n,"COMMENTS",len(p.comments),"MAXID",max(x["id"] for x in p.comments),flush=True)
    if n<last:time.sleep(1.05)
for r in sorted(rows.values(),key=lambda v:v["id"]):
    if r["author"]!="dustinc":continue
    s=r.get("own_text") or r["text"]
    c,k=classify_reply(s)
    print("DUSTINC",r["id"],r.get("created_at"),c,repr(s[:2800]),flush=True)
print("LATEST",max(rows),rows[max(rows)].get("created_at"),flush=True)
