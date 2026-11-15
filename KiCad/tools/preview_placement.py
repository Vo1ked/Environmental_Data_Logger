"""Draw an un-routed placement overview from the saved PCB, without design checks."""
from PIL import Image, ImageDraw, ImageFont
import json
import sys
import pcbnew as p
from generate_board import ROOT, PROJECT

b=p.LoadBoard(str(ROOT/(PROJECT+'.kicad_pcb')))
revision=sys.argv[1] if len(sys.argv)>1 else 'A2'
layout=json.loads((ROOT/('placement_'+revision+'.json')).read_text(encoding='utf-8'))
outline=layout.get('outline',[(50,50),(150,50),(150,138),(50,138)])
xmin=min(v[0] for v in outline); xmax=max(v[0] for v in outline)
ymin=min(v[1] for v in outline); ymax=max(v[1] for v in outline)
im=Image.new('RGB',(1800,1160),'#f3f5f8')
d=ImageDraw.Draw(im)
font_path=r'C:\Windows\Fonts\segoeui.ttf'
fonts={s:ImageFont.truetype(font_path,s) for s in (13,15,18,22,28,34)}
d.text((50,22),'Компоновка '+revision+' — для обсуждения',font=fonts[34],fill='#172536')
d.text((50,70),f'Без трассировки. Габариты платы {xmax-xmin:g} × {ymax-ymin:g} мм. Контуры модулей приблизительные.',font=fonts[18],fill='#475569')
names={'M1':'ESP32-S3','M2':'Tiny RTC','M3':'OLED','M4':'BME280'}
colors={'M1':'#506d8c','M2':'#2189ab','M3':'#273447','M4':'#8365b4'}

for panel,bottom in enumerate((False,True)):
    xoff=60+panel*880
    scale=710/(xmax-xmin)
    def point(x,y):
        return (xoff+((xmax-x) if bottom else (x-xmin))*scale,150+(y-22)*scale)
    def box(x1,y1,x2,y2):
        a=point(x1,y1); c=point(x2,y2)
        return (min(a[0],c[0]),min(a[1],c[1]),max(a[0],c[0]),max(a[1],c[1]))
    def pcb_box(bb):
        return box(p.ToMM(bb.GetX()),p.ToMM(bb.GetY()),p.ToMM(bb.GetRight()),p.ToMM(bb.GetBottom()))
    def centered(x,y,s,font=18,color='#172536'):
        w=d.textbbox((0,0),s,font=fonts[font])[2]
        d.text((x-w/2,y),s,font=fonts[font],fill=color)
    centered(xoff+355,117,'Вид снизу' if bottom else 'Вид сверху',28)
    d.rounded_rectangle(box(xmin,ymin,xmax,ymax),radius=5,fill='#e2eee7',outline='#3f6555',width=3)
    keepout=layout.get('rf_keepout',[(50.5,50.5),(65,50.5),(65,58),(50.5,58)])
    d.polygon([point(*v) for v in keepout],fill='#f7e6b1',outline='#aa8724')
    if not bottom:
        for f in b.GetFootprints():
            ref=f.GetReference()
            if ref not in names:
                continue
            shapes=[g.GetBoundingBox() for g in f.GraphicalItems() if g.GetLayer()==p.F_Fab]
            x1=min(v.GetX() for v in shapes); y1=min(v.GetY() for v in shapes)
            x2=max(v.GetRight() for v in shapes); y2=max(v.GetBottom() for v in shapes)
            bounds=box(p.ToMM(x1),p.ToMM(y1),p.ToMM(x2),p.ToMM(y2))
            d.rounded_rectangle(bounds,radius=5,fill=colors[ref],outline='#172536',width=2)
            centered((bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2-13,names[ref],22 if ref!='M4' else 15,'white')
            if ref=='M1' and revision=='A3':
                d.text((bounds[2]-112,bounds[1]+25),'USB ESP →',font=fonts[15],fill='white')
    else:
        for f in b.GetFootprints():
            if f.GetLayer()!=p.B_Cu:
                continue
            bounds=pcb_box(f.GetBoundingBox(False,False))
            fill='#bac6d4' if f.GetReference()=='J1' else '#ced8e0'
            d.rectangle(bounds,fill=fill,outline='#64748b',width=1)
            centered((bounds[0]+bounds[2])/2,bounds[3]+2,f.GetReference(),13)
    for f in b.GetFootprints():
        for pad in f.Pads():
            if not pad.IsOnLayer(p.B_Cu if bottom else p.F_Cu):
                continue
            bounds=pcb_box(pad.GetBoundingBox())
            if pad.GetAttribute()==p.PAD_ATTRIB_NPTH:
                d.ellipse(bounds,fill='#f3f5f8',outline='#465c54',width=1)
            elif pad.GetDrillSize().x>0:
                if pad.GetNumber()=='1':
                    d.rectangle(bounds,fill='#d4b45d',outline='#665322')
                else:
                    d.ellipse(bounds,fill='#d4b45d',outline='#665322')
                px,py=point(p.ToMM(pad.GetPosition().x),p.ToMM(pad.GetPosition().y))
                r=p.ToMM(pad.GetDrillSize().x)*scale/2
                d.ellipse((px-r,py-r,px+r,py+r),fill='#f3f5f8')
            else:
                d.rectangle(bounds,fill='#d4b45d',outline='#75602d')
        if not bottom and f.GetReference() in names:
            first=next(pad for pad in f.Pads() if pad.GetNumber()=='1')
            px,py=point(p.ToMM(first.GetPosition().x),p.ToMM(first.GetPosition().y))
            d.text((px+8,py-18),'1',font=fonts[15],fill='#9b2825')
    # Position of the bottom-mounted USB is also indicated on the top overview.
    if not bottom:
        j=next(f for f in b.GetFootprints() if f.GetReference()=='J1')
        bounds=pcb_box(j.GetBoundingBox(False,False))
        d.rectangle(bounds,outline='#64748b',width=2)
        tx=bounds[0]-90 if revision=='A3' else bounds[2]+8
        d.text((tx,bounds[1]+4),'USB 5 В\nснизу',font=fonts[15],fill='#475569')
        if revision=='A3':
            dx=point(xmax,50)[0]+6
            for yy in range(int(point(xmax,24)[1]),int(point(xmax,70)[1]),12):
                d.line((dx,yy,dx,yy+6),fill='#9b2825',width=2)
    note_y=point(xmin,ymax)[1]+32
    centered(xoff+355,note_y,'Сигналы: планируется F.Cu' if not bottom else 'Питание + GND: планируется B.Cu',18)
footer=int(note_y+65)
d.text((50,footer),'3,3 В пока формируются на модуле ESP: его вход 5 В сохранён.',font=fonts[18],fill='#334155')
d.text((50,footer+30),'Снизу показан вид со стороны монтажа — относительно вида сверху он зеркальный.',font=fonts[18],fill='#475569')
if revision=='A3':
    d.text((50,footer+60),'USB выровнены по правому краю в виде сверху; высота разъёмов разная. Точная геометрия ESP ещё не измерена.',font=fonts[18],fill='#475569')
im=im.crop((0,0,1800,footer+100))
out=ROOT/'exports'/('placement_'+revision+'.png')
im.save(out)
print(out)
