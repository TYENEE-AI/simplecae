# Research decisions for the general release

The Sohu survey (2026-10-07; https://www.sohu.com/a/1084649320_121124362) was fetched directly on 2026-10-13 after the browsing interface could not open it. Its relevant value is discovery and workflow design, not numerical validation. The private `research/` directory retains the fetched page and inspected upstream snapshots; this source directory is excluded from distributable skill archives.

| Source inspected | Version / license | Implementation consequence |
|---|---|---|
| SimpleCADAPI | `59c6ed82a9616fb5360fc75dae1c865441863773`, Apache-2.0 | Consume STEP and product/scene metadata; preserve semantic interface selection via geometric signatures and explicit provenance. Generator's source remains owned by the generation workflow. |
| text-to-cad | `24573128ceaab564f497d7c12f995c41784c9539`, MIT; installed skill/cadgen 0.7.21 | Respect decorated model outputs, scene/occurrence references, GLB transforms, URDF SI units and explicit kinematic poses. A visual material assignment does not supply structural properties. |
| HPC-Skills | `4ea8069188d931875121cdd418d7a26e60f47152`, MIT | Separate geometry, algorithm, physical regions, numerical outputs and error recovery. Validate current CalculiX procedure behavior by real runs; the inspected step matrix is not itself a buckling implementation. |
| femis-skill | `ceff46782f8379425162f7de42a46312f07704a5`, Apache-2.0 | Keep numerical verification separate from physical validation, retain source/input/result hashes, and converge the quantity being used for a claim. Treat this as methodology, not an execution backend or an authority to introduce unrelated approval requirements. |
| CAE-Agent-Hub | `194ef498e6efb1984cd65325e21e71087588a581`, MIT | Typed execution and result interfaces are useful; the CalculiX MCP starts primarily from a prepared INP deck, so model and robot adapters must be supplied by SimpleCAE. |
| pygccx | `83b9d16fa5ffa5443e5ce1463ccf1ebe4671f0e8`, GPL-3.0 | Its mesh/keyword abstraction is useful to evaluate; this toolkit's current quadratic-mesh and conservative-wrench path is independently implemented. No upstream code has been copied so far. Integration is optional if it adds verified capability; introducing it does not remove the need for validation. |

## Product scenarios informing tests

- Robot arm and tool payload: posture, center-of-mass offsets and joint effort all matter, even at the same payload mass. Use Newton–Euler static wrench propagation and independent simple-arm examples. Refer to official ROS URDF frame/joint semantics and primary robotics statics literature; do not infer effort ratings from appearance.
- Mobile DIY robot: a long arm can cause tipping before a link yields. Evaluate declared support geometry and conservative contact equilibrium, independently of elastic body analysis.
- Printed linkage, enclosure and mount: printing direction and layer adhesion can dominate. Support user-calibrated directional properties and clearly expose omitted creep, defects and infill details. Prusa's own material/modeling guidance supports treating these as input requirements, not replacing them with a universal PLA/PETG strength value.
- Initial engineering sizing: axial, bending, pure couple, self-weight, multi-case envelope, bonded assemblies and elastic column buckling give independent checks of different load paths and material responses.

## Physics sources

- Gmsh 4.15.2 manual: https://gmsh.info/doc/texinfo/gmsh.html (STEP/discrete-surface meshing and reference coordinates).
- CalculiX official distribution/manual: https://www.dhondt.de/ and https://www.dhondt.de/ccx_2.21.pdf (C3D10, equivalent loads, material orientation and BUCKLE procedure). Solver used for tests is actually detected as 2.23, with executable and input/result hashes.
- Elastic buckling limitations: https://docs.software.vt.edu/abaqusv2025/English/SIMACAEANLRefMap/simaanl-c-eigenbuckling.htm (imperfection-sensitive and nonlinear response limitations; used as theory, no Abaqus dependency).
- Primary robot equilibrium example: https://robotics.stanford.edu/~latombe/projects/HumanoidPlanner.pdf (gravity, effort limits and contact/friction equilibrium).
- Prusa material/design guidance: https://help.prusa3d.com/filament-material-guide and https://help.prusa3d.com/article/composite-materials-filled-with-carbon-kevlar-or-glass_167387.

Reference-case parameters are declared assumptions with closed-form comparisons. None of these sources, the survey rankings or upstream test counts establish performance or physical load capacity of SimpleCAE-generated products.

The current local official CalculiX 2.23 distribution manual was also extracted and checked directly (ELASTIC engineering-constant order, ORIENTATION, GLOBAL stresses, EQUATION dependent-DOF restrictions, SPRING1 and RF/CLOAD meaning). It takes precedence over the older linked manual for this backend. Directional constitutive checks enforce reciprocal positive compliance, and failure checks use explicitly calibrated signed material-axis allowables.

The independent planar nonmatching-interface implementation follows the dual-space mortar idea in [Wohlmuth, SIAM J. Numerical Analysis](https://epubs.siam.org/doi/10.1137/S0036142999350929), with explicit triangle-intersection quadrature and a constant-traction/rigid-motion verification. This is an implementation reference, not a blanket claim of all paper convergence guarantees. Manifold 3.5.4 (Apache-2.0) supplies mixed-mesh penetration checks; no resulting boolean geometry is substituted for input bodies. License checked against the installed wheel and [upstream LICENSE](https://github.com/elalish/manifold/blob/master/LICENSE).
