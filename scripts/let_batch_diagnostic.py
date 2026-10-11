#!/usr/bin/env python3
"""One-off check of embedded image presence in public LET replies."""
import urllib.request
from lowendtalk_monitor import THREAD_URL, ThreadParser

class ImageParser(ThreadParser):
    def __init__(self):
        super().__init__()
        self.pictures={}
    def handle_starttag(self,tag,attrs):
        super().handle_starttag(tag,attrs)
        if tag=='img' and self.comment is not None:
            a=dict(attrs)
            self.pictures.setdefault(self.comment['id'],[]).append(
                {'src':a.get('src'),'alt':a.get('alt'),'inside_quote':self._in_quote()})
req=urllib.request.Request(THREAD_URL+'/p24',headers={'User-Agent':'ResourcesGiveawayMonitor/1.0'})
with urllib.request.urlopen(req,timeout=20) as r:
    document=r.read(2_000_000).decode('utf8','replace')
p=ImageParser()
p.feed(document)
p.close()
for row in p.comments:
    if row['id'] in (4880882,4880883,4880884,4880885):
        print('COMMENT',row['id'],'AUTHOR',row['author'],'TEXT',repr(row['own_text']),
              'IMAGES',repr(p.pictures.get(row['id'],[])))
