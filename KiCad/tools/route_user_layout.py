"""Route the saved user placement without invoking KiCad ERC/DRC.

Works on a revision copy; the original PCB is published only after every
requested connection has been routed. Requires numpy and Pillow, not pcbnew.
"""
import sys
sys.dont_write_bytecode = True
import math, json, time, zipfile, copy, subprocess, base64
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from generate_design import ROOT, PROJECT, Q, parse, dump, child, children, uid

SOURCE = ROOT / (PROJECT + '.kicad_pcb')
BACKUP = ROOT / 'revisions' / 'user_placement_before_routing.zip'
OUT = ROOT / 'revisions' / 'user_layout_routed.kicad_pcb'
STEP = .05
X0,Y0,X1,Y1 = 58.5,50,160,108
W,H = round((X1-X0)/STEP)+1,round((Y1-Y0)/STEP)+1
POWER = {'GND','+3V3_ESP','+5V_USB','+5V_FUSED','+5V_SYS','CC1','CC2','POWER_ST'}

def pt(x,y): return ((x-X0)/STEP,(y-Y0)/STEP)
def cell(p): return (round((p[0]-X0)/STEP),round((p[1]-Y0)/STEP))
def mm(c): return (round(c[0]*STEP+X0,5),round(c[1]*STEP+Y0,5))
def transform(p,a):
    x,y=map(float,p[:2]); ang=math.radians(float(a[3]) if len(a)>3 else 0)
    return (float(a[1])+x*math.cos(ang)+y*math.sin(ang),float(a[2])-x*math.sin(ang)+y*math.cos(ang))
def ref(f): return next(str(v[2]) for v in children(f,'property') if v[1]=='Reference')
def fmt(v): return round(float(v),5)

def load():
    if not BACKUP.exists():
        with zipfile.ZipFile(BACKUP,'w',zipfile.ZIP_DEFLATED) as z:
            for p in (SOURCE,ROOT/(PROJECT+'.kicad_sch'),ROOT/'modules.kicad_sch',ROOT/(PROJECT+'.kicad_pro')):
                z.write(p,p.name)
    with zipfile.ZipFile(BACKUP) as z: board=parse(z.read(SOURCE.name).decode('utf-8'))
    # A copied, unconnected TP4 records the user's new location. Move the
    # schematic-linked TP4 there and remove the accidental duplicate.
    tps=[f for f in children(board,'footprint') if ref(f)=='TP4']
    if len(tps)==2:
        original=next(f for f in tps if child(f,'path'))
        duplicate=next(f for f in tps if not child(f,'path'))
        original[original.index(child(original,'at'))]=copy.deepcopy(child(duplicate,'at'))
        board.remove(duplicate)
    # RTC bypass capacitor follows its load; this also opens the OLED supply
    # corridor. Only this small SMD part moves, not the RTC module.
    for f in children(board,'footprint'):
        if ref(f)=='C10': child(f,'at')[1:3]=[148,98.5]
        elif ref(f)=='U3': child(f,'at')[1:3]=[116,64.5]
        elif ref(f)=='R3': child(f,'at')[1:3]=[110,63.5]
        elif ref(f)=='TP5': child(f,'at')[1:3]=[116,58]
        elif ref(f)=='C7': child(f,'at')[1:3]=[112.5,66.5]
    labels={'USB 5V IN':(155,92),'BME280 / SPI':(109,102.5),
            'SDA5':(146,89.5),'SCL5':(143.5,93.5),'3V3':(108.5,67.2),
            'VIN ADC':(116,56),'GND':(113.5,83.3)}
    for text in list(children(board,'gr_text')):
        if str(text[1]) in ('5V','VBUS'): board.remove(text)
        elif str(text[1]).startswith('A3 /'): text[1]=Q('A4 / 101.5 x 58 mm')
        elif str(text[1]) in labels: child(text,'at')[1:3]=list(labels[str(text[1])])
    for n in list(board):
        if isinstance(n,list) and n[0] in ('segment','via'): board.remove(n)
        elif isinstance(n,list) and n[0]=='zone' and not child(n,'keepout'):
            # Leave one lower GND pour, with no stale fill or upper-layer pour.
            if child(n,'layer')[1]=='F.Cu': board.remove(n)
            else:
                for v in list(n):
                    if isinstance(v,list) and v[0] in ('filled_polygon','fill_segments'): n.remove(v)
                child(child(n,'polygon'),'pts')[1:]=[['xy',59,50.5],['xy',159.5,50.5],['xy',159.5,107.5],['xy',59,107.5]]
    # Keep all four existing chassis holes: they clear the module outlines.
    return board

