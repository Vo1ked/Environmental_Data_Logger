"""Reproducible KiCad sources for the EDL carrier; no firmware compilation.

Run with the Python shipped with KiCad 10. The generated project is self-contained
except optional standard-library 3D models. Module envelopes are provisional.
"""
from pathlib import Path
import copy
import csv
import json
import math
import re
import uuid

ROOT = Path(__file__).resolve().parents[1]
KICAD = Path(r"E:\Embedded\KiCad\share\kicad")
PROJECT = "Environmental_Data_Logger"
ROOT_UUID = "00312c57-20e6-48e3-8808-307c8d4bf376"
NS = uuid.UUID(ROOT_UUID)


def uid(key):
    return str(uuid.uuid5(NS, key))


class Q(str):
    pass


def parse(text):
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text)
    stack = []
    result = None
    for token in tokens:
        if token == '(':
            node = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
        elif token == ')':
            result = stack.pop()
        else:
            stack[-1].append(Q(json.loads(token)) if token.startswith('"') else token)
    return result


def dump(node, level=0):
    if isinstance(node, Q):
        return json.dumps(str(node), ensure_ascii=False)
    if not isinstance(node, list):
        return str(node)
    if not any(isinstance(v, list) for v in node):
        return '(' + ' '.join(dump(v) for v in node) + ')'
    out = '(' + ' '.join(dump(v) for v in node if not isinstance(v, list))
    for v in node:
        if isinstance(v, list):
            out += '\n' + '  ' * (level + 1) + dump(v, level + 1)
    return out + ')'


def child(node, key):
    return next((v for v in node if isinstance(v, list) and v and v[0] == key), None)


def children(node, key):
    return [v for v in node if isinstance(v, list) and v and v[0] == key]


def prop(name, value, x=0, y=0, hide=False, size=1.27):
    p = ['property', Q(name), Q(value), ['at', x, y, 0], ['effects', ['font', ['size', size, size]]]]
    if hide:
        p.append(['hide', 'yes'])
    return p


LIBS = {}
SYMS = {}


def library_symbol(library, name):
    if library not in LIBS:
        LIBS[library] = parse((KICAD / 'symbols' / (library + '.kicad_sym')).read_text(encoding='utf-8'))
    source = next(v for v in children(LIBS[library], 'symbol') if v[1] == name)
    result = copy.deepcopy(source)
    parent = child(result, 'extends')
    if parent:
        base = library_symbol(library, str(parent[1]))
        base[1] = Q(name)
        for sub in children(base, 'symbol'):
            sub[1] = Q(str(sub[1]).replace(str(parent[1]), name, 1))
        for p in children(result, 'property'):
            old = next((v for v in children(base, 'property') if v[1] == p[1]), None)
            if old:
                base.remove(old)
            base.append(p)
        result = base
    SYMS[name] = result
    return result


def custom_module(name, description, pins, width=20.32):
    height = (len(pins) + 1) * 2.54
    s = ['symbol', Q(name), ['pin_names', ['offset', 1.016]], ['in_bom', 'yes'], ['on_board', 'yes'],
         prop('Reference', 'M', 0, height/2 + 3.81), prop('Value', name, 0, height/2 + 1.27),
         prop('Footprint', 'EDL:' + name, hide=True), prop('Datasheet', '', hide=True), prop('Description', description, hide=True)]
    s.append(['symbol', Q(name+'_0_1'), ['rectangle', ['start', -width/2, height/2], ['end', width/2, -height/2], ['stroke', ['width', .254], ['type', 'default']], ['fill', ['type', 'background']]]])
    unit = ['symbol', Q(name+'_1_1')]
    for i, (label, typ) in enumerate(pins):
        unit.append(['pin', typ, 'line', ['at', -width/2-5.08, height/2-(i+1)*2.54, 0], ['length', 5.08],
                     ['name', Q(label), ['effects', ['font', ['size', 1.016, 1.016]]]],
                     ['number', Q(str(i+1)), ['effects', ['font', ['size', 1.016, 1.016]]]]])
    s.append(unit)
    SYMS[name] = s


