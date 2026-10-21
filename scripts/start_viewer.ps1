param(
    [string]$Session = 'outputs/viewer-demo',
    [int]$Port = 0
)
$ErrorActionPreference = 'Stop'
$ToolkitRoot = Split-Path -Parent $PSScriptRoot
$ToolkitPython = Join-Path $ToolkitRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $ToolkitPython)) { throw 'Run scripts/bootstrap.ps1 first to create the local Python environment.' }
if (-not [IO.Path]::IsPathRooted($Session)) { $Session = Join-Path $ToolkitRoot $Session }
if (-not (Test-Path -LiteralPath (Join-Path $Session 'viewer.json'))) {
    if ($PSBoundParameters.ContainsKey('Session')) { throw "Viewer session not found: $Session. Create one with: simplecae view RESULT.json --out SESSION" }
    $ViewerExample = Join-Path $ToolkitRoot 'outputs/first-001'
    $ViewerResult = Join-Path $ViewerExample 'pass/result.json'
    # Opening a review surface must not implicitly start a solver or overwrite an incomplete run.
    if (Test-Path -LiteralPath $Session) { $Session = $Session + '-' + [guid]::NewGuid().ToString('N').Substring(0,8) }
    if (Test-Path -LiteralPath $ViewerResult) {
        & $ToolkitPython (Join-Path $PSScriptRoot 'simplecae_cli.py') view $ViewerResult --out $Session
    } else {
        Write-Host 'Opening an empty review session. Add an analysis result when ready; no solver is started.'
        & $ToolkitPython (Join-Path $PSScriptRoot 'simplecae_cli.py') view --out $Session
    }
    if ($LASTEXITCODE -ne 0) { throw 'Viewer session creation failed.' }
}
& $ToolkitPython (Join-Path $PSScriptRoot 'simplecae_cli.py') view --session $Session --serve --open --port $Port
exit $LASTEXITCODE
