#!/usr/bin/env python3
"""One-time read-only public handwriting entry photo comparison."""
import urllib.request,urllib.error,io,base64,sys,subprocess,time
try:
    from PIL import Image,ImageOps,ImageDraw
except ImportError:
    subprocess.run([sys.executable,"-m","pip","install","--quiet","--target","/tmp/let_pil","Pillow"],check=True,timeout=60)
    sys.path.insert(0,"/tmp/let_pil")
    from PIL import Image,ImageOps,ImageDraw
entries=[
(4885633,"cptech","https://img.cdn1.vip/i/6acf088154401_1791953025.webp"),
(4885636,"valerian","https://cdn.nodeimage.com/i/Qinb4MYG6kx7jjHzK8Ni7MN75DHYBdbB.webp"),
(4885638,"shinebay","https://static.flomoapp.com/file/2026-10-14/16911/1791953004502D0CBD4605B8EE04A.jpg?OSSAccessKeyId=LTAI5tAXfrgN5cBQ7Bym1EcM&Expires=1792212217&Signature=AgFw6qYb36LUdvJ%2FDGkhs2nNbEM%3D&id=59787720"),
(4885642,"zc741","https://cdn.nodeimage.com/i/zY7zS3noOTYRDbGiAWwcYNOixYVky8fj.webp"),
(4885644,"cyugpt666","https://i.ibb.co/VWwk9YSR/codex-clipboard-ca846914-f82b-4c43-aabf-243cf98f29bd.jpg"),
(4885646,"schrauger","https://i.ibb.co/rGHLJGfq/2026-10-1400-43-393425759214113506270.jpg"),
(4885649,"wkksk","https://iili.io/nXAjJyv.jpg"),
(4885653,"merry","https://i.postimg.cc/63Z5NSfG/5a3265b74e5e42b2ae3374f84028e1044c29abfd83de62179fc1845f8f15c937.jpg"),
(4885654,"lukepang","https://i.ibb.co/nNvysbK5/img.jpg"),
(4885655,"chrisrath","https://pub.mini-tools.uk/1-day/9839cc4a-4805-4daa-bc52-0ca768fdcd08.jpg"),
(4885658,"zc741-again","https://cdn.nodeimage.com/i/zY7zS3noOTYRDbGiAWwcYNOixYVky8fj.webp"),
(4885662,"decoder","https://i.ibb.co/Swj2h0xR/IMG-7742.jpg"),
(4885663,"yhzaat","https://i.ibb.co/fVNkpCR4/6-D6-A632056-BF3-A17748-B6176-F93-C6065.jpg"),
(4885665,"parsifal","https://i.ibb.co/r2Hfn62J/image.jpg")
]
cards=[]
for idx,(ident,name,url) in enumerate(entries):
    card=Image.new("RGB",(640,525),"white")
    d=ImageDraw.Draw(card);d.text((10,11),str(ident)+" @"+name,fill="black")
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=12) as resp:raw=resp.read(4200001)
        if len(raw)>4200000:raise ValueError("oversize")
        im=Image.open(io.BytesIO(raw)).convert("RGB")
        print("FETCHED",ident,im.size,flush=True)
        im=ImageOps.contain(im,(625,480))
        card.paste(im,((640-im.width)//2,35+(480-im.height)//2))
    except Exception as exc:
        print("FAILED",ident,type(exc).__name__,str(exc)[:120],flush=True)
        d.text((20,140),"UNAVAILABLE",fill="red")
    cards.append(card)
    time.sleep(.15)
for start in range(0,len(cards),7):
    group=cards[start:start+7]
    sheet=Image.new("RGB",(1280,2100),"#eee")
    for idx,card in enumerate(group):sheet.paste(card,((idx%2)*640,(idx//2)*525))
    buf=io.BytesIO();sheet.save(buf,"JPEG",quality=62,optimize=True)
    print("SHEET",start//7+1,base64.b64encode(buf.getvalue()).decode("ascii"),flush=True)
print("DONE",flush=True)
