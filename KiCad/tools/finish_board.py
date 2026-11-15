"""Import locally routed tracks, add ground planes and save the editable board."""
from pathlib import Path
import sys
import pcbnew as p
from generate_board import ROOT, PROJECT, zone
from generate_design import parse, dump, child


def main():
    path=ROOT/(PROJECT+'.kicad_pcb')
    board=p.LoadBoard(str(path))
    session=parse((ROOT/'reports'/(sys.argv[1] if len(sys.argv)>1 else 'routed.ses')).read_text(encoding='utf-8'))
    placement=child(session,'placement')
    placement[:]=[v for v in placement if not (isinstance(v,list) and v[0]=='component' and str(v[1])=='__EDL_ROUTING_OBSTACLES')]
    clean=ROOT/'reports'/'routed_kicad.ses'
    clean.write_text(dump(session)+'\n',encoding='utf-8')
    assert p.ImportSpecctraSES(board,str(clean))
    for t in board.GetTracks():
        if not isinstance(t,p.PCB_VIA) and t.GetWidth()<p.FromMM(.2):
            t.SetWidth(p.FromMM(.2))
    for item in board.GetDrawings():
        if isinstance(item,p.PCB_TEXT) and item.GetText()=='ENVIRONMENTAL DATA LOGGER':
            item.SetPosition(p.VECTOR2I(p.FromMM(101),p.FromMM(136)))
    ground=board.FindNet('GND')
    for layer in (p.F_Cu,p.B_Cu):
        zone(board,ground,layer,[(50.5,50.5),(149.5,50.5),(149.5,137.5),(50.5,137.5)])
    board.BuildConnectivity()
    p.ZONE_FILLER(board).Fill(board.Zones())
    p.SaveBoard(str(path),board)
    print('Tracks/vias:',len(list(board.GetTracks())))
    print('Added front and back GND pours; antenna keepout retained.')


if __name__=='__main__':
    main()
