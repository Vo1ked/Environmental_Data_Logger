"""Place the EDL carrier with KiCad's own pcbnew API and export local routing input."""
from pathlib import Path
import json
import sys
import shutil
import pcbnew as p
from generate_design import ROOT, KICAD, PROJECT, ROOT_UUID, uid, parse, dump, child, children, Q


def xy(x,y):
    return p.VECTOR2I(p.FromMM(x),p.FromMM(y))


PLACEMENT = {
    'M1':(70,54,0),'M2':(88,81,0),'M3':(122,86,0),'M4':(94,129,0),
    'J1':(53,119,270),'F1':(61.5,115.5,90),'D1':(62.5,121,90),'U1':(69,119,0),
    'R1':(60,124,0),'R2':(60,127.5,0),'R3':(77.5,64,90),'R4':(77.5,69,90),
    'R5':(106,111,0),'R6':(69,123,0),
    'U3':(83,65,0),'U2':(99,91,0),
    'C1':(65.5,116,90),'C2':(72.5,116,90),'C3':(75,120,90),
    'C4':(69,63,90),'C5':(73,63,90),'C6':(87.5,64,90),'C7':(83,69.5,0),
    'C8':(97,97,90),'C9':(102,97,90),'C10':(94.5,80,90),
    'C11':(123,76,90),'C12':(133,76,90),'C13':(93,134,0),'C14':(98,134,0),
    'TP1':(56,110,0),'TP2':(82,119,0),'TP3':(67,69,0),'TP4':(127,64,0),
    'TP5':(90,64,0),'TP6':(98,70,0),'TP7':(104,70,0),'TP8':(95,85,0),'TP9':(99,81,0),
}


def text(board, string, x,y,size=1,layer=p.F_SilkS):
    size=max(size,.8)
    t=p.PCB_TEXT(board); t.SetText(string); t.SetPosition(xy(x,y)); t.SetLayer(layer)
    t.SetTextSize(xy(size,size)); t.SetTextThickness(p.FromMM(.15)); board.Add(t)
    return t


def line(board,a,b,layer=p.Edge_Cuts,width=.05):
    s=p.PCB_SHAPE(board); s.SetShape(p.SHAPE_T_SEGMENT); s.SetStart(xy(*a)); s.SetEnd(xy(*b)); s.SetLayer(layer); s.SetWidth(p.FromMM(width)); board.Add(s)


def zone(board,net,layer,points,keepout=False):
    z=p.ZONE(board); z.SetLayer(layer); z.SetNetCode(net.GetNetCode() if net else 0)
    if keepout:
        z.SetIsRuleArea(True); z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowPads(False); z.SetDoNotAllowZoneFills(True); z.SetDoNotAllowFootprints(False)
    else:
        z.SetLocalClearance(p.FromMM(.25)); z.SetThermalReliefGap(p.FromMM(.25)); z.SetThermalReliefSpokeWidth(p.FromMM(.3)); z.SetPadConnection(p.ZONE_CONNECTION_THERMAL); z.SetMinThickness(p.FromMM(.2))
    z.Outline().NewOutline()
    for x,y in points:
        z.Outline().Append(int(p.FromMM(x)),int(p.FromMM(y)))
    board.Add(z)
    return z


