#!/usr/bin/env bash
# Ubuntu setup. Never invokes sudo or replaces an existing Windows environment.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python="python3"
ccx="${SIMPLECAE_CCX:-ccx}"
venv="$root/.venv-linux"
while (($#)); do
    case "$1" in
        --python|--ccx|--venv)
            if (($# < 2)); then echo "Missing value for $1" >&2; exit 2; fi
            case "$1" in
                --python) python="$2";;
                --ccx) ccx="$2";;
                --venv) venv="$2";;
            esac
            shift 2;;
        --help|-h)
            echo "Usage: bash scripts/bootstrap.sh [--python python3] [--ccx /path/to/ccx] [--venv PATH]"
            echo "Ubuntu prerequisites: python3-venv calculix-ccx libglu1-mesa libxft2 libxcursor1 libxinerama1 libgomp1"
            exit 0;;
        *) echo "Unknown argument: $1" >&2; exit 2;;
    esac
done
"$python" -c 'import sys,struct; assert sys.version_info >= (3,11) and struct.calcsize("P")==8, "Use 64-bit Python 3.11 or newer"'
if [[ -e "$venv/Scripts/python.exe" ]]; then
    echo "This directory contains a Windows environment; choose a separate Linux --venv." >&2
    exit 2
fi
if [[ ! -x "$venv/bin/python" ]]; then
    if [[ -e "$venv" ]]; then
        echo "The selected environment exists but has no working Linux Python. Choose a fresh --venv; no files were removed." >&2
        exit 2
    fi
    "$python" -m venv "$venv" || {
        echo "Install python3-venv with your Ubuntu package manager, then retry with a fresh --venv." >&2
        exit 1
    }
fi
runtime="$venv/bin/python"
"$runtime" -m pip install --no-cache-dir -e "$root"
if ! "$runtime" -c 'import gmsh; gmsh.initialize(); gmsh.finalize()'; then
    echo "Gmsh native libraries are missing. Ubuntu prerequisites: libglu1-mesa libxft2 libxcursor1 libxinerama1 libgomp1. Install them with your package manager." >&2
    exit 1
fi
"$runtime" "$root/scripts/simplecae_cli.py" doctor --ccx "$ccx"
"$runtime" - "$root" "$ccx" <<'PY'
import json
import platform
import sys
from pathlib import Path
from simplecae.solver import find_ccx
root, ccx = Path(sys.argv[1]), find_ccx(sys.argv[2])
config = root / ".tools/runtime.json"
config.parent.mkdir(parents=True, exist_ok=True)
existing = json.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
existing.setdefault("ccx_by_platform", {})[platform.system()] = str(ccx)
config.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
PY
echo "Ready. Run from the skill directory:"
printf '%q scripts/simplecae_cli.py quickstart --out outputs/first-001\n' "$runtime"
