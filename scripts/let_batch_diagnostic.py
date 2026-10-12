#!/usr/bin/env python3
"""One-off anonymous LET thread status check."""
import time
from lowendtalk_monitor import fetch_page,classify_reply
p=fetch_page(40)
last=max(p.pages)
print("LAST_PAGE",last,flush=True)
if last>65:raise SystemExit("too many pages")
rows={}
for n in range(37,last+1):
    if n>37:time.sleep(1.5)
    page=p if n==40 else fetch_page(n)
    print("PAGE",n,"ROWS",len(page.comments),flush=True)
    for item in page.comments:rows[item["id"]]=item
for r in sorted(rows.values(),key=lambda x:x["id"]):
    if r["author"]!="dustinc":continue
    t=r.get("own_text") or r["text"]
    cat,kw=classify_reply(t)
    if "RackNerd & AdminBolt Giveaway!" in t:print("BATCH",r["id"],r.get("created_at"),repr(t[:1800]),flush=True)
    elif cat in ("warmup","winners") or any(x in t.lower() for x in ("winner","remaining","giveaway","claimed","license")):print("DUSTINC",r["id"],r.get("created_at"),cat,repr(t[:420]),flush=True)
print("LATEST",max(rows),rows[max(rows)].get("created_at"),flush=True)
