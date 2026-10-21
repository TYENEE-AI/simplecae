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
    if (-not (Test-Path -LiteralPath $ViewerResult)) {
        if (Test-Path -LiteralPath $ViewerExample) { throw 'The first Viewer example is incomplete. Retain it for diagnosis and choose a fresh quickstart output.' }
        Write-Host 'Preparing the first STEP reference (3 mesh levels). This is a mathematical example, not a product rating.'
        & $ToolkitPython (Join-Path $PSScriptRoot 'simplecae_cli.py') quickstart --out $ViewerExample
        if ($LASTEXITCODE -ne 0) { throw 'First example failed; inspect the retained output and bootstrap environment.' }
    }
    & $ToolkitPython (Join-Path $PSScriptRoot 'simplecae_cli.py') view $ViewerResult --out $Session
    if ($LASTEXITCODE -ne 0) { throw 'Viewer session creation failed.' }
}
& $ToolkitPython (Join-Path $PSScriptRoot 'simplecae_cli.py') view --session $Session --serve --open --port $Port
exit $LASTEXITCODE
