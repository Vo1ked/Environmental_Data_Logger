"""Compare independently exported schematic XML connectivity with PCB pads."""
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
import pcbnew as p
from generate_design import ROOT, PROJECT

tree=ET.parse(ROOT/'reports'/'schematic.net.xml')
schematic=set()
for net in tree.findall('./nets/net'):
    nodes=frozenset((n.attrib['ref'],n.attrib['pin']) for n in net.findall('node') if not n.attrib['ref'].startswith('#'))
    if len(nodes)>1:
        schematic.add(nodes)
b=p.LoadBoard(str(ROOT/(PROJECT+'.kicad_pcb')))
groups=defaultdict(set)
for f in b.GetFootprints():
    for pad in f.Pads():
        if pad.GetNetCode()>0:
            groups[pad.GetNetCode()].add((f.GetReference(),pad.GetNumber()))
pcb={frozenset(nodes) for nodes in groups.values() if len(nodes)>1}
assert schematic==pcb, {'missing_from_pcb':[sorted(n) for n in schematic-pcb], 'extra_on_pcb':[sorted(n) for n in pcb-schematic]}
erc=json.loads((ROOT/'reports'/'erc.json').read_text(encoding='utf-8'))
drc=json.loads((ROOT/'reports'/'drc.json').read_text(encoding='utf-8'))
assert not drc['violations'] and not drc['unconnected_items'], 'DRC not clean'
assert not any(s.get('violations') for s in erc.get('sheets',[])), 'ERC not clean'
out={'kicad_version':p.GetBuildVersion(),'schematic_pcb_connected_net_groups_match':len(pcb),'electrical_footprints':sum(not f.GetReference().startswith('H') for f in b.GetFootprints()),'mounting_holes':4,'tracks':sum(not isinstance(t,p.PCB_VIA) for t in b.GetTracks()),'vias':sum(isinstance(t,p.PCB_VIA) for t in b.GetTracks()),'erc_violations':0,'drc_violations':0,'unconnected_items':0,'hardware_tested':False,'mechanical_fit_confirmed':False,'firmware_built':False}
(ROOT/'reports'/'verification.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out))
