#!/usr/bin/env python3
"""One-shot read-only enlargement of two ambiguous public giveaway entry photos."""
import urllib.request,io,base64,sys,subprocess
try:
    from PIL import Image,ImageOps,ImageDraw,ImageEnhance
except ImportError:
    subprocess.run([sys.executable,"-m","pip","install","--quiet","--target","/tmp/let_pil","Pillow"],check=True,timeout=60)
    sys.path.insert(0,"/tmp/let_pil")
    from PIL import Image,ImageOps,ImageDraw,ImageEnhance
entries=[
(4885628,"gooliver","https://d.uguu.se/WCKSZUpV.jpg"),
(4885654,"lukepang","https://i.ibb.co/nNvysbK5/img.jpg"),
(4885638,"shinebay","https://static.flomoapp.com/file/2026-10-14/16911/1791953004502D0CBD4605B8EE04A.jpg?OSSAccessKeyId=LTAI5tAXfrgN5cBQ7Bym1EcM&Expires=1792212217&Signature=AgFw6qYb36LUdvJ%2FDGkhs2nNbEM%3D&id=59787720")
]
for ident,name,url in entries:
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=15) as resp:raw=resp.read(16000001)
        if len(raw)>16000000:raise ValueError("oversize")
        im=Image.open(io.BytesIO(raw)).convert("RGB")
        print("FETCHED",ident,"ORIGINAL",im.size,flush=True)
        if ident==4885628:
            im=im.crop((30,250,850,1160))
            im=ImageEnhance.Contrast(im).enhance(1.65)
            im=ImageEnhance.Sharpness(im).enhance(2)
        im=ImageOps.contain(im,(1150,1450))
        buf=io.BytesIO();im.save(buf,"JPEG",quality=69,optimize=True)
        print("PHOTO",ident,base64.b64encode(buf.getvalue()).decode("ascii"),flush=True)
    except Exception as e:print("FAILED",ident,type(e).__name__,str(e)[:150],flush=True)
print("DONE",flush=True)
