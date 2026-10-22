# Separate CAD and CAE environments

Use three independent environments: SimpleCAE, SimpleCADAPI (validated 2.2.6.post2 on Python 3.13), and cadgen (validated 0.7.26). Exchange STEP and source-bound manifests. Never install CAD packages into CAE or import OCP there. `cadquery-ocp` and `cadquery-ocp-novtk` overwrite the same Python namespace; `doctor` warns if both are installed. Obtain package versions with `importlib.metadata.version`, never `scad.__version__`.

In commands, replace `<SIMPLECAE_PY>` with the absolute CAE interpreter and run from the SimpleCAE payload/repository root. In an addon, `sca addon use simplecae` reports `addon_dir` and `runtime_dir`; use the latter for all environments/caches. Installed agent references live in `skill/`, runtime code in the payload's `scripts/`. Maintainers synchronize the root and addon SKILL with `scripts/sync_addon_skill.py`; its `--check` is not a user installation gate.

| Host | `<SIMPLECAE_PY>` | Native solver setup |
|---|---|---|
| Windows x64 | `& 'C:/.../runtime/.venv/Scripts/python.exe'` in PowerShell | `scripts/bootstrap.ps1`; set `$env:SIMPLECAE_CCX` to the discovered `ccx.exe` |
| Linux x64 | `'/.../runtime/.venv/bin/python'` | `scripts/bootstrap.sh`, or the no-sudo environment below; export `SIMPLECAE_CCX` |
| macOS Apple Silicon | `'/.../runtime/.venv/bin/python'` | conda-forge CalculiX when available for the host; export `SIMPLECAE_CCX` to the native executable. This round does not validate macOS. |

The table uses addon runtime paths. Standalone Linux bootstrap defaults to
`<installed-folder>/.venv-linux/bin/python`; use the actual path printed by setup,
or the explicit `--venv` directory. Do not create another environment merely to
match the example path. The no-sudo addon recipe below provisions its own runtime;
it does not require subsequently running standalone bootstrap in the payload.

For Linux without sudo, install [micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html) in a user-owned directory. Keep its package cache/runtime outside the addon payload:

```sh
export MAMBA_ROOT_PREFIX="$SCA_RUNTIME_DIR/mamba"
micromamba create -y -p "$SCA_RUNTIME_DIR/native" -c conda-forge python=3.13 calculix libglu xorg-libxft xorg-libxcursor xorg-libxinerama
"$SCA_RUNTIME_DIR/native/bin/python" -m venv "$SCA_RUNTIME_DIR/.venv"
"$SCA_RUNTIME_DIR/.venv/bin/python" -m pip install "$SCA_ADDON_DIR"
export SIMPLECAE_CCX="$SCA_RUNTIME_DIR/native/bin/ccx"
export LD_LIBRARY_PATH="$SCA_RUNTIME_DIR/native/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$SCA_RUNTIME_DIR/.venv/bin/python" "$SCA_ADDON_DIR/scripts/addon_probe.py"
```

Set the two directories explicitly for standalone installation. Do not run Linux binaries on Windows or copy environments between hosts. On macOS use native arm64 package availability and runtime libraries; the Linux Xorg/libGLU package list above is not a macOS installation claim. A missing binary/library is an environment failure, not evidence about the model.

Addon installation: `sca addon add /path/to/simplecae`, provision `{runtime_dir}/.venv`, then `sca addon check simplecae`. The installed skill is `sca-simplecae`. Its probe loads Gmsh (therefore checks native shared libraries) and runs `ccx -v` offline. Do not start engineering analysis when the probe fails.

The solver version probe allows 30 seconds for cold native startup. For an
explicit diagnostic on an unusually slow host, run
`<SIMPLECAE_PY> scripts/addon_probe.py --timeout SECONDS` with a finite positive
limit. This bounds the solver version subprocess, not Gmsh initialization or
engineering analysis. A timeout remains unavailable; it never becomes a pass.
If bootstrap reports native loading failure, repair the reported shared library
or host execution environment before retrying. On Ubuntu, use the prerequisites
listed above; reinstalling Python packages does not supply missing system libraries.

Place generated evidence in `out/cae/` or `.simplecae/` and ignore that directory in the CAD project's Git configuration. The CLI warns if an output is not ignored; it does not edit user Git settings. Keep caches until the requested audit and retests finish and cleanup is authorized.
