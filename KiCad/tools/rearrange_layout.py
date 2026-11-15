"""Placement iteration A2 only: preserve nets, remove obsolete routing, no ERC/DRC."""
from pathlib import Path
import hashlib
import json
import zipfile
import pcbnew as p
from generate_board import ROOT, PROJECT, xy, text

TOP = {'M1':(70,54,0),'M2':(83,103,0),'M3':(120,115,90),'M4':(110,110,180)}
BACK = {
    'J1':(53,76,90),'F1':(61.5,72.5,90),'D1':(62.5,78,90),'U1':(69,76,0),
    'R1':(60,82,0),'R2':(60,85.5,0),'R3':(77.5,64,90),'R4':(77.5,69,90),
    'R5':(106.7,104,0),'R6':(69,80,0),'U3':(83,65,0),'U2':(91.5,104,0),
    'C1':(65.5,73,90),'C2':(72.5,73,90),'C3':(75,77,90),
    'C4':(69,63,90),'C5':(73,63,90),'C6':(87.5,64,90),'C7':(83,69.5,0),
    'C8':(91.5,108.5,0),'C9':(91.5,99.5,0),'C10':(79,104,90),
    'C11':(125,112,0),'C12':(125,116,0),'C13':(111,114,90),'C14':(115,114,90),
    'TP1':(56,87,0),'TP2':(77.5,82,0),'TP3':(66,69,0),'TP4':(128,64,0),
    'TP5':(91,65,0),'TP6':(96,72,0),'TP7':(103,72,0),'TP8':(88,113,0),'TP9':(94,113,0),
}


def main():
    board_path=ROOT/(PROJECT+'.kicad_pcb')
    original_hash=hashlib.sha256(board_path.read_bytes()).hexdigest()
    backup=ROOT/'revisions'/'A1_before_placement_A2.zip'
    backup.parent.mkdir(exist_ok=True)
    if not backup.exists():
        files=[ROOT/(PROJECT+ext) for ext in ('.kicad_pro','.kicad_sch','.kicad_pcb')]
        files += [ROOT/name for name in ('modules.kicad_sch','EDL.kicad_sym','fp-lib-table','sym-lib-table','design_manifest.json')]
        files += list((ROOT/'EDL.pretty').glob('*.kicad_mod'))
        files += [ROOT/'reports'/name for name in ('erc.json','drc.json','schematic.net.xml','verification.json')]
        with zipfile.ZipFile(backup,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                if path.exists():
                    archive.write(path,path.relative_to(ROOT))
    b=p.LoadBoard(str(board_path))
    # Moved parts invalidate the old routes. Retain the routed revision in the ZIP.
    tracks=b.GetTracks()
    for track in tracks:
        b.Remove(track)
        track.thisown=True
    zones=list(b.Zones())
    for z in zones:
        if not z.GetIsRuleArea():
            z.UnFill()
    fps={f.GetReference():f for f in b.GetFootprints()}
    for ref,(x,y,angle) in {**TOP,**BACK}.items():
        f=fps[ref]
        bottom=ref in BACK
        if (f.GetLayer()==p.B_Cu)!=bottom:
            f.Flip(f.GetPosition(),p.FLIP_DIRECTION_LEFT_RIGHT)
        f.SetPosition(xy(x,y)); f.SetOrientationDegrees(angle)
        f.Reference().SetLayer(p.B_SilkS if bottom else p.F_SilkS)
        f.Reference().SetMirrored(bottom)
        f.Reference().SetTextAngle(p.EDA_ANGLE(0,p.DEGREES_T))
        f.Reference().SetPosition(xy(x,y-2.6))
    for ref,x,y in [('M1',103,60),('M2',70,130),('M3',132,129),('M4',103,125),('R6',69,82.5),('R2',64,85.5),('C7',87,69.5)]:
        fps[ref].Reference().SetPosition(xy(x,y))
    labels={
        'USB 5V IN':(62,67,p.F_SilkS),'RTC / CR2032':(69,92.5,p.F_SilkS),
        'DISABLE RTC CHARGE':(69,94.7,p.F_SilkS),'OLED 3V3':(132,94,p.F_SilkS),
        'BME280 / SPI':(103,105,p.F_SilkS),'VIN ADC':(84,74,p.B_SilkS),
        'VBUS':(56,89,p.B_SilkS),'5V':(77.5,84,p.B_SilkS),'3V3':(66,71,p.B_SilkS),
        'GND':(128,66,p.B_SilkS),'ADC':(91,67,p.B_SilkS),'SDA':(96,74,p.B_SilkS),
        'SCL':(103,74,p.B_SilkS),'SDA5':(88,115,p.B_SilkS),'SCL5':(94,115,p.B_SilkS),
    }
    for t in b.GetDrawings():
        if not isinstance(t,p.PCB_TEXT):
            continue
        s=t.GetText()
        if s in labels:
            x,y,layer=labels[s]; t.SetPosition(xy(x,y)); t.SetLayer(layer); t.SetMirrored(layer==p.B_SilkS)
        elif s=='REV A1 / 2 LAYERS':
            t.SetText('A2 PLACEMENT DRAFT'); t.SetPosition(xy(130,132))
    if not any(isinstance(t,p.PCB_TEXT) and t.GetText()=='SMD ON BACK' for t in b.GetDrawings()):
        text(b,'SMD ON BACK',104,86,1,p.F_SilkS)
    title=b.GetTitleBlock(); title.SetRevision('A2 placement draft'); b.SetTitleBlock(title)
    assert hashlib.sha256(board_path.read_bytes()).hexdigest()==original_hash, 'PCB changed on disk during edit; not overwriting'
    p.SaveBoard(str(board_path),b)
    layout={'status':'placement draft, unrouted, no full checks','routing_policy':{'F.Cu':'signals primarily','B.Cu':'power primarily; preserve connected GND plane'},'power_topology':'unchanged: +5V_SYS feeds M1 regulator; M1 provides +3V3_ESP','top':TOP,'bottom':BACK,'previous_routed_board':str(backup.relative_to(ROOT))}
    (ROOT/'placement_A2.json').write_text(json.dumps(layout,indent=2)+'\n',encoding='utf-8')
    print('Saved A2 placement:',len(TOP),'top modules;',len(BACK),'bottom footprints.')
    print('Previous routing retained in',backup.name)
    print('No routing, zone refill, ERC or DRC performed.')


if __name__=='__main__':
    main()
