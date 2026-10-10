#!/usr/bin/env python3
"""One-shot anonymous check of RackNerd giveaway announcement times, no retries."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lowendtalk_monitor import THREAD_URL, ThreadParser, classify_reply, fetch_page

records = {}
def get(page):
    result=fetch_page(page)
    print("PAGE", page, "COUNT", len(result.comments), "AVAILABLE", sorted(result.pages),flush=True)
    for row in result.comments:
        records[row["id"]]=row
    return result

# Check the latest page first, and scan any newly created pages.
last=get(16)
latest=max(last.pages)
if latest > 20:
    print("TOO_MANY_PAGES",latest, "stopping, to avoid excessive requests")
    sys.exit(1)
for page in range(17, latest+1):
    time.sleep(2)
    get(page)

# Earlier pages needed to identify and time the most recent completed batches.
for page in [11,12,13,14]:
    time.sleep(2)
    get(page)

rows=sorted(records.values(), key=lambda r:r["id"])
print("LAST_COMMENT",rows[-1]["id"],rows[-1].get("created_at"))
print("LATEST_12")
for r in rows[-12:]:
    print("LATEST",r["id"],r["author"],r.get("created_at"),repr(r.get("own_text",r["text"])[:450]))
print("ANNOUNCEMENTS")
for r in rows:
    if r["author"] != "dustinc": continue
    t=r.get("own_text",r["text"])
    category,keyword=classify_reply(t)
    if category=="giveaway":
        print("GIVEAWAY",r["id"],r.get("created_at"),"KEYWORD",repr(keyword),"TEXT",repr(t[:1250]))
    elif r["id"]>=4879814 and category in ("warmup","winners"):
        print("SIGNAL",r["id"],r.get("created_at"),category,repr(t[:500]))
print("NEW_DUSTINC")
for r in rows:
    if r["author"]=="dustinc" and r["id"]>4879814:
        print("DUSTINC",r["id"],r.get("created_at"),repr(r.get("own_text",r["text"])[:800]))
