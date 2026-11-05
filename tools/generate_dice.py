"""Build exact-number d20 GIFs. Developer tool; Pillow not needed by the bot."""
from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
import math,itertools,io
ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'assets'; OUT.mkdir(exist_ok=True)
phi=(1+5**.5)/2
vertices=[]
for a in (-1,1):
    for b in (-phi,phi): vertices.extend([(0,a,b),(a,b,0),(b,0,a)])
edge=min(sum((a[i]-b[i])**2 for i in range(3)) for a,b in itertools.combinations(vertices,2))
faces=[t for t in itertools.combinations(range(12),3) if all(abs(sum((vertices[a][i]-vertices[b][i])**2 for i in range(3))-edge)<.001 for a,b in itertools.combinations(t,2))]
fontpath='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
small=ImageFont.truetype(fontpath,14); big=ImageFont.truetype(fontpath,38)

def frame(angle,result=None):
    im=Image.new('RGB',(320,320),(22,27,28));d=ImageDraw.Draw(im)
    d.rounded_rectangle((8,8,312,312),radius=24,outline=(123,99,58),width=2)
    d.text((160,33),'МЕДОВЫЙ ПОТОК',font=small,anchor='mm',fill=(231,206,156))
    d.ellipse((73,249,247,269),fill=(12,16,17))
    points=[]
    for x,y,z in vertices:
        x,z=x*math.cos(angle)+z*math.sin(angle),-x*math.sin(angle)+z*math.cos(angle)
        tilt=.36
        y,z=y*math.cos(tilt)-z*math.sin(tilt),y*math.sin(tilt)+z*math.cos(tilt)
        points.append((x,y,z))
    front=max(faces,key=lambda f:sum(points[j][2] for j in f))
    for f in sorted(faces,key=lambda f:sum(points[j][2] for j in f)):
        pts=[]
        z=sum(points[j][2] for j in f)/3
        for j in f:
            x,y,zz=points[j];scale=58/(1-zz*.09);pts.append((160+x*scale,159+y*scale))
        shade=int(104+z*32)
        d.polygon(pts,fill=(max(25,shade-44),max(43,shade-3),max(47,shade)),outline=(210,174,103),width=2)
        if f==front and result is not None:
            cx=sum(x for x,y in pts)/3;cy=sum(y for x,y in pts)/3
            d.text((cx,cy),str(result),font=big,anchor='mm',fill=(255,239,194),stroke_width=1,stroke_fill=(15,25,26))
    d.text((160,288),'D20 · БРОСОК РОЯ',font=small,anchor='mm',fill=(231,206,156))
    return im

spin=[frame(2*math.pi*(i/20)) for i in range(20)]
for value in range(1,21):
    frames=[f.copy() for f in spin]+[frame(0,value)]
    # Long final frame keeps the authoritative result visible between loops.
    buffer=io.BytesIO()
    frames[0].save(buffer,format='GIF',save_all=True,append_images=frames[1:],duration=[70]*20+[5000],loop=0,optimize=True)
    (OUT/f'd20-{value:02}.gif').write_bytes(buffer.getvalue())
frame(0,20).save(ROOT.parent/'dice-preview.png')
print('Built 20 animated dice.')
