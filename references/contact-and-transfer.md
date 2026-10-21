# Planar contact, axial preload locking and first-order robot elasticity (1.5)

Use the existing `analyze` command and case schemas. No new solver or plugin is needed. Runnable mathematical references are in `examples/mechanics`; `validate --suite mechanics --out FRESH_DIRECTORY` checks analytical responses and adverse controls. These are numerical references, not physical products.

For 1.5 bolt/friction examples use [examples/joints](../examples/joints/USE.md) and `validate --suite bolt-friction --out FRESH_DIRECTORY`. These additions use the same dependency lock and no automatic contact discovery, CAD optimizer or arbitrary loading-history language.

## Planar frictionless contact

An `assembly-1.0` connection can use:

```json
{"name":"seat","type":"frictionless_contact",
 "master":{"body":"base","selector":{"type":"plane","axis":"x","position_mm":50}},
 "slave":{"body":"slider","selector":{"type":"plane","axis":"x","position_mm":0}},
 "normal":[1,0,0],"normal_stiffness_n_mm3":100000,
 "initial_gap_mm":0,"gap_convergence_tolerance_mm":0.00001,
 "calibration":{"reference":"Explain source of penalty stiffness","applicability":"Explain applicable materials, geometry and penalty sensitivity"}}
```

Selectors use each body's CAD coordinates; the normal is in assembly world axes, outward from master toward slave. Default `matching` requires the same full footprint and straight quadratic edges. The toolkit also supports opt-in [CAD-verified contained planar contact](contained-planar-contact.md), including curved planar boundaries. The actual geometric gap must match `initial_gap_mm` (default zero). The toolkit does not move nodes, fuse solids, remove a real interference or replace a missing connection. Nonplanar contact, arbitrary partial initial overlap and self-contact are unsupported.

The backend writes CalculiX face-to-face contact with linear pressure-overclosure. Normal pressure is compression-only; separation is permitted and tangential friction is zero. `normal_stiffness_n_mm3` is pressure per penetration, **MPa/mm = N/mm³**, rather than a total spring stiffness. A finite penalty produces penetration. Check penalty sensitivity separately from mesh convergence; do not inflate stiffness until a desired answer appears. Contact pressure samples are output, without inventing a calibrated pressure allowable, true area fraction or surface failure criterion.

Every body must remain statically stable in every stage, including when contact opens. A frictionless seat does not constrain tangential rigid motion. Declare actual guides/stops/fixtures; a free body initially separated from its only support can fail to find static equilibrium. Do not add a fictitious support to force success. Preserve `invalid` and `indeterminate` results.

### Applied preload and sequence

Existing `loads[].scalable:false` forces and gravity are applied first. The second step retains those fixed loads and applies the full declared service loads. With no fixed loads, there is one service step. CLOAD values are explicit dead loads, not follower loads. Preload and service stages are separately checked for stress, displacement, equilibrium, mesh convergence and small response. A preload failure cannot be hidden by an opposing service force.

This force-only mode implements **applied clamping-force preload**. It does not itself lock a bolt or infer tightening torque. Use the explicit equivalent bolt model below when retained preload is required. Thread engagement, embedding, relaxation and mounting failure remain unassessed.

Optional `contact_control` provides `initial_increment` (0.1), `minimum_increment` (1e-6), `maximum_increment` (0.2) and `max_increments` (200). Values are dimensionless step fractions and require `0 < minimum <= initial <= maximum <= 1`. The complete load in every requested step must be reached. A partial increment or a successful process exit alone cannot qualify a result.

Keep three or more successively refined meshes. Existing stress tolerance also checks peak contact pressure; the minimum-gap convergence tolerance defaults to 1e-5 mm per connection. Fully open interfaces can generate no native contact elements: zero pressure is accepted only after positive actual material separation is sampled across the segmented footprint. Missing contact output alone is not a zero-pressure result. This sampling is a small-sliding numerical check, not an analytical proof of arbitrary deformed-surface nonintersection.

Coverage is checked per slave face: paired native stress/displacement samples, or positive material-opening evidence on that face. Partial tables on closed faces cannot qualify the entire contact pair.

Contact cases do **not** use fixed/full linear superposition or output an automatic capacity multiplier. Rerun each requested actual load level and retain each load history. Cache/level reuse is deliberately rejected for this new history-dependent mode until qualified. Elastic buckling with changing contact is rejected. The existing small-response screen remains active even though the contact deck uses nonlinear iterations.

