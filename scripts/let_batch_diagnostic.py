#!/usr/bin/env python3
"""One-time anonymous public audit of latest RackNerd Giveaway responses."""
import re, time, html
import urllib.request
from lowendtalk_monitor import THREAD_URL, parse_thread

BATCH_ID=4882286
def load(p):
    u=THREAD_URL + ("/p"+str(p) if p>1 else "")
    req=urllib.request.Request(u, headers={"User-Agent":"ResourcesGiveawayMonitor/1.0 (+https://github.com/ParsifalC/Resources)", "Accept":"text/html"})
    with urllib.request.urlopen(req,timeout=20) as r:
        d=r.read(2_000_001)
        if len(d)>2_000_000: raise ValueError("page too big")
        page=d.decode(r.headers.get_content_charset() or "utf-8","replace")
    parser=parse_thread(page,page=p)
    return page,parser

raw,parsed=load(37)
last=max(parsed.pages)
print("LATEST_PAGE",last,flush=True)
if last>45: raise SystemExit("Page guard triggered; manual check needed")
pages={37:(raw,parsed)}
for p in range(38,last+1):
    time.sleep(1.5)
    pages[p]=load(p)
    print("PAGE",p,"ROWS",len(pages[p][1].comments),flush=True)

ann=next(x for x in parsed.comments if x['id']==BATCH_ID)
print("OFFICIAL",ann,flush=True)

# Extract original HTML for announcement; HTML order: li id=Comment_... followed by next li.
pos=raw.find('id="Comment_'+str(BATCH_ID)+'"')
if pos<0: raise RuntimeError("announcement raw HTML not found")
nxt=re.search(r'<li\\b[^>]*id="Comment_\\d+"',raw[pos+3:],re.I)
end=pos+3+nxt.start() if nxt else pos+12000
fragment=raw[pos:end]
marker='Count the number of dots below correctly:'
at=fragment.find(marker)
print("OFFICIAL_DOTS_AROUND",repr(fragment[at-400:at+5000] if at>=0 else fragment[:7000]),flush=True)

for p,(htmlsrc,parsed) in pages.items():
    rows=[r for r in parsed.comments if r["id"]>BATCH_ID]
    print("PAGE_AUDIT",p,len(rows),flush=True)
    for r in rows:
        t=r.get('own_text') or r['text']
        text=repr(t[:320])
        print("ENTRY",r["id"],r["author"],r.get("created_at"),text,flush=True)
print("AUDIT_DONE",flush=True)