def custom_switch():
    name = 'SN74CBTLV1G125DBV'
    s = ['symbol', Q(name), ['in_bom', 'yes'], ['on_board', 'yes'], prop('Reference', 'U', 0, 8.89), prop('Value', name, 0, -8.89), prop('Footprint', 'EDL:SOT-23-5', hide=True), prop('Datasheet', 'https://www.ti.com/lit/ds/symlink/sn74cbtlv1g125.pdf', hide=True)]
    s.append(['symbol', Q(name+'_0_1'), ['rectangle', ['start', -7.62, 6.35], ['end', 7.62, -6.35], ['stroke', ['width', .254], ['type', 'default']], ['fill', ['type', 'background']]]])
    u = ['symbol', Q(name+'_1_1')]
    for num, label, typ, x, y, angle in [('1','~{OE}','input',-10.16,-2.54,0),('2','A','passive',-10.16,2.54,0),('3','GND','power_in',0,-8.89,90),('4','B','passive',10.16,2.54,180),('5','VCC','power_in',0,8.89,270)]:
        u.append(['pin',typ,'line',['at',x,y,angle],['length',2.54],['name',Q(label),['effects',['font',['size',1.27,1.27]]]],['number',Q(num),['effects',['font',['size',1.27,1.27]]]]])
    s.append(u)
    SYMS[name] = s


FOOTPRINTS = {}


def footprint(source):
    lib, name = source.split(':')
    if name not in FOOTPRINTS:
        fp = parse((KICAD / 'footprints' / (lib + '.pretty') / (name + '.kicad_mod')).read_text(encoding='utf-8'))
        FOOTPRINTS[name] = fp
    return 'EDL:' + name


ALL_COMPONENTS = []
GLOBAL_NETS = {'GND', '+5V_SYS', '+3V3_ESP', 'I2C_SDA', 'I2C_SCL', 'SPI_SCK', 'SPI_MOSI', 'SPI_MISO', 'BME_CS'}


