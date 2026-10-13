#!/usr/bin/env python3
"""One-time anonymous verification of three latest announced giveaways."""
import time,re
from html.parser import HTMLParser
from lowendtalk_monitor import fetch_page,THREAD_URL
import urllib.request

class Images(HTMLParser):
    def __init__(self):super().__init__();self.paths=[]
    def handle_starttag(self,tag,attrs):
        if tag=='img':
            a=dict(attrs)
            src=a.get('src','')
            if 'racknerd.com' in src or 'adminbolt' in src.lower():self.paths.append(src)
for pg,id in [(54,4883232),(65,4883902),(69,4884068)]:
    if pg!=54:time.sleep(2)
    r=fetch_page(pg)
    item=next(x for x in r.comments if x["id"]==id)
    print("ROUND",id,"PAGE",pg,"DATE",item.get('created_at'),"TEXT",repr(item.get("own_text") or item["text"]),flush=True)
    req=urllib.request.Request(THREAD_URL+'/p'+str(pg),headers={'User-Agent':'ResourcesGiveawayMonitor/1.0'})
    with urllib.request.urlopen(req,timeout=20) as response:raw=response.read(2_000_000).decode('utf-8','replace')
    start=raw.find('id="Comment_'+str(id)+'"')
    next_=raw.find('id="Comment_',start+15)
    segment=raw[start:next_ if next_!=-1 else start+12000]
    imgs=Images();imgs.feed(segment)
    print("ROUND_IMAGES",id,imgs.paths,flush=True)
print("DONE",flush=True)