def update_project():
    path=ROOT/(PROJECT+'.kicad_pro')
    data=json.loads(path.read_text(encoding='utf-8'))
    default=data['net_settings']['classes'][0]
    default.update(clearance=.2,track_width=.25,via_diameter=.6,via_drill=.3)
    power=dict(default); power.update(name='Power',track_width=.6)
    data['net_settings']['classes']=[default,power]
    data['net_settings']['netclass_patterns']=[{'netclass':'Power','pattern':name} for name in ['+5V_USB','+5V_FUSED','+5V_SYS','+3V3_ESP','GND']]
    settings=data['board'].setdefault('design_settings',{})
    settings.setdefault('rules',{}).update(min_clearance=.2,min_track_width=.2,min_via_diameter=.6,min_through_hole_diameter=.3,min_copper_edge_clearance=.3,min_hole_to_hole=.25)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    update_project()
    manifest=json.loads((ROOT/'design_manifest.json').read_text(encoding='utf-8'))
    board=p.BOARD(); board.SetFileName(str(ROOT/(PROJECT+'.kicad_pcb'))); board.SetCopperLayerCount(2)
    board.GetDesignSettings().SetCopperLayerCount(2)
    board.GetDesignSettings().m_BoardThickness=p.FromMM(1.6)
    dc=board.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
    dc.SetClearance(p.FromMM(.2)); dc.SetTrackWidth(p.FromMM(.25)); dc.SetViaDiameter(p.FromMM(.6)); dc.SetViaDrill(p.FromMM(.3))
    nets={}
    for name in sorted({n for c in manifest for n in c['nets'].values()}):
        net=p.NETINFO_ITEM(board,name); board.Add(net); nets[name]=net
    fps={}
    for c in manifest:
        if c['ref'].startswith('#'):
            continue
        name=c['footprint'].split(':',1)[1]
        fp=p.FootprintLoad(str(ROOT/'EDL.pretty'),name)
        assert fp, c['ref']
        fp.SetReference(c['ref']); fp.SetValue(c['value']); fp.SetFPID(p.LIB_ID('EDL',name))
        path='/'+ROOT_UUID + (('/'+uid('sheet:modules')) if c['sheet']=='modules.kicad_sch' else '') + '/'+c['uuid']
        fp.SetPath(p.KIID_PATH(path))
        fp.SetSheetfile(c['sheet'])
        board.Add(fp)
        x,y,a=PLACEMENT[c['ref']]; fp.SetPosition(xy(x,y)); fp.SetOrientationDegrees(a)
        fp.Reference().SetTextSize(xy(.9,.9)); fp.Reference().SetTextThickness(p.FromMM(.12)); fp.Reference().SetTextAngle(p.EDA_ANGLE(0,p.DEGREES_T)); fp.Reference().SetPosition(xy(x,y-2.6))
        fp.Value().SetVisible(False)
        for pad in fp.Pads():
            name=c['nets'].get(pad.GetNumber())
            if name:
                pad.SetNet(nets[name])
        fps[c['ref']]=fp
    # Board-only mechanical holes: these are carrier holes, not guessed module holes.
    hole_name='MountingHole_3.2mm_M3'
    shutil.copyfile(KICAD/'footprints'/'MountingHole.pretty'/(hole_name+'.kicad_mod'),ROOT/'EDL.pretty'/(hole_name+'.kicad_mod'))
    for index,(x,y) in enumerate([(54,61),(146,61),(54,134),(146,134)],1):
        f=p.FootprintLoad(str(ROOT/'EDL.pretty'),hole_name); f.SetReference('H'+str(index)); f.SetValue('M3 carrier mounting'); f.SetFPID(p.LIB_ID('EDL',hole_name))
        f.SetAttributes(p.FP_BOARD_ONLY | p.FP_EXCLUDE_FROM_BOM | p.FP_EXCLUDE_FROM_POS_FILES); board.Add(f); f.SetPosition(xy(x,y)); f.Reference().SetVisible(False); f.Value().SetVisible(False)
    outline=[(50,50),(150,50),(150,138),(50,138),(50,50)]
    for a,b in zip(outline,outline[1:]): line(board,a,b)
    # Keep copper away from the overhanging module antenna at the upper left.
    for layer in [p.F_Cu,p.B_Cu]:
        zone(board,None,layer,[(50.5,50.5),(68.5,50.5),(68.5,60),(50.5,60)],True)
    # Labels placed in free board areas; module envelopes remain on fabrication layer.
    text(board,'ENVIRONMENTAL DATA LOGGER',101,135.5,1.2)
    text(board,'REV A1 / 2 LAYERS',130,132,.8)
    text(board,'ESP: IN-OUT + USB-OTG OPEN',104,61,.8)
    text(board,'ANTENNA',57.5,56,.75)
    text(board,'USB 5V IN',61,130.5,.9)
    text(board,'RTC / CR2032',74,109.5,.9)
    text(board,'DISABLE RTC CHARGE',74,111.5,.7)
    text(board,'OLED 3V3',125,117,.9)
    text(board,'BME280 / SPI',101,114,.9)
    text(board,'VIN ADC',86,74,.8)
    for ref,label in [('TP1','VBUS'),('TP2','5V'),('TP3','3V3'),('TP4','GND'),('TP5','ADC'),('TP6','SDA'),('TP7','SCL'),('TP8','SDA5'),('TP9','SCL5')]:
        x,y,_=PLACEMENT[ref]; fps[ref].Reference().SetVisible(False); text(board,label,x,y+1.8,.75)
    for ref,x,y in [('R6',69,125.3),('R2',63.8,127.5),('C7',86.8,69.5)]:
        fps[ref].Reference().SetPosition(xy(x,y))
    board.BuildConnectivity()
    p.SaveBoard(str(ROOT/(PROJECT+'.kicad_pcb')),board)
    assert p.ExportSpecctraDSN(board,str(ROOT/'reports'/'unrouted.dsn'))
    prepare_dsn(ROOT/'reports'/'unrouted.dsn')
    print('Placed',len(fps),'electrical parts + four carrier holes on 100 x 88 mm PCB.')
    print('Exported reports/unrouted.dsn')