class Sheet:
    def __init__(self, filename, title, sheet_id, page):
        self.filename, self.title, self.id, self.page = filename, title, sheet_id, page
        self.parts, self.graphics, self.used, self.count = [], [], set(), 0
        self.terminals = {}

    def key(self, kind):
        self.count += 1
        return uid(self.filename + ':' + kind + ':' + str(self.count))

    def text(self, text, x, y, size=1.27):
        self.graphics.append(['text',Q(text),['at',x,y,0],['effects',['font',['size',size,size]],['justify','left','top']],['uuid',self.key('text')]])

    def wire(self, a, b):
        if a == b:
            return
        self.graphics.append(['wire',['pts',['xy',*a],['xy',*b]],['stroke',['width',0],['type','default']],['uuid',self.key('wire')]])

    def label(self, net, x, y, angle=0):
        if net in GLOBAL_NETS:
            self.graphics.append(['global_label',Q(net),['shape','bidirectional'],['at',x,y,angle],['effects',['font',['size',1.016,1.016]],['justify','right' if angle==180 else 'left']],['uuid',self.key('label')],prop('Intersheetrefs','${INTERSHEET_REFS}',x,y,True)])
        else:
            self.graphics.append(['label',Q(net),['at',x,y,angle],['effects',['font',['size',1.016,1.016]],['justify','left','bottom']],['uuid',self.key('label')]])

    def add(self, name, ref, value, x, y, nets, fp='', angle=0, mpn='', note='', dnp=False, auto=True):
        self.used.add(name)
        s = SYMS[name]
        symbol_id = uid('part:'+ref)
        properties = {str(v[1]): str(v[2]) for v in children(s,'property')}
        fp = fp or properties.get('Footprint','')
        if fp and not fp.startswith('EDL:'):
            fp = footprint(fp)
        part = ['symbol',['lib_id',Q('EDL:'+name)],['at',x,y,angle],['unit',1],['in_bom','yes'],['on_board','yes'],['dnp','yes' if dnp else 'no'],['uuid',symbol_id]]
        for p in children(s, 'property'):
            pn = str(p[1])
            if pn.startswith('ki_'):
                continue
            v = {'Reference':ref,'Value':value,'Footprint':fp}.get(pn,str(p[2]))
            at = child(p,'at') or ['at',0,0,0]
            if pn in ('Reference','Value'):
                dx,dy = float(at[1]),-float(at[2])
                if name in ('R','C','Fuse','D_TVS'):
                    dx,dy = (3.81,-1.27 if pn=='Reference' else 1.27)
                    if angle:
                        dx,dy = (0,-5.08 if pn=='Reference' else -2.54)
                pnew=prop(pn,v,x+dx,y+dy,False,1.016)
                if name=='PWR_FLAG':
                    child(pnew,'effects').append(['hide','yes'])
                if name in ('R','C','Fuse','D_TVS') and angle:
                    child(pnew,'at')[3]=angle
                if name=='D_TVS' and angle in (90,270):
                    child(pnew,'at')[1:3]=[x+5.08,y+(-1.27 if pn=='Reference' else 1.27)]
                    child(pnew,'effects').append(['justify','left'])
                if name in ('R','C','Fuse','D_TVS') and not angle:
                    child(pnew,'effects').append(['justify','left'])
                if name in ('LM66100DCK','TCA9406DC','SN74CBTLV1G125DBV'):
                    pnew=prop(pn,v,x+12.7,y-11.43 if pn=='Reference' else y-8.89,False,1.016)
                    child(pnew,'effects').append(['justify','left'])
                part.append(pnew)
            else:
                part.append(prop(pn,v,x,y,True))
        part.extend([prop('MPN',mpn,x,y,True),prop('Assembly',note,x,y,True)])
        pins = {}
        for sub in children(s,'symbol'):
            if not str(sub[1]).endswith(('_1_1','_0_1','_1_0','_0_0')):
                continue
            for p in children(sub,'pin'):
                num = str(child(p,'number')[1])
                at = child(p,'at')
                dx, dy, pa = float(at[1]),float(at[2]),float(at[3])
                a=math.radians(angle)
                px=round(x+dx*math.cos(a)-dy*math.sin(a),5)
                py=round(y-dx*math.sin(a)-dy*math.cos(a),5)
                pa=(pa+angle)%360
                pins[num]=(px,py,pa)
                part.append(['pin',Q(num),['uuid',uid(ref+':'+num)]])
        path = '/'+ROOT_UUID + (('/'+uid('sheet:modules')) if self.page != 1 else '')
        part.append(['instances',['project',Q(PROJECT),['path',Q(path),['reference',Q(ref)],['unit',1]]]])
        self.parts.append(part)
        net_map = {str(k):v for k,v in nets.items()}
        assert not set(net_map)-set(pins), (ref,'unknown pins',set(net_map)-set(pins))
        ALL_COMPONENTS.append(dict(ref=ref,value=value,symbol=name,footprint=fp,mpn=mpn,note=note,dnp=dnp,uuid=symbol_id,sheet=self.filename,nets=net_map))
        if auto:
            seen=set()
            for num,(px,py,pa) in pins.items():
                net=net_map.get(num)
                point=(px,py)
                if not net:
                    if point not in seen:
                        self.graphics.append(['no_connect',['at',px,py],['uuid',self.key('nc')]])
                elif point not in seen:
                    dx,dy={0:(-5.08,0),90:(0,5.08),180:(5.08,0),270:(0,-5.08)}[pa]
                    end=(round(px+dx,5),round(py+dy,5))
                    self.wire(point,end)
                    self.label(net,*end,180 if dx<0 or (name=='TCA9406DC' and num=='3') else 0)
                    self.terminals[(ref,num)] = (point, self.graphics[-2:])
                seen.add(point)
        return pins

    def join(self, ref1, pin1, ref2, pin2, via=(), net=None):
        ends=[]
        for key in [(ref1,str(pin1)),(ref2,str(pin2))]:
            point, graphics=self.terminals[key]
            for graphic in graphics:
                if graphic in self.graphics:
                    self.graphics.remove(graphic)
            ends.append(point)
        points=[ends[0],*via,ends[1]]
        for a,b in zip(points,points[1:]):
            self.wire(a,b)
        if net:
            self.label(net,*ends[0])

    def save(self):
        syms=[]
        for name in sorted(self.used):
            s=copy.deepcopy(SYMS[name]); s[1]=Q('EDL:'+name); syms.append(s)
        root=['kicad_sch',['version',20260306],['generator',Q('eeschema')],['generator_version',Q('10.0')],['uuid',self.id],['paper',Q('A3')],
              ['title_block',['title',Q(self.title)],['date',Q('2026-11-15')],['rev',Q('A1')],['company',Q('Environmental Data Logger')],['comment',1,Q('Prototype: verify module fit before manufacture')]], ['lib_symbols',*syms], *self.graphics, *self.parts]
        if self.page==1:
            root.append(['sheet_instances',['path',Q('/'),['page',Q('1')]]])
        root.append(['embedded_fonts','no'])
        (ROOT/self.filename).write_text(dump(root)+'\n',encoding='utf-8')


