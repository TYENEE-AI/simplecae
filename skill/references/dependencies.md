# Runtime, provenance and third-party dependencies

SimpleCAE-authored code/docs/examples use GPL-3.0-or-later. [NOTICE](../NOTICE.md) defines the source-only boundary. [The exact inventory](../licenses/dependency-inventory.json) and verbatim notices cover every package in the Windows Python lock, including transitive/test dependencies; `scripts/audit_dependencies.py` is a maintainer check of completeness and notice content; it tolerates line-ending conversion, not changed license text. License metadata is retained verbatim, including composite wheel notices. Ubuntu resolves the dependency ranges in `pyproject.toml`; its installed versions and upstream notices remain in that environment. The Windows inventory must not be described as an exact lock for every platform. External CalculiX is obtained separately, not relicensed/bundled.

Core analysis uses Gmsh 4.15.2 (GPL v2 or later), external CalculiX 2.23 (distribution includes GPL v2 text), NumPy/SciPy (BSD-family notices), Matplotlib (Matplotlib/PSF license), trimesh and meshio (MIT), defusedxml (PSF), jsonschema (MIT), and Manifold 3.5.4 (Apache-2.0). Exact resolved versions, including transitive packages, are in `requirements-lock.txt`; installed packages retain their upstream license files. Manifold is used only to check body penetration for mixed-mesh assemblies. Interface projection/integration and all solver orchestration are independently implemented here.

The source archive excludes downloaded solver binaries, environments and upstream repository snapshots. Windows bootstrap downloads the upstream [CalculiX-Windows distribution](https://github.com/calculix/CalculiX-Windows) at commit `60c9a10b350ec813f4d493098f47f7a8b96cd276`, archive SHA-256 `79a674fdee735a22720bbd12bb9ccbadad1e8c8ad5b1de74e1c62f8808b2d395`; the verified ccx executable SHA-256 is `27a9426a1ee2f72c38fbe892e0ffaf38e14867628ffd0235770261b6f3ec9c5f`. Downloaded distribution notices remain intact. A provided `-Ccx` path is saved locally for later invocations; explicit `--ccx` or `SIMPLECAE_CCX` overrides it.

The local performance follow-up also evaluates that same downloaded
distribution's `ccx_MT.exe` (SHA-256
`62349096f3b76cef2f0e094d03f747187016683a233ec7f07a363c7089804876`).
It introduces no dependency or redistributed binary. Default discovery stays
with `ccx.exe`; select a parallel build explicitly and retain all native-field
checks. Measured 1/2/4-thread parity and an automatic replay are recorded in
[platform evidence](platform-evidence.md). This is not blanket qualification of
other builds, thread counts or platforms. See [resource selection](execution-resources.md).

SDK fixture generation used actual SimpleCADAPI 2.2.1 (Apache-2.0) and cadgen/text-to-cad 0.7.21 (MIT). Their pinned source revisions, inspected upstream projects and adoption decisions are recorded in [research-decisions.md](research-decisions.md). Saved exported models and independent generators are included; SDKs are optional and unnecessary for analysis of those saved files. No pygccx/HPC-Skills/femis/CAE-Agent-Hub source has been copied. [Manifold's upstream license](https://github.com/elalish/manifold/blob/master/LICENSE) and installed wheel metadata were checked.

Showcase CAD uses SimpleCADAPI2.2.4; the earlier SDK fixtures retain their original
provenance. No CAD SDK is needed to analyze the saved STEP inputs.

Installation is local to the skill folder: Windows
`powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 [-Python PATH] [-Ccx PATH] [-Locked]`;
Ubuntu `bash scripts/bootstrap.sh [--python PATH] [--ccx PATH]`.
The latter uses separate `.venv-linux`, preserves platform-specific solver settings,
and reports missing native dependencies without modifying system packages.
Actual Windows and WSL Ubuntu evidence is described in
[platform evidence](platform-evidence.md); macOS native execution is not qualified.
Source archives supply skill instructions, examples and verification scripts,
not a runtime or solver executable. Wheels include toolkit resources and support
`python -m simplecae`, including subprocess workers; a wheel alone does not install
a host's `SKILL.md` directory. Keep the source skill intact for Agent discovery.

Ordinary bootstrap installs runtime dependencies within pyproject bounds, reuses a
compatible local environment and configured solver, and does not install tests.
Windows `-Locked` opts into the archived full dependency lock for maintainers.
A ready environment needs no network or system Python rediscovery.
