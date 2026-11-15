"""Placement A3: compact outline and USB ports toward the right; no routing/checks."""
import hashlib
import json
import zipfile
import pcbnew as p
from generate_board import ROOT, PROJECT, xy, line, text

TOP={'M1':(98,52,0),'M2':(82,74,0),'M3':(130,85,90),'M4':(116,76,180)}
BACK={
    'J1':(156.325,64,270),'F1':(149,60,90),'D1':(149,68,90),'U1':(143,63,0),
    'R1':(150,72,0),'R2':(150,75.5,0),'R3':(108,61,90),'R4':(108,66,90),
    'R5':(109,70.5,0),'R6':(143,67.5,0),'U3':(113.5,62,0),'U2':(91.5,76,0),
    'C1':(146.5,60,90),'C2':(139.5,60,90),'C3':(139.5,65,90),
    'C4':(98,61,90),'C5':(102,61,90),'C6':(118,62,90),'C7':(113.5,66.5,0),
    'C8':(91.5,81,0),'C9':(91.5,71,0),'C10':(78,76,90),
    'C11':(135,82,0),'C12':(135,86,0),'C13':(116,80,90),'C14':(120,80,90),
    'TP1':(154,77,0),'TP2':(143,73,0),'TP3':(97,67.5,0),'TP4':(147,84,0),
    'TP5':(119.5,66.5,0),'TP6':(122,72,0),'TP7':(127,72,0),'TP8':(87,85,0),'TP9':(94,85,0),
}
HOLES={'H1':(54,54),'H2':(128,60),'H3':(54,104),'H4':(155,104)}
OUTLINE=[(50,50),(160,50),(160,108),(50,108)]
RF_KEEPOUT=[(50.5,50.5),(96.5,50.5),(96.5,68),(50.5,68)]


def main():
    path=ROOT/(PROJECT+'.kicad_pcb')
    old_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    backup=ROOT/'revisions'/'A2_before_compact_A3.zip'
    if not backup.exists():
        files=[path,ROOT/(PROJECT+'.kicad_pro'),ROOT/'placement_A2.json',ROOT/'LAYOUT_STATUS.md',ROOT/'exports'/'placement_A2.png']
        with zipfile.ZipFile(backup,'w',zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                if file.exists(): archive.write(file,file.relative_to(ROOT))
    b=p.LoadBoard(str(path))
    tracks=b.GetTracks()
    for t in tracks:
        b.Remove(t); t.thisown=True
    fps={f.GetReference():f for f in b.GetFootprints()}
    for ref,(x,y,a) in {**TOP,**BACK}.items():
        f=fps[ref]; bottom=ref in BACK
        if (f.GetLayer()==p.B_Cu)!=bottom: f.Flip(f.GetPosition(),p.FLIP_DIRECTION_LEFT_RIGHT)
        f.SetPosition(xy(x,y)); f.SetOrientationDegrees(a)
        f.Reference().SetLayer(p.B_SilkS if bottom else p.F_SilkS); f.Reference().SetMirrored(bottom)
        f.Reference().SetTextAngle(p.EDA_ANGLE(0,p.DEGREES_T)); f.Reference().SetPosition(xy(x,y-2.6))
    for ref,position in HOLES.items(): fps[ref].SetPosition(xy(*position))
    for ref,x,y in [('M1',132,55.5),('M2',69,100),('M3',141,98),('M4',109,90),('R6',143,69.7),('R2',146.5,75.5),('C7',113.5,68.8)]:
        fps[ref].Reference().SetPosition(xy(x,y))
    drawings=list(b.GetDrawings())
    for drawing in drawings:
        if drawing.GetLayer()==p.Edge_Cuts:
            b.Remove(drawing); drawing.thisown=True
    for a,c in zip(OUTLINE,OUTLINE[1:]+OUTLINE[:1]): line(b,a,c)
    zones=list(b.Zones())
    for z in zones:
        points=RF_KEEPOUT if z.GetIsRuleArea() else [(50.5,50.5),(159.5,50.5),(159.5,107.5),(50.5,107.5)]
        z.UnFill(); z.Outline().RemoveAllContours(); z.Outline().NewOutline()
        for x,y in points: z.Outline().Append(p.FromMM(x),p.FromMM(y))
    labels={
        'USB 5V IN':(150,57,p.F_SilkS),'RTC / CR2032':(69,64.5,p.F_SilkS),
        'DISABLE RTC CHARGE':(69,66.5,p.F_SilkS),'OLED 3V3':(141,65,p.F_SilkS),
        'BME280 / SPI':(109,72,p.F_SilkS),'VIN ADC':(112,58,p.B_SilkS),
        'VBUS':(154,79,p.B_SilkS),'5V':(143,75,p.B_SilkS),'3V3':(97,69.5,p.B_SilkS),
        'GND':(147,86,p.B_SilkS),'ADC':(119.5,68.5,p.B_SilkS),'SDA':(122,74,p.B_SilkS),
        'SCL':(127,74,p.B_SilkS),'SDA5':(87,87,p.B_SilkS),'SCL5':(94,87,p.B_SilkS),
        'SMD ON BACK':(109,94,p.F_SilkS),'ANTENNA':(82,58,p.F_SilkS),
        'ESP: IN-OUT + USB-OTG OPEN':(110,98,p.F_SilkS),
        'ENVIRONMENTAL DATA LOGGER':(100,104.8,p.F_SilkS),
    }
    for t in b.GetDrawings():
        if not isinstance(t,p.PCB_TEXT): continue
        s=t.GetText()
        if s in labels:
            x,y,layer=labels[s]; t.SetPosition(xy(x,y)); t.SetLayer(layer); t.SetMirrored(layer==p.B_SilkS)
        elif s=='A2 PLACEMENT DRAFT':
            t.SetText('A3 / 110 x 58 mm'); t.SetPosition(xy(140,104.8))
    title=b.GetTitleBlock(); title.SetRevision('A3 placement draft'); b.SetTitleBlock(title)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==old_hash, 'PCB changed on disk; not overwriting'
    p.SaveBoard(str(path),b)
    layout={'revision':'A3','status':'placement draft, unrouted, no full checks','board_size_mm':[110,58],
            'outline':OUTLINE,'rf_keepout':RF_KEEPOUT,'usb_mouth_target_x_mm':160,
            'usb_alignment':'Right-hand mating faces aligned in top view using the provisional ESP module outline; heights differ.',
            'routing_policy':{'F.Cu':'signals primarily','B.Cu':'power primarily; preserve connected GND plane'},
            'power_topology':'unchanged: +5V_SYS feeds M1 regulator; M1 provides +3V3_ESP',
            'top':TOP,'bottom':BACK,'mounting_holes':HOLES,'previous_placement':str(backup.relative_to(ROOT))}
    (ROOT/'placement_A3.json').write_text(json.dumps(layout,indent=2)+'\n',encoding='utf-8')
    print('Saved placement A3: 110 x 58 mm; USB mouth nominally at x=160 mm; power parts beside ESP 5V input.')
    print('No routing, fill, ERC, DRC, connectivity comparison or firmware build performed.')


if __name__=='__main__': main()