def module_footprint(name, count, outline, horizontal=True):
    xmin,ymin,xmax,ymax=outline
    f=['footprint',Q(name),['version',20260206],['generator',Q('pcbnew')],['layer',Q('F.Cu')],['descr',Q('2.54 mm header; provisional module envelope; verify with physical module')],['tags',Q('EDL module prototype')],['attr','through_hole'],
       ['property',Q('Reference'),Q('REF**'),['at',0,-5,0],['layer',Q('F.SilkS')],['effects',['font',['size',1,1],['thickness',.15]]]],
       ['property',Q('Value'),Q(name),['at',0,0,0],['layer',Q('F.Fab')],['hide','yes'],['effects',['font',['size',1,1],['thickness',.15]]]]]
    for layer,margin,width in [('F.Fab',0,.1),('F.CrtYd',3,.05)]:
        f.append(['fp_rect',['start',xmin-margin,ymin-margin],['end',xmax+margin,ymax+margin],['stroke',['width',width],['type','default']],['fill','none'],['layer',Q(layer)]])
    for i in range(count):
        x,y=(i*2.54,0) if horizontal else (0,i*2.54)
        f.append(['pad',Q(str(i+1)),'thru_hole','rect' if i==0 else 'circle',['at',x,y],['size',1.8,1.8],['drill',1],['layers',Q('*.Cu'),Q('*.Mask')]])
    f.append(['fp_line',['start',-1.15,-1.15],['end',1.15,-1.15],['stroke',['width',.15],['type','default']],['layer',Q('F.SilkS')]])
    FOOTPRINTS[name]=f