## Equivalent axial bolt with retained preload

Add an assembly-level `bolts` list, alongside explicit planar contact connections:

```json
"bolts": [{"name":"fastener",
  "master":{"body":"base","selector":{"type":"plane","axis":"x","position_mm":0}},
  "slave":{"body":"cap","selector":{"type":"plane","axis":"x","position_mm":50}},
  "axis":[1,0,0],"axial_stiffness_n_mm":100000,
  "preload_n":1000,"allowable_tension_n":2000,
  "reference":"State stiffness calculation/test, preload source, axial allowable including safety margin, and their applicability"}]
```

Selectors use local CAD coordinates. `axis` is a world unit vector from the master attachment centroid toward the slave attachment centroid. Both attachments must be planar, normal to this axis, with aligned distinct centroids. They need not have identical meshes or areas. The model distributes axial force through consistent area-average attachment weights; it adds no rigid head, shear tie or fictitious support. Define real head/washer regions upstream when needed. This is an axial equivalent, so attachment averaging cannot resolve local bolt-head bearing or local thread stress.

The generalized elastic extension is `e = axis·(u_slave_average-u_master_average) + q`, energy is `k*e²/2`, and bolt force is `k*e`. A native spring and linear constraint implement this relation. Stage 1 applies generalized force `P0` to tighten `q`. Stage 2 removes that force and freezes the achieved `q` using `*BOUNDARY,FIXED`. Stage 3 retains `q` and adds service loads. **The adjustment is locked; elastic extension and bolt force can still change.** Ordinary fixed forces and gravity remain in every stage. Bolt-only preload cases may have an empty loads list.

Each stage independently checks force/moment balance, body criteria, bolt axial tension, contact and mesh convergence. Raw `fixed-results.json`, `locked-results.json` and final fields are retained. Final results contain per-bolt force, adjustment, elastic and attachment extension, utilization and lock error. Missing controls, incomplete steps or a changing locked adjustment invalidate the calculation. A preload or lock failure remains in the overall verdict even when service relieves the bolt.

Criteria assess the requested **stage endpoints**, not intermediate-increment peak stress or an arbitrary cyclic load path. Unload/reload cycles, accumulated plastic slip and time-dependent relaxation are outside qualification.

`allowable_tension_n` is already an allowable: include the intended safety factor when supplying it. Do not use body yield stress as a bolt allowable or infer preload from tightening torque. Axial stiffness, preload and allowable need a defensible reference and applicability statement. Multiple declared bolts may act in parallel; automatic bolt-pattern load allocation is not provided.

This is a **fixed-axis, tension-carrying equivalent axial model**, not a detailed continuum `*PRE-TENSION SECTION`/thread model. Compressive/slack bolt states and transverse attachment motion above 1% of initial bolt span fail the applicability screen and withhold a favorable verdict. The screen is a heuristic, not a validated large-rotation limit. It excludes bolt shear/bending, bearing, thread pullout, torque conversion, preload scatter, embedding, relaxation, fatigue and unspecified joint/fixture compliance. A model pass never certifies the fastening assembly or product.

## Planar Coulomb friction

Change a planar connection to `type:"frictional_contact"` and supply:

```json
"friction_coefficient": 0.2,
"tangential_stiffness_n_mm3": 10000,
"max_tangential_displacement_mm": 0.001,
"slip_convergence_tolerance_mm": 0.00001
```

Keep the existing normal, normal penalty and calibration reference/applicability. These are prescribed parameters, not toolkit material defaults. Both coefficient and stiffness must be positive; use `frictionless_contact` for zero friction. The native law is elastic penalty stick followed by the Coulomb shear bound `|tau| <= mu*p`; an open interface carries neither normal pressure nor friction. This is a single constant coefficient, without separate static/kinetic coefficients, adhesion, wear, rate effects or thermal coupling.

`max_tangential_displacement_mm` is a required task limit. The assessed quantity is the maximum sampled relative **material-point** tangential motion on the initial segmented footprint, including elastic compliance. Native `CDIS` tangential magnitudes are retained separately; neither quantity alone proves accumulated irreversible slip or a sliding area fraction. Pressure, shear, gap and material motion require two consecutive mesh comparisons. Shear uses the existing stress tolerance; gap and material-motion absolute tolerances default to 1e-5 mm. Coulomb bound violations are reported, never clipped. Near-bound samples indicate local sliding saturation; they are not an area measurement.

