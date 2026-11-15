"""Reviewed power routes and narrow escape from the TCA9406 supply pin."""
import pcbnew as p
from generate_board import ROOT, PROJECT, xy

b=p.LoadBoard(str(ROOT/(PROJECT+'.kicad_pcb')))
net=b.FindNet('+5V_SYS')

def track(points,layer,width):
    for a,c in zip(points,points[1:]):
        if any(not isinstance(t,p.PCB_VIA) and t.GetStart()==xy(*a) and t.GetEnd()==xy(*c) and t.GetLayer()==layer for t in b.GetTracks()):
            continue
        t=p.PCB_TRACK(b); t.SetStart(xy(*a)); t.SetEnd(xy(*c)); t.SetWidth(p.FromMM(width)); t.SetLayer(layer); t.SetNet(net); b.Add(t)

def via(x,y):
    if any(isinstance(t,p.PCB_VIA) and t.GetPosition()==xy(x,y) for t in b.GetTracks()):
        return
    v=p.PCB_VIA(b); v.SetPosition(xy(x,y)); v.SetWidth(p.FromMM(.6)); v.SetDrill(p.FromMM(.3)); v.SetViaType(p.VIATYPE_THROUGH); v.SetLayerPair(p.F_Cu,p.B_Cu); v.SetNet(net); b.Add(v)

# Main ESP supply: a wide top-layer route below the module header.
track([(120.8,54),(120.8,56.5),(119.3,58),(76.5582,58)],p.F_Cu,.6)
via(76.5582,58)
track([(76.5582,58),(76.5582,65.8543)],p.B_Cu,.6)
# A 0.25 mm escape is necessary between the 0.65 mm-pitch SSOP pins.
track([(100.7,90.675),(102.6,90.675)],p.F_Cu,.25)
via(102.6,90.675)
track([(102.6,90.675),(102.6,96.5292),(100.7192,98.41)],p.B_Cu,.6)
b.BuildConnectivity()
p.ZONE_FILLER(b).Fill(b.Zones())
p.SaveBoard(str(ROOT/(PROJECT+'.kicad_pcb')),b)
print('Completed ESP +5V and TCA9406 VCCB routes.')
