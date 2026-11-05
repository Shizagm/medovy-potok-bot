"""Small dependency-free PNG renderer. Cell labels are Latin A-Z / numbers."""
import struct,zlib
from collections import defaultdict

FONT={
'A':['01110','10001','10001','11111','10001','10001','10001'],
'B':['11110','10001','10001','11110','10001','10001','11110'],
'C':['01111','10000','10000','10000','10000','10000','01111'],
'D':['11110','10001','10001','10001','10001','10001','11110'],
'E':['11111','10000','10000','11110','10000','10000','11111'],
'F':['11111','10000','10000','11110','10000','10000','10000'],
'G':['01111','10000','10000','10111','10001','10001','01110'],
'H':['10001','10001','10001','11111','10001','10001','10001'],
'I':['11111','00100','00100','00100','00100','00100','11111'],
'J':['00111','00010','00010','00010','10010','10010','01100'],
'K':['10001','10010','10100','11000','10100','10010','10001'],
'L':['10000','10000','10000','10000','10000','10000','11111'],
'M':['10001','11011','10101','10101','10001','10001','10001'],
'N':['10001','11001','10101','10011','10001','10001','10001'],
'O':['01110','10001','10001','10001','10001','10001','01110'],
'P':['11110','10001','10001','11110','10000','10000','10000'],
'Q':['01110','10001','10001','10001','10101','10010','01101'],
'R':['11110','10001','10001','11110','10100','10010','10001'],
'S':['01111','10000','10000','01110','00001','00001','11110'],
'T':['11111','00100','00100','00100','00100','00100','00100'],
'U':['10001','10001','10001','10001','10001','10001','01110'],
'V':['10001','10001','10001','10001','10001','01010','00100'],
'W':['10001','10001','10001','10101','10101','10101','01010'],
'X':['10001','10001','01010','00100','01010','10001','10001'],
'Y':['10001','10001','01010','00100','00100','00100','00100'],
'Z':['11111','00001','00010','00100','01000','10000','11111'],
'0':['01110','10001','10011','10101','11001','10001','01110'],
'1':['00100','01100','00100','00100','00100','00100','01110'],
'2':['01110','10001','00001','00010','00100','01000','11111'],
'3':['11110','00001','00001','01110','00001','00001','11110'],
'4':['00010','00110','01010','10010','11111','00010','00010'],
'5':['11111','10000','10000','11110','00001','00001','11110'],
'6':['01110','10000','10000','11110','10001','10001','01110'],
'7':['11111','00001','00010','00100','01000','01000','01000'],
'8':['01110','10001','10001','01110','10001','10001','01110'],
'9':['01110','10001','10001','01111','00001','00001','01110'],
'+':['00000','00100','00100','11111','00100','00100','00000'],
' ':['00000']*7,'-':['00000','00000','00000','11111','00000','00000','00000']}

def render_map(snap):
    import io
    from PIL import Image,ImageDraw,ImageOps
    step=48;left=48;top=48;rows=snap['tiles'];w=left+len(rows[0])*step+16;h=top+len(rows)*step+24
    canvas=Image.new('RGB',(w,h),(25,33,40));draw=ImageDraw.Draw(canvas)
    def text(x,y,value,color=(245,239,219),scale=2):
        for i,c in enumerate(str(value).upper()):
            for yy,row in enumerate(FONT.get(c,FONT[' '])):
                for xx,v in enumerate(row):
                    if v=='1':draw.rectangle((x+i*6*scale+xx*scale,y+yy*scale,x+i*6*scale+(xx+1)*scale-1,y+(yy+1)*scale-1),fill=color)
    text(left,8,('DRAFT - ' if snap.get('draft') else '')+'MEDOVY POTOK - '+snap['area'])
    for x in range(len(rows[0])):text(left+x*step+19,top-20,chr(65+x))
    for y,row in enumerate(rows):
        text(8,top+y*step+17,str(y+1))
        for x,v in enumerate(row):
            color={'#':(69,65,59),'.':(203,177,128),'?':(31,39,47)}[v]
            draw.rectangle((left+x*step,top+y*step,left+(x+1)*step-2,top+(y+1)*step-2),fill=color)
    for d in snap['doors']:
        x=left+d['x']*step;y=top+d['y']*step
        draw.rectangle((x+4,y+4,x+step-6,y+step-6),fill=(70,142,104) if d['open'] else (164,73,53))
        text(x+19,y+17,'O' if d['open'] else 'X')
    for i,lm in enumerate(snap['landmarks'],1):
        x=left+lm['x']*step;y=top+lm['y']*step
        draw.rectangle((x+10,y+10,x+36,y+36),fill=(47,88,111));text(x+19,y+17,i)
    def token(x,y,size,png,border,ghost=False):
        d=size*step-6;px=left+x*step+2;py=top+y*step+2
        draw.ellipse((px,py,px+d,py+d),fill=(178,104,223) if border==(72,234,159) else border)
        if border==(72,234,159):draw.ellipse((px,py,px+d,py+d),outline=border,width=2)
        inset=4;inner=d-2*inset
        if png:
            with Image.open(io.BytesIO(png)) as original:
                portrait=ImageOps.fit(original.convert('RGB'),(inner,inner),method=Image.Resampling.LANCZOS)
            if ghost:portrait=ImageOps.colorize(ImageOps.grayscale(portrait),'#516978','#dce9ee')
        else:
            portrait=Image.new('RGB',(inner,inner),(106,77,135) if not ghost else (110,141,158));pd=ImageDraw.Draw(portrait)
            cx=inner//2;pd.ellipse((cx-inner//7,inner//6,cx+inner//7,inner//6+inner//3),fill=(230,219,237))
            pd.ellipse((inner//5,inner//2,inner*4//5,inner*6//5),fill=(230,219,237))
        mask=Image.new('L',(inner,inner));ImageDraw.Draw(mask).ellipse((0,0,inner-1,inner-1),fill=255)
        canvas.paste(portrait,(px+inset,py+inset),mask)
        if ghost:
            radius=max(3,d//9);draw.ellipse((px+d-radius*2,py+d-radius*2,px+d,py+d),fill=(225,244,255),outline=(61,100,128),width=2)
    for npc in snap.get('npcs',[]):
        token(npc['x'],npc['y'],npc['size'],npc.get('png'),(201,66,51) if npc['kind']=='monster' else (222,165,52))
    for p in snap['people']:
        token(p['x'],p['y'],1,p.get('portrait'),(72,234,159) if p['uid']==snap['uid'] else (178,104,223),p['dead'])
    out=io.BytesIO();canvas.save(out,format='PNG');return out.getvalue()
