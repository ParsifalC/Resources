#!/usr/bin/env python3
"""One-shot anonymous validation of round six's pagination index."""
from lowendtalk_monitor import fetch_page
page=18
r=fetch_page(page)
print("PAGE",page,"SIZE",len(r.comments),"RANGE",
      (r.comments[0]["id"],r.comments[-1]["id"]) if r.comments else None)
for index,item in enumerate(r.comments):
    if item["id"] == 4880439:
        print("BATCH6",item["id"],"PAGE",page,"INDEX_0",index,
              "UTC",item.get("created_at"),"AUTHOR",item["author"],
              "TEXT",repr((item.get("own_text") or item["text"])[:1500]))
print("DONE")
