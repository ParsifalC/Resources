#!/usr/bin/env python3
"""One-time anonymous read of latest replies, no credentials or retries."""
import sys
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lowendtalk_monitor import THREAD_URL, ThreadParser

class TimedParser(ThreadParser):
    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if self.comment is not None and tag.lower() == 'time':
            dt = dict(attrs).get('datetime')
            if dt:
                self.comment['created_at'] = dt

def fetch(page):
    request = urllib.request.Request(f'{THREAD_URL}/p{page}', headers={
        'User-Agent': 'ResourcesTimestampCheck/1.0 (+https://github.com/ParsifalC/Resources)',
        'Accept': 'text/html',
        'Accept-Language': 'en-US,en;q=0.9'
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(2_000_000).decode('utf-8','replace')
    parser = TimedParser()
    parser.feed(raw)
    parser.close()
    return parser

data = {}
try:
    start = fetch(15)
    print('PAGE',15,'pages',sorted(start.pages),'count',len(start.comments),flush=True)
    for row in start.comments:
        data[row['id']] = row
    latest = max(start.pages)
    if latest>15:
        if latest>18:
            print('TOO_MANY_NEW_PAGES',latest,'stopping',flush=True)
        else:
            for number in range(16,latest+1):
                p=fetch(number)
                print('PAGE',number,'count',len(p.comments),'pages',sorted(p.pages),flush=True)
                for row in p.comments:
                    data[row['id']]=row
    rows=sorted(data.values(),key=lambda x:x['id'])
    print('LATEST_COMMENT_ID', rows[-1]['id'] if rows else None,flush=True)
    print('LATEST_FIVE_ALL_REPLIES',flush=True)
    for item in rows[-5:]:
        print('COMMENT',item['id'],item['author'],item.get('created_at'),repr(item['text'][:2500]),flush=True)
except Exception as exc:
    print('FETCH_ERROR',type(exc).__name__,str(exc),flush=True)
    raise
