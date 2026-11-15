"""Export remaining routes for a fresh, single-pass local router invocation."""
import pcbnew as p
from generate_board import ROOT, PROJECT, prepare_dsn

b=p.LoadBoard(str(ROOT/(PROJECT+'.kicad_pcb')))
zones=list(b.Zones())
for z in zones:
    if not z.GetIsRuleArea():
        b.Remove(z)
for t in b.GetTracks():
    if not isinstance(t,p.PCB_VIA) and t.GetWidth()<p.FromMM(.2):
        t.SetWidth(p.FromMM(.2))
for f in b.GetFootprints():
    if f.GetReference() in ('U1','J1'):
        for pad in f.Pads():
            if pad.GetNetname()=='GND':
                pad.SetLocalZoneConnection(p.ZONE_CONNECTION_FULL)
p.SaveBoard(str(ROOT/(PROJECT+'.kicad_pcb')),b)
assert p.ExportSpecctraDSN(b,str(ROOT/'reports'/'continue.dsn'))
prepare_dsn(ROOT/'reports'/'continue.dsn')