class Router:
    def __init__(self,b):
        self.b=b; self.pads=[]; self.routes=[]; self.vias=[]; self.counter=0
        self.server=subprocess.Popen(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools'/'grid_router_server.ps1')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        response=self.server.stdout.readline().strip()
        if response!='READY': raise RuntimeError('Router server: '+response)
        self.font=ImageFont.truetype(r'C:\Windows\Fonts\segoeui.ttf',15)
        for f in children(b,'footprint'):
            for p in children(f,'pad'):
                at=child(p,'at'); size=child(p,'size'); layers=child(p,'layers')[1:]
                ls=[0,1] if '*.Cu' in layers else ([0] if 'F.Cu' in layers else [1])
                net=child(p,'net'); drill=child(p,'drill')
                self.pads.append(dict(ref=ref(f),num=str(p[1]),pos=transform(at[1:3],child(f,'at')),
                    size=tuple(map(float,size[1:3])),angle=float(at[3]) if len(at)>3 else 0,
                    shape=str(p[3]),layers=ls,net=str(net[-1]) if net else '',
                    drill=float(drill[1]) if drill and drill[1]!='oval' else 0,node=p,
                    hole=p[2]=='np_thru_hole'))
        self.nets=sorted({p['net'] for p in self.pads if p['net']})
        self.keepouts=[]
        for z in children(b,'zone'):
            if child(z,'keepout'):
                self.keepouts.append((0 if child(z,'layer')[1]=='F.Cu' else 1,
                    [tuple(map(float,v[1:3])) for v in child(child(z,'polygon'),'pts')[1:]]))

    def draw_pad(self,d,p,margin,fill):
        x,y=p['pos']; sx,sy=p['size']; sx+=2*margin; sy+=2*margin
        if p['shape']=='circle' or p['hole']:
            d.ellipse((*pt(x-sx/2,y-sy/2),*pt(x+sx/2,y+sy/2)),fill=fill)
        else:
            a=math.radians(p['angle']); ca,sa=math.cos(a),math.sin(a)
            corners=[(x+dx*ca+dy*sa,y-dx*sa+dy*ca) for dx,dy in [(-sx/2,-sy/2),(sx/2,-sy/2),(sx/2,sy/2),(-sx/2,sy/2)]]
            pixels=[pt(*q) for q in corners]
            if abs(p['angle']%90)<.0001:
                d.rectangle((math.ceil(min(q[0] for q in pixels)),math.ceil(min(q[1] for q in pixels)),math.floor(max(q[0] for q in pixels)),math.floor(max(q[1] for q in pixels))),fill=fill)
            else: d.polygon(pixels,fill=fill)

    def mask(self,net,layer,width=.25,routes=None):
        im=Image.new('L',(W,H),0); d=ImageDraw.Draw(im)
        m=width/2+.22
        # Copper edge clearance and the antenna rule areas.
        edge=math.ceil((.52+width/2)/STEP)
        d.rectangle((0,0,W-1,H-1),outline=255,width=edge)
        for l,points in self.keepouts:
            if l==layer: d.polygon([pt(*p) for p in points],fill=255)
        for p in self.pads:
            if layer in p['layers'] and (p['net']!=net or p['hole']): self.draw_pad(d,p,m,255)
        for r in (self.routes if routes is None else routes):
            if r['layer']==layer and r['net']!=net:
                rad=(r['width']/2+m)
                d.line([pt(*p) for p in r['points']],fill=255,width=math.ceil(2*rad/STEP))
                for p in (r['points'][0],r['points'][-1]):
                    d.ellipse((*pt(p[0]-rad,p[1]-rad),*pt(p[0]+rad,p[1]+rad)),fill=255)
        for v in self.vias:
            if v['net']!=net:
                x,y=v['pos']; r=.3+m
                d.ellipse((*pt(x-r,y-r),*pt(x+r,y+r)),fill=255)
        return np.asarray(im).copy()!=0

    @staticmethod
    def clear_segment(mask,a,b):
        ca,cb=cell(a),cell(b); length=max(abs(ca[0]-cb[0]),abs(ca[1]-cb[1]))
        for k in range(length+1):
            t=k/max(1,length); x=round(ca[0]+t*(cb[0]-ca[0])); y=round(ca[1]+t*(cb[1]-ca[1]))
            if x<0 or x>=W or y<0 or y>=H or mask[y,x]: return False
        return True

    def add_route(self,net,layer,width,points):
        if len(points)>1: self.routes.append(dict(net=net,layer=layer,width=width,points=points))

    def escape(self,p):
        net=p['net']; a=p['pos']; bottom=self.mask(net,1,.22); top=self.mask(net,0,.6); bv=self.mask(net,1,.6)
        # Prefer exiting along the long pad dimension, away from the body.
        candidates=[]
        for r in (.9,1.2,1.5,1.8,2.2,2.6,3,3.5,4,5):
            for ang in range(0,360,45):
                q=(round(a[0]+r*math.cos(math.radians(ang)),1),round(a[1]+r*math.sin(math.radians(ang)),1))
                c=cell(q)
                if 0<=c[0]<W and 0<=c[1]<H and not top[c[1],c[0]] and not bv[c[1],c[0]] and self.clear_segment(bottom,a,q):
                    candidates.append((r,q))
            if candidates: break
        if not candidates: raise RuntimeError('No via escape: '+p['ref']+'.'+p['num']+' '+net)
        _,q=candidates[0]
        self.add_route(net,1,.22,[a,q]); self.vias.append(dict(net=net,pos=q)); return q

    def astar(self,mask,start,ends):
        sc=cell(start); ec=[cell(v) for v in ends]
        request=dict(w=W,h=H,start=sc[1]*W+sc[0],ends=[y*W+x for x,y in ec])
        heat=getattr(self,'current_heat',None)
        self.server.stdin.write(json.dumps(request)+'\n')
        self.server.stdin.write(base64.b64encode(mask.astype(np.uint8).tobytes()).decode()+'\n')
        self.server.stdin.write((base64.b64encode(heat.tobytes()).decode() if heat is not None else '')+'\n'); self.server.stdin.flush()
        response=self.server.stdout.readline().strip()
        if not response: return None
        chain=list(map(int,response.split(','))); pts=[(v%W,v//W) for v in chain]
        simple=[pts[0]]; old=None
        for i in range(1,len(pts)):
            direction=(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1])
            if old and direction!=old: simple.append(pts[i-1])
            old=direction
        if pts[-1]!=simple[-1]: simple.append(pts[-1])
        result=[mm(v) for v in simple]; result[0]=start
        end=min(ends,key=lambda p:math.dist(p,result[-1]))
        if end!=result[-1]: result.append(end)
        return result

    def multilayer(self,net,start,ends,preferred,width):
        masks=[self.mask(net,l,width) for l in (0,1)]
        vm=self.mask(net,0,.6)|self.mask(net,1,.6)
        im=Image.fromarray(vm.astype(np.uint8)*255); d=ImageDraw.Draw(im)
        ports={}
        for p in self.pads:
            if p['net']!=net: continue
            self.draw_pad(d,p,.52,255)
            if p['drill']:
                ports[cell(p['pos'])]=p['pos']
        for v in self.vias:
            if v['net']==net:
                x,y=v['pos']; r=.82
                d.ellipse((*pt(x-r,y-r),*pt(x+r,y+r)),fill=255)
                ports[cell(v['pos'])]=v['pos']
        for c in ports:
            if not vm[c[1],c[0]]: d.point(c,fill=0)
        vm=np.asarray(im)>0
        def idx(p,layer):
            x,y=cell(p); return layer*W*H+y*W+x
        request=dict(mode='layers',w=W,h=H,start=idx(start,preferred),ends=[idx(p,preferred) for p in ends],preferred=preferred)
        self.server.stdin.write(json.dumps(request)+'\n')
        self.server.stdin.write(base64.b64encode(np.stack(masks).astype(np.uint8).tobytes()).decode()+'\n')
        self.server.stdin.write(base64.b64encode(vm.astype(np.uint8).tobytes()).decode()+'\n'); self.server.stdin.flush()
        response=self.server.stdout.readline().strip()
        if not response: return None
        chain=list(map(int,response.split(',')))
        parts=[]; layer=chain[0]//(W*H); points=[]
        for index in chain:
            l=index//(W*H); v=index%(W*H); p=mm((v%W,v//W))
            if l!=layer:
                q=ports.get(cell(p),p)
                if points: points[-1]=q
                parts.append((layer,points)); points=[p]; layer=l
                points=[q]
                if cell(p) not in ports: self.vias.append(dict(net=net,pos=p))
            else: points.append(p)
        parts.append((layer,points))
        anchors=[]
        for i,(l,pts) in enumerate(parts):
            if i==0: pts[0]=start
            if i==len(parts)-1: pts[-1]=min(ends,key=lambda p:math.dist(p,pts[-1]))
            simple=[pts[0]]; old=None
            for j in range(1,len(pts)):
                dx=round(pts[j][0]-pts[j-1][0],5); dy=round(pts[j][1]-pts[j-1][1],5)
                direction=(round(math.atan2(dy,dx),4) if dx or dy else old)
                if old is not None and direction!=old: simple.append(pts[j-1])
                old=direction
            if pts[-1]!=simple[-1]: simple.append(pts[-1])
            self.add_route(net,l,width,simple)
            if l==preferred: anchors.extend(simple)
        return anchors

    def run_layered(self):
        anchors={}
        for n in self.nets:
            pads=[p for p in self.pads if p['net']==n]
            anchors[n]=list(dict.fromkeys(p['pos'] if n in POWER or 0 in p['layers'] else self.escape(p) for p in pads))
        # Reserve narrow exits at the power switch before its neighbouring
        # connections can fence in a fine-pitch pin.
        for p in self.pads:
            if p['ref']=='U1' and p['net']:
                if p['num']=='3':
                    anchors[p['net']]=[(149,74.3) if p['pos']==v else v for v in anchors[p['net']]]
                    continue
                a=p['pos']; q=(144.3 if p['num']=='2' else (149.7 if p['num']=='5' else (145 if int(p['num'])<=3 else 149)),a[1])
                self.add_route(p['net'],1,.2,[a,q])
                anchors[p['net']]=[q if a==v else v for v in anchors[p['net']]]
                if p['num'] in ('2','5'): self.vias.append(dict(net=p['net'],pos=q))
        for y,sy in ((81.3,80.18),(87.7,88.82)):
            self.add_route('GND',1,.3,[(153.32,y),(153.32,sy),(153.895,sy)])
            q=(152.1,79 if sy<85 else 90)
            self.add_route('GND',1,.3,[(153.895,sy),q])
            self.vias.append(dict(net='GND',pos=q))
            anchors['GND']=[q if v in ((153.32,y),(153.895,sy)) else v for v in anchors['GND']]
        self.vias.append(dict(net='+5V_SYS',pos=(149,74.3)))
        self.add_route('+5V_SYS',1,.2,[(146.175,73),(147.0125,73),(147.0125,74.3),(147.85,74.3)])
        self.add_route('GND',1,.3,[(117.1375,63.55),(118.5,62.5)])
        self.vias.append(dict(net='GND',pos=(118.5,62.5)))
        anchors['GND']=[(118.5,62.5) if v==(117.1375,63.55) else v for v in anchors['GND']]
        anchors={k:list(dict.fromkeys(v)) for k,v in anchors.items()}
        order=['I2C_SDA','I2C_SCL','RTC_SDA_5V','RTC_SCL_5V','BME_CS','SPI_MOSI','SPI_SCK','SPI_MISO','VIN_ADC','VIN_DIV',
               'CC1','CC2','POWER_ST','+5V_USB','+5V_FUSED','+5V_SYS','+3V3_ESP','GND']
        failures=[]
        for net in order:
            if net not in anchors: continue
            pending=anchors[net].copy(); layer=1 if net in POWER else 0
            widths=[.5,.3,.2] if net.startswith('+') or net=='GND' else [.25,.2]
            connected=[pending.pop(0)]
            while pending:
                p=min(pending,key=lambda a:min(math.dist(a,b) for b in connected)); route=None
                for width in widths:
                    route=self.astar(self.mask(net,layer,width),p,connected)
                    if route:
                        self.add_route(net,layer,width,route); break
                if route is None:
                    for width in widths[1:] if len(widths)>2 else widths:
                        route=self.multilayer(net,p,connected,layer,width)
                        if route: break
                if route is None: failures.append((net,p)); print('UNROUTED',net,p,flush=True)
                else: connected.extend(route)
                pending.remove(p)
            print(net,'done; vias',len(self.vias),flush=True)
        self.finish_vias()
        self.save(failures)
        self.server.stdin.write('QUIT\n'); self.server.stdin.flush(); self.server.wait()
        return failures

    def finish_vias(self):
        # A search can leave two same-net transitions within one via diameter.
        # Keep one drill and connect the former centre on both copper layers;
        # the small links lie inside the two original copper disks.
        for a in self.vias.copy():
            if a not in self.vias: continue
            for b in self.vias.copy():
                if a is b or a['net']!=b['net']: continue
                distance=math.dist(a['pos'],b['pos'])
                if distance<.55:
                    for layer in (0,1): self.add_route(a['net'],layer,.2,[a['pos'],b['pos']])
                    self.vias.remove(b)
        def distance(p,a,b):
            dx,dy=b[0]-a[0],b[1]-a[1]; dd=dx*dx+dy*dy
            t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/dd)) if dd else 0
            return math.dist(p,(a[0]+t*dx,a[1]+t*dy))
        self.vias=[v for v in self.vias if len({r['layer'] for r in self.routes if r['net']==v['net'] and any(distance(v['pos'],a,b)<r['width']/2+.3 for a,b in zip(r['points'],r['points'][1:]))})==2]

    def save(self,failures):
        b=copy.deepcopy(self.b)
        child(child(b,'title_block'),'rev')[1]=Q('A4 user placement routing')
        for r in self.routes:
            for a,c in zip(r['points'],r['points'][1:]):
                if math.dist(a,c)<.0001: continue
                self.counter+=1
                b.append(['segment',['start',*map(fmt,a)],['end',*map(fmt,c)],['width',r['width']],['layer',Q('F.Cu' if r['layer']==0 else 'B.Cu')],['net',Q(r['net'])],['uuid',Q(uid('user-route-'+str(self.counter)))]])
        for i,v in enumerate(self.vias):
            b.append(['via',['at',*map(fmt,v['pos'])],['size',.6],['drill',.3],['layers',Q('F.Cu'),Q('B.Cu')],['net',Q(v['net'])],['uuid',Q(uid('user-via-'+str(i)))]])
        OUT.write_text(dump(b)+'\n',encoding='utf-8')
        (ROOT/'reports'/'user_routing.json').write_text(json.dumps(dict(failures=failures,routes=self.routes,vias=self.vias,erc_drc_run=False),indent=2),encoding='utf-8')
        self.preview()

    def preview(self):
        scale=12; margin=45; pw=round((X1-X0)*scale); ph=round((Y1-Y0)*scale)
        im=Image.new('RGB',(pw+2*margin,2*ph+150),'#f4f5f8'); d=ImageDraw.Draw(im)
        for layer in (0,1):
            oy=55+layer*(ph+55)
            def xy(p): return (margin+(p[0]-X0)*scale,oy+(p[1]-Y0)*scale)
            d.rectangle((margin,oy,margin+pw,oy+ph),fill='#183a30',outline='#666666',width=2)
            d.text((margin,oy-27),'F.Cu — сигналы (вид сверху)' if layer==0 else 'B.Cu — питание и GND (просмотр сверху, без зеркала)',font=self.font,fill='#172536')
            for l,poly in self.keepouts:
                if l==layer: d.polygon([xy(p) for p in poly],outline='#96773c',width=2)
            for r in self.routes:
                if r['layer']==layer:
                    color='#ee7770' if not layer else ('#7799ee' if r['net']!='GND' else '#78baa5')
                    d.line([xy(p) for p in r['points']],fill=color,width=max(2,round(r['width']*scale)),joint='curve')
            for p in self.pads:
                if layer not in p['layers']: continue
                x,y=xy(p['pos']); sx,sy=p['size']; angle=math.radians(p['angle'])
                if p['shape']=='circle' or p['hole']:
                    d.ellipse((x-sx*scale/2,y-sy*scale/2,x+sx*scale/2,y+sy*scale/2),fill='#d5b568' if not p['hole'] else '#f4f5f8')
                else:
                    d.polygon([(x+(dx*math.cos(angle)+dy*math.sin(angle))*scale,y+(-dx*math.sin(angle)+dy*math.cos(angle))*scale) for dx,dy in [(-sx/2,-sy/2),(sx/2,-sy/2),(sx/2,sy/2),(-sx/2,sy/2)]],fill='#d5b568')
                if p['drill']:
                    rr=p['drill']*scale/2; d.ellipse((x-rr,y-rr,x+rr,y+rr),fill='#f4f5f8')
            for v in self.vias:
                x,y=xy(v['pos']); d.ellipse((x-3.6,y-3.6,x+3.6,y+3.6),fill='#d5b568'); d.ellipse((x-1.8,y-1.8,x+1.8,y+1.8),fill='#183a30')
            for f in children(self.b,'footprint'):
                if (child(f,'layer')[1]=='F.Cu')==(layer==0):
                    x,y=xy(tuple(map(float,child(f,'at')[1:3]))); d.text((x+5,y+5),ref(f),font=self.font,fill='white')
        im.save(ROOT/'exports'/'user_routing_preview.png')

if __name__=='__main__':
    router=Router(load())
    if '--preview' in sys.argv:
        router.preview()
        router.server.stdin.write('QUIT\n'); router.server.stdin.flush(); router.server.wait()
    else:
        t=time.monotonic(); failures=router.run_layered(); print('Seconds:',round(time.monotonic()-t,1),'Unrouted:',len(failures))