def generate():
    (ROOT/'EDL.pretty').mkdir(exist_ok=True)
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'exports').mkdir(exist_ok=True)
    for lib,name in [('Device','R'),('Device','C'),('Device','Fuse'),('Device','D_TVS'),('Connector','TestPoint'),('Connector','USB_C_Receptacle_USB2.0_16P'),('Power_Management','LM66100DCK'),('Interface','TCA9406DC'),('power','PWR_FLAG')]:
        library_symbol(lib,name)
    names=['3V3','3V3','EN','GPIO4','GPIO5','GPIO6','GPIO7 / ADC1_CH6','GPIO15','GPIO16','GPIO17','GPIO18','GPIO8 / SDA','GPIO3','GPIO46','GPIO9 / SCL','GPIO10 / CS','GPIO11 / MOSI','GPIO12 / SCK','GPIO13 / MISO','GPIO14','5V_IN','GND']
    types=['power_out','passive','input']+['bidirectional']*17+['power_in','power_in']
    types[6]='input'; types[15]=types[16]=types[17]='output'; types[18]='input'
    custom_module('YD_ESP32_S3_LeftRow22','YD-ESP32-S3 J1 left row only; IN-OUT and USB-OTG OPEN',list(zip(names,types)),33.02)
    custom_module('Tiny_RTC_Row5','Tiny RTC DS1307 module; CR2032 charging path MUST be disabled',[('GND','power_in'),('VCC_5V','power_in'),('SDA','bidirectional'),('SCL','input'),('DS_1WIRE_UNUSED','passive')],30.48)
    custom_module('OLED_SSD1306_Row4','I2C OLED module front view: GND VDD SCK SDA',[('GND','power_in'),('VDD_3V3','power_in'),('SCK_SCL','input'),('SDA','bidirectional')],25.4)
    custom_module('BME280_SPI_Row6','GY-BME/P280 module; verify BME280 chip ID 0x60',[('VCC_3V3','power_in'),('GND','power_in'),('SCL_SCK','input'),('SDA_SDI','input'),('CSB','input'),('SDO','output')],25.4)
    custom_switch()
    module_footprint('YD_ESP32_S3_LeftRow22',22,(-8,-28,62,2))
    module_footprint('Tiny_RTC_Row5',5,(-28,-6,2,24),False)
    module_footprint('OLED_SSD1306_Row4',4,(-10,-2,17,26))
    module_footprint('BME280_SPI_Row6',6,(-2,-11,15,1))
    rfp=footprint('Resistor_SMD:R_0805_2012Metric')
    cfp=footprint('Capacitor_SMD:C_0805_2012Metric')
    tfp=footprint('TestPoint:TestPoint_Pad_D1.5mm')
    power=Sheet(PROJECT+'.kicad_sch','01 Power / ESP / ADC',ROOT_UUID,1)
    power.text('USB-C POWER INPUT  |  5 V regulated supply, >= 1 A',20.32,20.32,2.032)
    power.add('USB_C_Receptacle_USB2.0_16P','J1','USB4105-GF-A',43.18,60.96,{'A4':'+5V_USB','A9':'+5V_USB','B4':'+5V_USB','B9':'+5V_USB','A1':'GND','A12':'GND','B1':'GND','B12':'GND','SH':'GND','A5':'CC1','B5':'CC2'},'Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal',mpn='USB4105-GF-A')
    power.add('R','R1','5.1k 1%',91.44,66.04,{'1':'CC1','2':'GND'},rfp,mpn='0805 5.1k 1%')
    power.add('R','R2','5.1k 1%',116.84,66.04,{'1':'CC2','2':'GND'},rfp,mpn='0805 5.1k 1%')
    power.add('Fuse','F1','1A fast',99.06,45.72,{'1':'+5V_USB','2':'+5V_FUSED'},'Fuse:Fuse_1206_3216Metric',angle=90,mpn='0466001.NR',note='Verify supplier resistance; test RTC rail >=4.5V under full load')
    power.add('D_TVS','D1','PESD5V0S1BA',73.66,116.84,{'1':'+5V_FUSED','2':'GND'},'Diode_SMD:D_SOD-323',angle=270,mpn='PESD5V0S1BA',note='ESD protection, not sustained overvoltage protection')
    power.add('C','C1','1u 16V X7R',111.76,116.84,{'1':'+5V_FUSED','2':'GND'},cfp)
    power.add('LM66100DCK','U1','LM66100DCKR',162.56,48.26,{'1':'+5V_FUSED','2':'GND','3':'+5V_SYS','5':'POWER_ST','6':'+5V_SYS'},mpn='LM66100DCKR',note='CE tied to VOUT for reverse-current blocking; NC pin 4 open; unused ST held low via R6')
    power.add('R','R6','10k 1%',210.82,86.36,{'1':'POWER_ST','2':'GND'},rfp)
    power.add('C','C2','4.7u 16V X7R',162.56,121.92,{'1':'+5V_SYS','2':'GND'},cfp)
    power.add('C','C3','100n 16V X7R',200.66,121.92,{'1':'+5V_SYS','2':'GND'},cfp)
    power.join('J1','A4','F1','1',net='+5V_USB')
    power.join('F1','2','U1','1',net='+5V_FUSED')
    power.join('J1','A5','R1','1',via=((91.44,50.8),))
    power.join('J1','B5','R2','1',via=((116.84,53.34),))
    power.add('PWR_FLAG','#FLG01','PWR_FLAG',20.32,134.62,{'1':'GND'})
    power.add('PWR_FLAG','#FLG02','PWR_FLAG',48.26,134.62,{'1':'+5V_USB'})
    power.add('PWR_FLAG','#FLG03','PWR_FLAG',81.28,144.78,{'1':'+5V_FUSED'})
    power.text('CE = VOUT: reverse-current blocking. USB D+/D-/SBU unused.\nNormal operation requires +5V_SYS >= 4.5 V at RTC.\nUSB-C source must supply 5 V; no USB PD or data on J1.',20.32,157.48)
    power.text('CONTROLLER  |  SINGLE SOLDERED 1x22 ROW',254,20.32,2.032)
    power.add('YD_ESP32_S3_LeftRow22','M1','YD-ESP32-S3',302.26,73.66,{'1':'+3V3_ESP','2':'+3V3_ESP','7':'VIN_ADC','12':'I2C_SDA','15':'I2C_SCL','16':'BME_CS','17':'SPI_MOSI','18':'SPI_SCK','19':'SPI_MISO','21':'+5V_SYS','22':'GND'},note='IN-OUT OPEN; USB-OTG OPEN; use onboard CH343P USB for commands')
    power.add('C','C4','4.7u 10V X7R',353.06,114.3,{'1':'+3V3_ESP','2':'GND'},cfp)
    power.add('C','C5','100n 16V X7R',388.62,114.3,{'1':'+3V3_ESP','2':'GND'},cfp)
    power.text('M1 regulator supplies OLED, BME280 and low-voltage logic.\nNo second 3.3 V regulator connected in parallel.\nCH343P already connects to GPIO43/44 on M1.\nBoth M1 power jumpers remain OPEN.\nUSB on M1 alone: ESP/OLED/BME run, RTC main supply absent.',254,144.78)
    power.text('INPUT VOLTAGE MONITOR  |  GPIO7 / ADC1_CH6',20.32,187.96,2.032)
    power.add('R','R3','27k 1%',38.1,213.36,{'1':'+5V_SYS','2':'VIN_DIV'},rfp)
    power.add('R','R4','10k 1%',76.2,213.36,{'1':'VIN_DIV','2':'GND'},rfp)
    power.add('SN74CBTLV1G125DBV','U3','SN74CBTLV1G125DBVR',137.16,213.36,{'1':'GND','2':'VIN_DIV','3':'GND','4':'VIN_ADC','5':'+3V3_ESP'},footprint('Package_TO_SOT_SMD:SOT-23-5'),mpn='SN74CBTLV1G125DBVR',note='Ioff isolates ADC divider when ESP 3V3 is absent')
    power.add('C','C6','100n 16V X7R',190.5,213.36,{'1':'VIN_ADC','2':'GND'},cfp)
    power.add('C','C7','100n 16V X7R',137.16,251.46,{'1':'+3V3_ESP','2':'GND'},cfp)
    power.text('VADC = VSYS / 3.7  |  5 V -> 1.351 V\n5.5 V + 1% resistor worst case -> < 1.51 V\nADC attenuation: 6 dB; calibration + averaging in firmware.\nU3 is an analog FET switch, NOT a logic buffer.',20.32,238.76)
    for ref,net,x in [('TP1','+5V_USB',254),('TP2','+5V_SYS',289.56),('TP3','+3V3_ESP',325.12),('TP4','GND',360.68)]:
        power.add('TestPoint',ref,net,x,187.96,{'1':net},tfp)
    power.add('TestPoint','TP5','VIN_ADC',228.6,213.36,{'1':'VIN_ADC'},tfp)
    sheet=['sheet',['at',284.48,220.98],['size',93.98,22.86],['stroke',['width',.254],['type','default']],['fill',['color',0,0,0,0]],['uuid',uid('sheet:modules')],prop('Sheetname','02 - Modules and I2C level translation',284.48,219.71),prop('Sheetfile','modules.kicad_sch',284.48,245.11),['instances',['project',Q(PROJECT),['path',Q('/'+ROOT_UUID),['page',Q('2')]]]]]
    power.graphics.append(sheet)
    mod=Sheet('modules.kicad_sch','02 Sensors / RTC / display',uid('file:modules'),2)
    mod.text('RTC I2C LEVEL TRANSLATION  |  100 kHz',20.32,20.32,2.032)
    mod.add('TCA9406DC','U2','TCA9406DCTR',99.06,68.58,{'1':'RTC_SDA_5V','2':'GND','3':'+3V3_ESP','4':'I2C_SDA','5':'I2C_SCL','6':'+3V3_ESP','7':'+5V_SYS','8':'RTC_SCL_5V'},'Package_SO:SSOP-8_2.95x2.8mm_P0.65mm',mpn='TCA9406DCTR',note='Partial-power-down isolation; internal 10k pulls on both sides')
    mod.add('Tiny_RTC_Row5','M2','Tiny RTC / DS1307',210.82,66.04,{'1':'GND','2':'+5V_SYS','3':'RTC_SDA_5V','4':'RTC_SCL_5V'},note='CR2032; disable charging path and verify VBAT network before installation')
    mod.add('C','C8','100n 16V X7R',40.64,114.3,{'1':'+3V3_ESP','2':'GND'},cfp)
    mod.add('C','C9','100n 16V X7R',91.44,114.3,{'1':'+5V_SYS','2':'GND'},cfp)
    mod.add('C','C10','100n 16V X7R',142.24,114.3,{'1':'+5V_SYS','2':'GND'},cfp)
    mod.text('U2: internal 10k pullups; RTC/OLED modules also contain pullups.\nKeep the RTC module 5 V pullups on the HIGH side only.\nU2 isolates the bus if either supply is absent.\nConfirm rise time and low level on populated hardware.',20.32,144.78)
    mod.text('CR2032 IS NOT RECHARGEABLE.\nDisable and verify the Tiny RTC charging path BEFORE fitting cell.\nVerify DS1307 VBAT = 2.0..3.5 V and remove any incompatible\nbattery divider after checking the exact module traces.\nDo not copy component designators from a different Tiny RTC revision.',20.32,177.8)
    mod.text('OLED  |  3.3 V I2C / 0x3C',274.32,20.32,2.032)
    mod.add('OLED_SSD1306_Row4','M3','SSD1306 128x64',330.2,60.96,{'1':'GND','2':'+3V3_ESP','3':'I2C_SCL','4':'I2C_SDA'},note='Front view: GND VDD SCK SDA; SCK means I2C SCL')
    mod.add('C','C11','100n 16V X7R',292.1,106.68,{'1':'+3V3_ESP','2':'GND'},cfp)
    mod.add('C','C12','1u 10V X7R',355.6,106.68,{'1':'+3V3_ESP','2':'GND'},cfp)
    mod.text('BME280  |  FOUR-WIRE SPI / 1 MHz',274.32,144.78,2.032)
    mod.add('BME280_SPI_Row6','M4','GY-BME280 / SPI',335.28,187.96,{'1':'+3V3_ESP','2':'GND','3':'SPI_SCK','4':'SPI_MOSI','5':'BME_CS','6':'SPI_MISO'},note='Keep away from ESP/regulator heat; inspect sensor ID 0x60')
    mod.add('R','R5','10k 1%',279.4,231.14,{'1':'+3V3_ESP','2':'BME_CS'},rfp)
    mod.add('C','C13','100n 16V X7R',330.2,231.14,{'1':'+3V3_ESP','2':'GND'},cfp)
    mod.add('C','C14','1u 10V X7R',381,231.14,{'1':'+3V3_ESP','2':'GND'},cfp)
    for ref,net,x in [('TP6','I2C_SDA',35.56),('TP7','I2C_SCL',86.36),('TP8','RTC_SDA_5V',137.16),('TP9','RTC_SCL_5V',203.2)]:
        mod.add('TestPoint',ref,net,x,233.68,{'1':net},tfp)
    mod.text('Module contact pitch = 2.54 mm. Body envelopes + 3 mm margin.\nPin order checked against supplied photos; mounting-hole coordinates\nare not measured. Fit-check a 1:1 print before ordering a PCB.',20.32,256.54)
    power.save(); mod.save()
    (ROOT/'EDL.kicad_sym').write_text(dump(['kicad_symbol_lib',['version',20250930],['generator',Q('kicad_symbol_editor')],*SYMS.values()])+'\n',encoding='utf-8')
    for name,f in FOOTPRINTS.items():
        (ROOT/'EDL.pretty'/(name+'.kicad_mod')).write_text(dump(f)+'\n',encoding='utf-8')
    (ROOT/'sym-lib-table').write_text('(sym_lib_table (version 7) (lib (name "EDL") (type "KiCad") (uri "${KIPRJMOD}/EDL.kicad_sym") (options "") (descr "EDL local symbols")))\n',encoding='utf-8')
    (ROOT/'fp-lib-table').write_text('(fp_lib_table (version 7) (lib (name "EDL") (type "KiCad") (uri "${KIPRJMOD}/EDL.pretty") (options "") (descr "EDL local footprints")))\n',encoding='utf-8')
    (ROOT/'design_manifest.json').write_text(json.dumps(ALL_COMPONENTS,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (ROOT/'exports'/'bom.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f); writer.writerow(['Reference','Value','MPN','Footprint','Assembly notes'])
        for c in ALL_COMPONENTS:
            if not c['ref'].startswith('#'):
                writer.writerow([c['ref'],c['value'],c['mpn'],c['footprint'],c['note']])
    print(f'Generated {len(ALL_COMPONENTS)} symbols, {len(FOOTPRINTS)} local footprints, two schematic sheets.')


if __name__ == '__main__':
    generate()
