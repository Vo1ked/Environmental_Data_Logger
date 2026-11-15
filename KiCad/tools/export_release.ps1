$ErrorActionPreference = 'Stop'
$edlRoot = Split-Path -Parent $PSScriptRoot
$edlCli = 'E:\Embedded\KiCad\bin\kicad-cli.exe'
$edlBoard = Join-Path $edlRoot 'Environmental_Data_Logger.kicad_pcb'
$edlSchematic = Join-Path $edlRoot 'Environmental_Data_Logger.kicad_sch'
$edlExports = Join-Path $edlRoot 'exports'
$edlReports = Join-Path $edlRoot 'reports'
$edlFabrication = Join-Path $edlExports 'fabrication_draft'
New-Item -ItemType Directory -Force -Path $edlFabrication | Out-Null
function Invoke-EdlKiCad {
    & $edlCli @args
    if ($LASTEXITCODE -ne 0) { throw "KiCad command failed: $args" }
}
Invoke-EdlKiCad sch erc --format json --severity-all --exit-code-violations -o (Join-Path $edlReports 'erc.json') $edlSchematic
Invoke-EdlKiCad pcb drc --format json --severity-all --exit-code-violations -o (Join-Path $edlReports 'drc.json') $edlBoard
Invoke-EdlKiCad sch export netlist --format kicadxml -o (Join-Path $edlReports 'schematic.net.xml') $edlSchematic
Invoke-EdlKiCad sch export pdf --no-background-color -o (Join-Path $edlExports 'schematic.pdf') $edlSchematic
Invoke-EdlKiCad pcb export pdf --mode-single --layers 'F.Fab,F.SilkS,Edge.Cuts,Dwgs.User' --sketch-pads-on-fab-layers --black-and-white --scale 1 -o (Join-Path $edlExports 'assembly_1to1.pdf') $edlBoard
Invoke-EdlKiCad pcb export pdf --mode-multipage --layers 'F.Cu,B.Cu' --common-layers 'Edge.Cuts' --scale 1 -o (Join-Path $edlExports 'copper_layers.pdf') $edlBoard
Invoke-EdlKiCad pcb export gerbers --layers 'F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,F.Paste,Edge.Cuts' --subtract-soldermask -o $edlFabrication $edlBoard
Invoke-EdlKiCad pcb export drill --format excellon --drill-origin absolute --excellon-units mm --excellon-separate-th --generate-map --generate-report --report-path (Join-Path $edlReports 'drill_report.txt') -o $edlFabrication $edlBoard
Invoke-EdlKiCad pcb render --width 1600 --height 1200 --side top --background opaque --quality high --zoom 1.15 -o (Join-Path $edlExports 'pcb_top.png') $edlBoard
& 'E:\Embedded\KiCad\bin\python.exe' (Join-Path $PSScriptRoot 'verify_connectivity.py')
if ($LASTEXITCODE -ne 0) { throw 'Schematic-to-PCB connectivity comparison failed' }
