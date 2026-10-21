# SimpleCAE source and third-party notices

Copyright (C) 2026 SimpleCAE contributors.

SimpleCAE-authored source, skill instructions, documentation and authored example assets in this source distribution are licensed under **GPL-3.0-or-later**, unless a file explicitly states another origin/license. The full text is in `LICENSE` (SPDX upstream text: https://github.com/spdx/license-list-data/blob/main/text/GPL-3.0-or-later.txt).

Third-party license/notice texts under `licenses/dependencies` retain their own copyright and terms. `licenses/dependency-inventory.json` records all distributions in the Windows lock, original wheel-relative notice paths and notice hashes. Other platforms may resolve different versions within the declared bounds and retain their notices in the installed distributions. These records do not imply dependency code or binaries are included. Do not replace upstream notices with the SimpleCAE license.

Gmsh is GPL-2.0-or-later with its upstream linking exception, as recorded in the installed Gmsh notice. SimpleCAE uses its Python/native API. Choosing GPL-3.0-or-later for this source avoids presenting this integrated toolkit as an unrestricted MIT/Apache-only package. Apache-2.0 Manifold and permissive dependencies keep their own notices. CalculiX runs as a separate external process; its GPL terms are not changed by this project's license.

The source archive contains no Python runtime, wheel, DLL, solver executable or downloaded solver distribution. Bootstrap obtains dependencies separately from their recorded upstream sources. Anyone redistributing an environment or solver binaries must separately retain applicable notices and satisfy corresponding-source and other upstream requirements; this source distribution is not clearance for such redistribution. The pinned third-party Windows distribution includes additional notices and a legacy README with a GE-confidential header; it is not repackaged or relicensed here. Use the upstream distribution intact or an explicitly supplied solver.

All bundled geometry is authored mathematical/test geometry, including shapes exported by pinned optional SimpleCADAPI/text-to-cad workflows; it is not purchased/vendor product CAD. See `examples/preview/USE.md` and `references/research-decisions.md` for provenance. No external project's implementation source has been copied into the analysis backend. User geometry/results remain subject to their own ownership; operating this tool does not by itself assign their rights or place them under this source license.

License inventory checking establishes provenance and notice completeness for the stated source package. It is not a legal opinion about every downstream integration, and does not certify engineering results.
