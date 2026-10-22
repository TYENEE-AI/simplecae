"""Fast offline native runtime probe, also callable before addon provisioning."""
import json
import argparse
import math
import subprocess
import re
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=30,
                        help='Native solver version-probe deadline in seconds (default: 30)')
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    try:
        from simplecae.solver import find_ccx
        from simplecae.environment import environment_warnings
        import gmsh
        from simplecae import gmsh_runtime
        gmsh_runtime.initialize()
        gmsh_runtime.finalize()
        ccx=find_ccx()
        probe=subprocess.run([str(ccx),'-v'],capture_output=True,text=True,timeout=args.timeout)
        # Official Windows CCX 2.23 prints its version then exits 201 for -v.
        # Require the exact version banner as well; a loader/crash code is not ready.
        banner=probe.stdout.strip()
        if probe.returncode not in (0,201) or not re.fullmatch(r'This is Version \d+(?:\.\d+)+',banner):
            raise RuntimeError(f'CalculiX native probe returned {probe.returncode}: {banner} {probe.stderr}')
        print(json.dumps({'status':'ready','python':sys.executable,'ccx':str(ccx),
                          'gmsh':gmsh.__version__,'warnings':environment_warnings(),
                          'meaning':'Native loading only, including required shared libraries; not engineering acceptance.'}))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'unavailable','error':str(exc),
                          'next_action':'Provision the separate {runtime_dir}/.venv and native solver using references/platform-installation.md, then sca addon check simplecae.'}))
        return 2


if __name__=='__main__':raise SystemExit(main())
