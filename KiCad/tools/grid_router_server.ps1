$ErrorActionPreference = 'Stop'
Add-Type -Path (Join-Path $PSScriptRoot 'grid_router.cs')
[Console]::WriteLine('READY')
while ($null -ne ($requestLine = [Console]::ReadLine())) {
    if ($requestLine -eq 'QUIT') { break }
    $request = $requestLine | ConvertFrom-Json
    $mask = [Convert]::FromBase64String([Console]::ReadLine())
    $heat = [Convert]::FromBase64String([Console]::ReadLine())
    if ($request.mode -eq 'layers') {
        $result = [GridRouter]::SolveLayers($mask, $heat, [int]$request.w, [int]$request.h, [int]$request.start, [int[]]$request.ends, [int]$request.preferred)
    } else {
        $result = [GridRouter]::Solve($mask, $heat, [int]$request.w, [int]$request.h, [int]$request.start, [int[]]$request.ends)
    }
    [Console]::WriteLine(($result -join ','))
}
