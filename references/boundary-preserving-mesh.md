# Planar ports and native high-order mesh optimization

A flat CAD face is not sufficient for the straight-sided quadratic transfer
algorithm: an unconstrained high-order optimizer can move its midside nodes
within that face. The interface check rejects such a mesh. Its original
straight-edge tolerance remains unchanged; pressure, stress and hotspots are
never clipped or omitted.

For an actual flat **straight-edged** port, an Agent can explicitly request:

```json
"mesh": {"sizes_mm":[2,1.6,1.28],"preserve_boundary_nodes":true}
```

This uses Gmsh `Mesh.HighOrderFixBoundaryNodes=1`: boundary nodes retain their
positions from CAD projection before interior high-order optimization. The
default is false and the setting is reset per mesh. There is no node snapping,
straightening of curved holes, source-geometry edit or tolerance increase.
All native optimizer errors, adaptive positive Jacobians, signed quality,
CAD-volume agreement, full-field equilibrium and convergence gates still apply.
The choice is saved in the case and mesh report.

Fixing boundaries can prevent the optimizer from untangling a coarse curved
region. Resolve actual curvature with appropriate global or existing whole-face
local refinement. In an assembly, use each body's own `local_refinements` and
source-bound selector; identical shapes do not imply identical STEP hashes.
Do not add refinement everywhere when only a remote hole needs it. Always keep
three systematically refined meshes and a finite execution budget. A timeout
or rejected optimizer remains insufficient evidence, not a weak-part diagnosis.

This option does not add curved-interface quadrature, arbitrary overlap or
nonplanar contact. Curved port boundaries need an already supported explicit
model (for example qualified contained planar contact) or another appropriate
method. It is not an automatic fallback or guarantee of convergence.

Primary source: [Gmsh reference manual, mesh options](https://gmsh.info/doc/texinfo/gmsh.html#index-Mesh_002eHighOrderFixBoundaryNodes).
