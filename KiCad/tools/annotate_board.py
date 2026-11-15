"""Add fabrication fit-check information without modifying electrical connections."""
import pcbnew as p
from generate_board import ROOT, PROJECT, xy, text, line

b=p.LoadBoard(str(ROOT/(PROJECT+'.kicad_pcb')))
for z in b.Zones():
    if z.GetIsRuleArea():
        z.Outline().Clear(); z.Outline().NewOutline()
        for x,y in [(50.5,50.5),(68.5,50.5),(68.5,60),(50.5,60)]:
            z.Outline().Append(p.FromMM(x),p.FromMM(y))
if not any(isinstance(t,p.PCB_TEXT) and t.GetText()=='100 mm - PRINT AT 100%' for t in b.GetDrawings()):
    line(b,(50,143),(150,143),p.Dwgs_User,.15)
    line(b,(50,141),(50,145),p.Dwgs_User,.15)
    line(b,(150,141),(150,145),p.Dwgs_User,.15)
    text(b,'100 mm - PRINT AT 100%',100,146,1.2,p.Dwgs_User)
    text(b,'PROVISIONAL MODULE OUTLINES - VERIFY REAL PARTS',100,149,1,p.Dwgs_User)
title=p.TITLE_BLOCK(); title.SetTitle('Environmental Data Logger - module carrier'); title.SetDate('2026-11-15'); title.SetRevision('A1'); title.SetCompany('Prototype / verify module fit'); b.SetTitleBlock(title)
b.BuildConnectivity(); p.ZONE_FILLER(b).Fill(b.Zones()); p.SaveBoard(str(ROOT/(PROJECT+'.kicad_pcb')),b)
