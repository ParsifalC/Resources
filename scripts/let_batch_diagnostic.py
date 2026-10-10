#!/usr/bin/env python3
"""One-shot public LET post timing diagnostic. No retry or credentials."""
import re
import time
import urllib.request
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lowendtalk_monitor import ThreadParser, THREAD_URL

class TimedParser(ThreadParser):
    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if self.comment is not None and tag.lower() == 'time':
            data = dict(attrs)
            if data.get('datetime'):
                self.comment['time'] = data['datetime']

def fetch(page):
    url = THREAD_URL if page == 1 else f'{THREAD_URL}/p{page}'
    req = urllib.request.Request(url, headers={
        "User-Agent": "ResourcesTimestampCheck/1.0 (+https://github.com/ParsifalC/Resources)",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read(2_000_000).decode('utf-8', 'replace')
    p = TimedParser()
    p.feed(data)
    p.close()
    return p.comments

records = {}
for page in range(11, 13):
    try:
        comments = fetch(page)
        print('PAGE', page, 'count', len(comments), 'first', comments[0] if comments else None, flush=True)
        for r in comments:
            records[r['id']] = r
    except Exception as exc:
        print('PAGE_ERROR', page, type(exc).__name__, str(exc), flush=True)
    if page != 12:
        time.sleep(3)
rows = [records[k] for k in sorted(records)]
print('ROWS',len(rows),'START',rows[0]['id'] if rows else None,'END',rows[-1]['id'] if rows else None)
for i,r in enumerate(rows):
    body = r.get('text','')
    if r['author']=='dustinc' and ('the next 10 comments' in body.lower() or 'racknerd & adminbolt giveaway' in body.lower()):
        print('BATCH',r['id'],r.get('time'),repr(body[:1800]),flush=True)
        keyword_match=re.search(r'KEYWORD\\s*[;:]\\s*(?:#\\s*)?([^\\n]+)',body, re.I)
        kw = keyword_match.group(1).strip().strip('#') if keyword_match else None
        print('KEYWORD',repr(kw))
        eligible=[]
        seen=set()
        for t in rows[i+1:]:
            txt=' '.join(t.get('text','').strip().split())
            normalized=txt.lstrip('#').strip()
            if kw and normalized.upper()==kw.upper().strip() and t['author'] not in seen:
                eligible.append(t);seen.add(t['author'])
            if len(eligible)>=10: break
        print('ELIGIBLE_COUNT',len(eligible))
        for j,t in enumerate(eligible,1):
            print('ELIGIBLE',j,t['id'],t['author'],t.get('time'),repr(t['text'][:120]))
        print('FOLLOWING_20')
        for t in rows[i+1:i+21]:
            print('NEXT',t['id'],t['author'],t.get('time'),repr(t['text'][:200]))
print('ALL_ANNOUNCEMENTS_OR_CLOSING')
for r in rows:
    if r['author']=='dustinc' and any(x in r.get('text','').lower() for x in ('giveaway!', 'went quick', 'winners have been dm', 'winners have been dm\'d', 'latest giveaway winners')):
        print('SIGNAL',r['id'],r.get('time'),repr(r.get('text','')[:180]))

print('ALL_DUSTINC_ON_PAGES_11_12')
for r in rows:
    if r['author']=='dustinc':
        print('DUSTINC',r['id'],r.get('time'),repr(r.get('text','')[:400]))
print('LAST_20_ROWS_PAGE_11_AND_START_PAGE_12')
for r in rows:
    if r.get('time','')>='2026-10-09T17:40' and r.get('time','')<'2026-10-09T18:25':
        print('NEAR',r['id'],r['author'],r.get('time'),repr(r.get('text','')[:250]))