def prepare_dsn(dsn_path):
    # DSN power class and routing preferences are explicit, independent of global prefs.
    dsn=parse(dsn_path.read_text(encoding='utf-8').replace('(string_quote ")','(string_quote quote)'))
    # The native 2.5.0 CLI has a serialization bug for visual ComponentOutline.
    # Omit only non-copper component drawings from the routing interchange file.
    # Pads, board boundary and all copper keepouts stay intact; PCB is unchanged.
    library=child(dsn,'library')
    for image in children(library,'image'):
        image[:]=[v for v in image if not (isinstance(v,list) and v and v[0]=='outline')]
    # The same native build also cannot serialize ObstacleArea. Represent routing
    # obstacles as unconnected dummy pad shapes with identical geometry/layers.
    # This is conservative (pad clearance is added); never remove a copper keepout.
    # These dummy pins are ONLY in DSN, and are not added to the fabrication board.
    keepout_id=0
    structure=child(dsn,'structure')
    board_obstacles=['image',Q('__EDL_ROUTING_OBSTACLES')]
    for parent in [structure,*children(library,'image')]:
        for ko in list(children(parent,'keepout')):
            keepout_id+=1
            shape=next(v for v in ko if isinstance(v,list))
            stackname=Q('__EDL_KO_'+str(keepout_id))
            library.append(['padstack',stackname,['shape',shape],['attach','off']])
            pin=['pin',stackname,Q('__KO'+str(keepout_id)),0,0]
            (board_obstacles if parent is structure else parent).append(pin)
            parent.remove(ko)
    library.append(board_obstacles)
    child(dsn,'placement').append(['component',Q('__EDL_ROUTING_OBSTACLES'),['place',Q('__EDL_KO'),0,0,'front',0]])
    network=child(dsn,'network')
    power_names={'+5V_USB','+5V_FUSED','+5V_SYS','+3V3_ESP','GND'}
    for cl in children(network,'class'):
        cl[:]=[v for i,v in enumerate(cl) if i<2 or isinstance(v,list) or str(v) not in power_names]
    network.append(['class',Q('Power'),*[Q(v) for v in sorted(power_names)],['circuit',['use_via',Q('Via[0-1]_600:300_um')]],['rule',['width',600],['clearance',200]]])
    # Use the actual via definition emitted by KiCad, not an assumed padstack identifier.
    default_class=children(network,'class')[0]
    circuit=child(default_class,'circuit')
    if circuit:
        child(children(network,'class')[-1],'circuit')[:]=json.loads(json.dumps(circuit))
        for index,v in enumerate(child(children(network,'class')[-1],'circuit')):
            if isinstance(v,list):
                v[1:]=[Q(s) if isinstance(s,str) else s for s in v[1:]]
    structure=child(dsn,'structure')
    ar=child(structure,'autoroute_settings')
    if ar:
        for lr in children(ar,'layer_rule'):
            if str(lr[1])=='B.Cu':
                for key in ['preferred_direction_trace_costs','against_preferred_direction_trace_costs']:
                    v=child(lr,key)
                    if v: v[1]=4
    dsn_path.write_text(dump(dsn).replace('(string_quote quote)','(string_quote ")')+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
