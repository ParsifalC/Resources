#!/usr/bin/env python3
"""One-shot public candidate photo thumbnail contact sheets for manual review."""
import urllib.request,io,base64,subprocess,sys,time
try:
    from PIL import Image,ImageOps,ImageDraw
except ImportError:
    subprocess.run([sys.executable,"-m","pip","install","--quiet","Pillow"],check=True,timeout=65)
    from PIL import Image,ImageOps,ImageDraw
entries=[
(4885610,"weishiair","https://img.cdn1.vip/i/6acf07c903770_1791952841.webp"),
(4885612,"vgl","https://cdn-fusion.imgcdn.store/i/2026/5f4a1e62c41f5c6b.jpg"),
(4885613,"beiji","https://imgs.966001.xyz/file/KisYFWSY.webp"),
(4885614,"schrauger","https://i.ibb.co/k2sHnc9S/2026-10-1400-39-202368175048570551078.jpg"),
(4885615,"parsifal","https://i.ibb.co/RGJG7ZJy/image.jpg"),
(4885616,"dale0990","https://i.ibb.co/k2Q9Nj4m/20261014124105.jpg"),
(4885618,"hunkx","https://d.uguu.se/ziblgzzs.jpg"),
(4885623,"a549250828","https://img.cdn1.vip/i/6acf0838386cd_1791952952.webp"),
(4885625,"dallwwej203","https://i.ibb.co/hxGhDb2n/2026-10-14-12-41-42.png"),
(4885626,"weishiair","https://img.cdn1.vip/i/6acf083e69784_1791952958.webp"),
(4885628,"gooliver","https://d.uguu.se/WCKSZUpV.jpg"),
(4885629,"warlocklin","https://i.ibb.co/HLn41BGV/20261013214146-70-22.jpg"),
(4885630,"winlend","https://i.ibb.co/6cpBr0MH/IMG-20261014-124129.jpg"),
(4885665,"parsifal","https://i.ibb.co/r2Hfn62J/image.jpg")
]
panels=[]
for ident,name,url in entries:
    panel=Image.new("RGB",(680,535),"white")
    draw=ImageDraw.Draw(panel)
    draw.text((10,10),str(ident)+" @"+name,fill="black")
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; public giveaway audit)"})
        with urllib.request.urlopen(req,timeout=12) as r:
            raw=r.read(5000001)
        if len(raw)>5000000:raise ValueError("image too large")
        im=Image.open(io.BytesIO(raw)).convert("RGB")
        print("FETCHED",ident,"SIZE",im.size,flush=True)
        im=ImageOps.contain(im,(660,490))
        panel.paste(im,((680-im.width)//2,40+(490-im.height)//2))
    except Exception as e:
        print("FETCH_FAILED",ident,type(e).__name__,str(e)[:120],flush=True)
        draw.text((10,160),"IMAGE UNAVAILABLE",fill="red")
    panels.append(panel)
    time.sleep(.3)
for idx in range(0,len(panels),8):
    group=panels[idx:idx+8]
    sheet=Image.new("RGB",(1360,535*4),"#eeeeee")
    for i,im in enumerate(group):sheet.paste(im,((i%2)*680,(i//2)*535))
    buf=io.BytesIO();sheet.save(buf,"JPEG",quality=63,optimize=True)
    print("SHEET",idx//8+1,base64.b64encode(buf.getvalue()).decode("ascii"),flush=True)
print("DONE",flush=True)
