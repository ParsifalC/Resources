#!/usr/bin/env python3
"""One-time audit of the handwritten-papers giveaway, anonymous HTML only."""
import time
from lowendtalk_monitor import fetch_page, ThreadParser, THREAD_URL
import urllib.request
class P(ThreadParser):
    def handle_starttag(self,tag,attrs):
        super().handle_starttag(tag,attrs)
        if self.comment is None:return
        a=dict(attrs)
        cls=set(a.get("class","").split())
        if "DateUpdated" in cls or "edited" in cls:self.comment["edited"]=True
        if tag.lower()=="img" and self._in_message() and not self._in_quote():
            self.comment.setdefault("images",[]).append((a.get("src") or a.get("data-src") or "",a.get("alt") or "",a.get("class") or ""))
def read(page):
    url=THREAD_URL if page==1 else THREAD_URL+"/p"+str(page)
    req=urllib.request.Request(url,headers={"User-Agent":"ResourcesGiveawayMonitor/1.0 (+https://github.com/ParsifalC/Resources)","Accept":"text/html"})
    with urllib.request.urlopen(req,timeout=20) as response:html=response.read(2000000).decode("utf-8","replace")
    p=P();p.feed(html);p.close()
    return p
p=read(96)
last=max(p.pages)
print("PAGES",last,flush=True)
if last>110:raise ValueError("Page bound exceeded")
items={}
for n in range(95,last+1):
    x=p if n==96 else read(n)
    print("PAGE",n,"COUNT",len(x.comments),flush=True)
    for r in x.comments:items[r["id"]]=r
    if n<last:time.sleep(.85)
for r in sorted(items.values(),key=lambda v:v["id"]):
    if r["id"]<4885609:continue
    print("POST",r["id"],r.get("created_at"),"USER",r["author"],"EDIT",r.get("edited",False),"TEXT",repr((r.get("own_text") or "")[:180]),"IMAGES",repr(r.get("images",[]))[:1100],flush=True)
print("LATEST",max(items),flush=True)
