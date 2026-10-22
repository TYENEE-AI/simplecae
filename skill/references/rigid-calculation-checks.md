# Rigid robot checks without component FEM

Use the existing `robot-1.0` case for declared poses, SI inertials, gravity,
payloads, actuator limits, ground equilibrium or grip friction. This is a
calculation, not link strength or elastic displacement. The Agent selects the
model and checks; product names never choose physics.

In a task, set `method: "calculation"`, `decision: "now"`, the explicit
`load_path`, `load_basis`, `support_basis`, and `result_criteria`, then bind its
case in `cases`. The same `task start`, `task run --check ID`, `task status`
and Viewer work. Case preparation starts no worker. A computed calculation
must have no `components`, `required_components`, `elastic_transfer` or
`probes`; use `method: "fem"` when structural fields are requested.

Available criterion names include `POSE/ground_equilibrium` and
`POSE/grasp_friction`. Ground equilibrium is categorical feasibility of the
existing unilateral-point-contact LP. It has no invented stress utilization
or universal stability score. Grasp is only the explicitly selected model's
force/wrench balance. Neither certifies real contact strength or friction.
Confirmed failures stay visible even if another requested criterion is
unresolved. Aggregate validity/capacity still stays withheld.

Other calculations, such as an applicable beam/column formula or geometry
clearance script, remain external `calculation`/`geometry` checks **without
`result_criteria` or `case_path`**. Record their actual artifacts with
`task record`. This path cannot overwrite computed calculation/FEM evidence.

Strict robot comparison freezes non-FEM link masses and local COM along with
the existing loads, poses, limits, supports and numerical gates. FEM-covered
link mass changes remain subject to actual CAD volume/density/COM checks.
The component mass/COM alignment tolerance policy is part of the comparison
contract too; increasing those tolerances is not a geometry improvement.
Real ballast or support changes may be valid designs, but require separate
evidence and are not ranked under the old unchanged-model contract. Legacy
robot results without frozen rigid-link mass/COM need a fresh run for ranking;
their files are preserved. Face-ID geometry hashes remain strict too.

Before a strength run declare an applicable `failure_criterion` explicitly
(e.g. `von_mises_yield` for the stated ductile isotropic mathematical model),
strength data, safety factor and material applicability. A yield value alone
does not silently choose a failure model. Missing criteria must remain
indeterminate. Never replace task accuracy with a convenient mount point.
