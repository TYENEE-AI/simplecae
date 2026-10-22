param([string]$Python = 'python', [string]$Ccx = '', [switch]$Locked,
      [ValidateRange(1,2147483647)][int]$DownloadTimeoutSeconds = 3000)
$ErrorActionPreference = 'Stop'
$simplecaeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$simplecaeVenv = Join-Path $simplecaeRoot '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $simplecaeVenv 'Scripts\python.exe'))) {
    & $Python -c "import sys,struct,venv,ensurepip; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8"
    if ($LASTEXITCODE -ne 0) { throw 'Use a full 64-bit Python 3.11+ with venv and ensurepip. Some Agent-bundled Pythons omit these. Pass -Python PATH to an existing full Python installation.' }
    & $Python -m venv $simplecaeVenv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
$simplecaePython = Join-Path $simplecaeVenv 'Scripts\python.exe'
& $simplecaePython (Join-Path $PSScriptRoot 'runtime_ready.py')
$simplecaeReadyCode = $LASTEXITCODE
if ($simplecaeReadyCode -notin @(0,1)) {
    throw 'Runtime inspection or native loading failed. Repair the reported shared libraries/runtime or configuration; Python packages were not reinstalled.'
}
$simplecaeRuntimeReady = $simplecaeReadyCode -eq 0
if ($Locked) {
    & $simplecaePython -m pip install --no-cache-dir -r (Join-Path $simplecaeRoot 'requirements-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed' }
    & $simplecaePython -m pip install --no-cache-dir --no-deps -e $simplecaeRoot
    if ($LASTEXITCODE -ne 0) { throw 'Python package installation failed' }
} elseif (-not $simplecaeRuntimeReady) {
    & $simplecaePython -m pip install --no-cache-dir -e $simplecaeRoot
    if ($LASTEXITCODE -ne 0) { throw 'Python runtime installation failed' }
} else { Write-Host 'Reusing the existing runtime; no dependency download needed.' }
if ($Locked -or -not $simplecaeRuntimeReady) {
    & $simplecaePython (Join-Path $PSScriptRoot 'runtime_ready.py')
    if ($LASTEXITCODE -ne 0) { throw 'Runtime still unavailable after Python setup; resolve the reported cause before retrying.' }
}
if (-not $Ccx) {
    # Reuse explicit environment/config/PATH discovery, including custom solvers.
    $simplecaeFindCode = @'
import sys
sys.path.insert(0,sys.argv[1])
from simplecae.solver import find_ccx
try:
    print(find_ccx())
except (FileNotFoundError, ValueError):
    sys.exit(1)
'@
    $simplecaeFound = & $simplecaePython -c $simplecaeFindCode (Join-Path $simplecaeRoot 'scripts')
    if ($LASTEXITCODE -eq 0) { $Ccx = [string]($simplecaeFound | Select-Object -Last 1) }
    else {
        $simplecaeConfigured = $env:SIMPLECAE_CCX
        $simplecaeConfigPath = Join-Path $simplecaeRoot '.tools/runtime.json'
        if (Test-Path -LiteralPath $simplecaeConfigPath) {
            $simplecaeSettings = Get-Content -Raw -LiteralPath $simplecaeConfigPath | ConvertFrom-Json
            $simplecaeConfigured = $simplecaeConfigured -or $simplecaeSettings.ccx_by_platform.Windows -or $simplecaeSettings.ccx
        }
        if ($simplecaeConfigured) {
            throw 'Configured solver unavailable. Supply -Ccx PATH or correct .tools/runtime.json; no alternate solver was silently selected.'
        }
    }
}
if ($Ccx) {
    $simplecaeCcx = (Resolve-Path -LiteralPath $Ccx).Path
} else {
    $simplecaeTools = Join-Path $simplecaeRoot '.tools'
    New-Item -ItemType Directory -Force -Path $simplecaeTools | Out-Null
    $simplecaeUrl = 'https://raw.githubusercontent.com/calculix/CalculiX-Windows/60c9a10b350ec813f4d493098f47f7a8b96cd276/releases/CalculiX-2.23.0-win-x64.zip'
    $simplecaeHash = '79a674fdee735a22720bbd12bb9ccbadad1e8c8ad5b1de74e1c62f8808b2d395'
    $simplecaeArchive = Join-Path $simplecaeTools 'CalculiX-2.23.0-win-x64.zip'
    if (-not (Test-Path -LiteralPath $simplecaeArchive)) {
        # A slow response can outlive an HTTP socket timeout. Bound the owned
        # download worker and publish the archive only after its pinned hash passes.
        & $simplecaePython (Join-Path $PSScriptRoot 'download_verified.py') $simplecaeUrl $simplecaeArchive $simplecaeHash --timeout $DownloadTimeoutSeconds
        if ($LASTEXITCODE -ne 0) { throw 'CalculiX download failed; its partial file was retained. Retry after addressing the reported network/timeout issue.' }
    }
    # Use the already verified Python runtime: Agent hosts may pass a PSModulePath
    # that omits Windows PowerShell's Get-FileHash/Expand-Archive modules.
    $simplecaeActualHash = & $simplecaePython -c "import hashlib,sys; f=open(sys.argv[1],'rb'); print(hashlib.file_digest(f,'sha256').hexdigest()); f.close()" $simplecaeArchive
    if ($LASTEXITCODE -ne 0) { throw 'CalculiX archive hashing failed' }
    if ([string]$simplecaeActualHash -ne $simplecaeHash) {
        throw 'CalculiX archive SHA-256 mismatch; refusing to extract or execute. Preserve and move this invalid archive aside before retrying.'
    }
    $simplecaeDestination = [IO.Path]::GetFullPath((Join-Path $simplecaeTools 'calculix-2.23'))
    if (-not $simplecaeDestination.StartsWith($simplecaeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Extraction destination is outside the skill directory'
    }
    $simplecaeCcx = Join-Path $simplecaeDestination 'CalculiX-2.23.0-win-x64\bin\ccx.exe'
    if (-not (Test-Path -LiteralPath $simplecaeCcx)) {
        & $simplecaePython -c "import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); z.extractall(sys.argv[2]); z.close()" $simplecaeArchive $simplecaeDestination
        if ($LASTEXITCODE -ne 0) { throw 'CalculiX archive extraction failed' }
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
