#!/usr/bin/env python3
"""One-time enlarged inspection of public prize-entry photographs."""
import urllib.request,io,base64,sys,subprocess
try:
    from PIL import Image,ImageEnhance,ImageOps,ImageDraw,ImageFilter
except ImportError:
    subprocess.run([sys.executable,"-m","pip","install","--quiet","--target","/tmp/let_pil","Pillow"],check=True,timeout=65)
    sys.path.insert(0,"/tmp/let_pil")
    from PIL import Image,ImageEnhance,ImageOps,ImageDraw,ImageFilter
items=[
(4885613,"beiji","https://imgs.966001.xyz/file/KisYFWSY.webp",(0.09,0.20,0.92,0.85)),
(4885623,"a549250828","https://img.cdn1.vip/i/6acf0838386cd_1791952952.webp",(0.19,0.18,0.82,0.83)),
(4885628,"gooliver","https://d.uguu.se/WCKSZUpV.jpg",(0.10,0.25,0.96,0.78)),
(4885665,"parsifal","https://i.ibb.co/r2Hfn62J/image.jpg",(0.02,0.01,0.99,0.99)),
]
for ident,name,url,box in items:
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=15) as r:data=r.read(4500000)
    im=Image.open(io.BytesIO(data)).convert("RGB")
    w,h=im.size
    crop=im.crop((int(box[0]*w),int(box[1]*h),int(box[2]*w),int(box[3]*h)))
    if ident==4885613:crop=crop.rotate(90,expand=True)
    crop=ImageEnhance.Contrast(crop).enhance(1.5)
    crop=ImageEnhance.Sharpness(crop).enhance(1.5)
    crop.thumbnail((1450,1200))
    out=Image.new("RGB",(max(900,crop.width),crop.height+38),"white")
    ImageDraw.Draw(out).text((12,10),str(ident)+" @"+name,fill="black")
    out.paste(crop,((out.width-crop.width)//2,38))
    buf=io.BytesIO();out.save(buf,"JPEG",quality=74,optimize=True)
    print("PHOTO",ident,base64.b64encode(buf.getvalue()).decode("ascii"),flush=True)
print("DONE",flush=True)