Initial footprints must coincide completely in projection and remain within the small-sliding model. Sampled tangential motion exceeding **1% of the initial footprint diagonal** withholds a favorable verdict; no threshold is increased to accept a candidate. The normal material-gap sampling and mesh checks do not prove arbitrary deformed-surface extrema or nonintersection. Nonplanar contact, partial initial overlap, large travel, changing contact pairs and self-contact remain unsupported. A force-controlled free slider above friction capacity may have no static solution: retain `invalid`/`indeterminate`, not a safe-load claim.

For a mathematically zero shear stage, both mesh readouts must be below the same fixed 1e-7 MPa native stress resolution already used in sign/Coulomb checks, or satisfy the normal relative shear convergence gate. This avoids division by zero-scale noise; it does not change task allowables or clip the recorded stresses.

For a displacement-controlled test or an actual moving fixture, supports may specify `service_displacement_mm:[ux,uy,uz]` in world mm, on their constrained DOFs only. They are zero during preload/lock and ramp to these values in service. Overlapping stationary/moving prescriptions must agree. Preview and report disclose the movement. This is an explicit physical fixture; do not add one merely to stabilize an otherwise unsupported product. `prepare` remains a solid-first intake and does not auto-create bolt/contact data.

## URDF first-order section-frame transfer

The optional robot compliance model supports [independent scalar joint compliance](joint-compliance.md). The locked-joint default described below remains compatible; stiffness is never inferred from URDF effort, friction or damping.

Default robot probes still use independent component fields. Explicitly opt in with:

```json
"elastic_transfer": {
  "rigid_links": ["base"],
  "joints_locked_verified": false,
  "max_rotation_rad": 0.01,
  "max_section_warping_mm": 0.001,
  "reference": "Explain the locked-joint, rigid-link and section-model assumptions"
}
```

Choose accuracy limits from the task before solving; do not relax them to accept a candidate. A rotation limit above 0.05 rad is rejected. The warping limit bounds the area-weighted RMS residual of a rigid section fit, not its maximum or an independent joint strength allowable.

Requirements:

- A fixed-base URDF tree at explicit poses, with at least one task probe. Closed drive-reaction loops and contact bases require a coupled model and are rejected in this mode.
- Every URDF link appears exactly once as a FEM component or in `rigid_links`, including massless virtual frames. A rigid declaration is a modeling assumption, not a strength check.
- Each FEM template has exactly one fully clamped upstream surface. Existing CAD/URDF mass, COM, material, load-port and source checks remain active.
- Every child joint of a FEM link has a named planar material section in `component.ports[joint_name]`, even for a zero transmitted wrench. Task-point/surface probes still require their own explicit FEM link.

The original rigid statics supplies each component's loads at the posed configuration. The code fits **translation and all three infinitesimal rotations** to the actual quadratic material displacement on each downstream port, using positive area quadrature. It passes those motions down the URDF tree. At a downstream point, ancestor rotation contributes `theta × lever_arm`; translations alone are insufficient. Common ancestor motion is included before relative probe evaluation. Fixed gravity and full-load motions are propagated separately.

Transmitted frames and requested task probes require two consecutive refined-mesh comparisons. Frame rotation and warping screens must pass. If they fail, the task result is indeterminate and has no favorable comparison margin. A task can fail even when all independent links pass. Raw section translations, rotations, warping residuals and mesh comparisons remain in `result.json`.

`measurement_scope="first_order_section_frames"` and `coverage.first_order_chain_displacement_available` identify this capability. `whole_robot_displacement_available=false` remains explicit: this is a reduced tree model with ideal locked joints, rather than a coupled continuum solution enforcing section warping compatibility. It excludes bearing/gear/motor/guide compliance, backlash, contact, rigid-link elasticity, P-delta redistribution, changing actuation load paths and flexible control response. Joint locking confirmation is separate from the numerical result and never inferred from URDF joint type.

This initial mode evaluates requested loads and withholds automatic chain capacity extrapolation. It does not establish an overall robot rating, physical material qualification or product acceptance.

## Primary solver reference

[CalculiX 2.23 official manual](https://www.dhondt.de/ccx_2.23.pdf): `*CONTACT PAIR`, `*SURFACE BEHAVIOR`, `*CONTACT PRINT`, `*FRICTION`, `*SPRING`, `*EQUATION`, `*BOUNDARY,FIXED` and `*STATIC`. `*PRE-TENSION SECTION` describes a different continuum bolt-section model not exposed here. See the [official project](https://www.dhondt.de/) for the solver and examples.
