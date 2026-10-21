param([string]$Python = 'python', [string]$Ccx = '')
$ErrorActionPreference = 'Stop'
$simplecaeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$simplecaeVenv = Join-Path $simplecaeRoot '.venv'
& $Python -c "import sys,struct; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8, 'Use 64-bit Python 3.11 or newer; pass -Python PATH'"
if ($LASTEXITCODE -ne 0) { throw 'A working 64-bit Python 3.11+ is required. Supply its path with -Python PATH.' }
if (-not (Test-Path -LiteralPath (Join-Path $simplecaeVenv 'Scripts\python.exe'))) {
    & $Python -m venv $simplecaeVenv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
$simplecaePython = Join-Path $simplecaeVenv 'Scripts\python.exe'
& $simplecaePython -m pip install --no-cache-dir -r (Join-Path $simplecaeRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed' }
& $simplecaePython -m pip install --no-cache-dir --no-deps -e "${simplecaeRoot}[test]"
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
if ($Ccx) {
    $simplecaeCcx = (Resolve-Path -LiteralPath $Ccx).Path
} else {
    $simplecaeTools = Join-Path $simplecaeRoot '.tools'
    New-Item -ItemType Directory -Force -Path $simplecaeTools | Out-Null
    $simplecaeUrl = 'https://raw.githubusercontent.com/calculix/CalculiX-Windows/60c9a10b350ec813f4d493098f47f7a8b96cd276/releases/CalculiX-2.23.0-win-x64.zip'
    $simplecaeHash = '79a674fdee735a22720bbd12bb9ccbadad1e8c8ad5b1de74e1c62f8808b2d395'
    $simplecaeArchive = Join-Path $simplecaeTools 'CalculiX-2.23.0-win-x64.zip'
    if (-not (Test-Path -LiteralPath $simplecaeArchive)) {
        Invoke-WebRequest -Uri $simplecaeUrl -OutFile $simplecaeArchive
    }
    if ((Get-FileHash -LiteralPath $simplecaeArchive -Algorithm SHA256).Hash.ToLower() -ne $simplecaeHash) {
        throw 'CalculiX archive SHA-256 mismatch; refusing to extract or execute'
    }
    $simplecaeDestination = [IO.Path]::GetFullPath((Join-Path $simplecaeTools 'calculix-2.23'))
    if (-not $simplecaeDestination.StartsWith($simplecaeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Extraction destination is outside the skill directory'
    }
    $simplecaeCcx = Join-Path $simplecaeDestination 'CalculiX-2.23.0-win-x64\bin\ccx.exe'
    if (-not (Test-Path -LiteralPath $simplecaeCcx)) {
        Expand-Archive -LiteralPath $simplecaeArchive -DestinationPath $simplecaeDestination
    }
    [ordered]@{version='2.23'; source_url=$simplecaeUrl; repository_commit='60c9a10b350ec813f4d493098f47f7a8b96cd276'; archive_sha256=$simplecaeHash} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $simplecaeTools 'calculix-provenance.json') -Encoding utf8
}
& $simplecaePython (Join-Path $PSScriptRoot 'simplecae_cli.py') doctor --ccx $simplecaeCcx
if ($LASTEXITCODE -ne 0) { throw 'Runtime check failed' }
$simplecaeTools = Join-Path $simplecaeRoot '.tools'
New-Item -ItemType Directory -Force -Path $simplecaeTools | Out-Null
& $simplecaePython -c "import json,sys; from pathlib import Path; p=Path(sys.argv[1]); data=json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {}; data.setdefault('ccx_by_platform',{})['Windows']=sys.argv[2]; p.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')" (Join-Path $simplecaeTools 'runtime.json') $simplecaeCcx
if ($LASTEXITCODE -ne 0) { throw 'Runtime configuration update failed' }
Write-Host 'Ready. First STEP example (run from the skill folder):'
Write-Host '.\.venv\Scripts\python.exe scripts/simplecae_cli.py quickstart --out outputs/first-001'
