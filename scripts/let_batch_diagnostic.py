#!/usr/bin/env python3
"""Single anonymous check of giveaway post eligibility."""
import time
from lowendtalk_monitor import fetch_page, ThreadParser, THREAD_URL
import urllib.request

BASE="RACKNERD CTRL + ADMINBOLT - ONE CLICK TO GET THE PARTY STARTED!"
class E(ThreadParser):
    def handle_starttag(self,tag,attrs):
        super().handle_starttag(tag,attrs)
        if self.comment is not None and 'DateUpdated' in dict(attrs).get('class',''):
            self.comment['edited']=True

def load(n):
    req=urllib.request.Request(THREAD_URL+"/p"+str(n),headers={'User-Agent':'ResourcesGiveawayMonitor/1.0'})
    with urllib.request.urlopen(req,timeout=20) as f:
        h=f.read(2_000_000).decode('utf8','replace')
    p=E();p.pages.add(n);p.feed(h);p.close()
    return p
first=load(37)
last=max(first.pages)
if last>45:raise ValueError('page bound')
rows=list(first.comments)
for pg in range(38,last+1):
    time.sleep(1.5)
    rows.extend(load(pg).comments)
seen=set();valid=[]
print("AUDIT_PAGE",last,flush=True)
for r in sorted(rows,key=lambda x:x['id']):
    if r['id']<=4882286:continue
    t=r.get('own_text') or r['text']
    exact=t in (BASE+'seven','#'+BASE+'seven')
    edited=r.get('edited',False)
    status='bad_format' if not exact else 'edited' if edited else 'duplicate' if r['author'] in seen else 'candidate'
    if status=='candidate':
        seen.add(r['author']);valid.append(r)
    print('CHECK',r['id'],r['author'],status,'edit',edited,repr(t[:125]),flush=True)
print('FIRST10',[(x['id'],x['author']) for x in valid[:10]],flush=True)
print('UNIQUE_CANDIDATES',len(valid),flush=True)
