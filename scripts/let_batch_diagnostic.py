#!/usr/bin/env python3
"""One-off anonymous audit of user's recent comments; no account logins or retries."""
from datetime import datetime
import time
from lowendtalk_monitor import fetch_page, classify_reply

first=fetch_page(1)
last=max(first.pages)
print("LAST_PAGE",last,flush=True)
if last>40:
    print("PAGE_GUARD_STOP",last,flush=True)
    raise SystemExit(1)
records={}
start=max(2,last-6)
for page in range(start,last+1):
    if records:time.sleep(1.5)
    parsed=fetch_page(page)
    print("PAGE",page,"SIZE",len(parsed.comments),"IDS",parsed.comments[0]["id"] if parsed.comments else None,parsed.comments[-1]["id"] if parsed.comments else None,flush=True)
    for row in parsed.comments:
        records[row["id"]]=row
rows=[records[k] for k in sorted(records)]
print("LATEST_COMMENT",rows[-1]["id"], rows[-1].get("created_at"),flush=True)
print("ALL_PARSIFAL_RECENT",flush=True)
for r in rows:
    if r["author"]=="parsifal":
        print("PARSIFAL",r["id"],r.get("created_at"),repr(r.get("own_text",r["text"])[:1800]),flush=True)
print("RECENT_OFFICIAL",flush=True)
for r in rows:
    if r["author"]=="dustinc":
        t=r.get("own_text") or r["text"]
        cat,kw=classify_reply(t)
        print("DUSTINC",r["id"],r.get("created_at"),cat,repr(kw),repr(t[:850]),flush=True)
print("LATEST_22_REPLIES",flush=True)
for r in rows[-22:]:
    print("LATEST",r["id"],r["author"],r.get("created_at"),repr((r.get("own_text") or r["text"])[:220]),flush=True)
