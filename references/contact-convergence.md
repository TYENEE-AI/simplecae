# Partial opening and native contact convergence

An assembly may be driven solely by nonzero `supports[].service_displacement_mm`
through the existing staged contact backend. Do not add a fictitious force to
satisfy an input check. With no applied force or preload, equilibrium uses half
the sum of fixture-reaction magnitudes as its force scale, recorded in the native
result; a missing reaction path cannot pass. Full force/moment residuals, contact
sign, field coverage and small-response gates still apply. A prescribed motion
outside the model's validity calls for another applicable model, not endless
mesh refinement, altered stiffness or invented supports.

Native STEP cylinder/cone/sphere/torus connection faces are rejected during input
validation before volume meshing. This early rejection does not replace the later
coplanarity, trimmed-footprint and quadratic-mesh projection checks.

This is a numerical control for declared planar contact, not a contact material property or a product allowable. It applies to both matching and CAD-contained footprints.

CalculiX 2.23 face-to-face static contact selects active springs, solves and updates the displacement. Its default `delcon=0.001` allows a small relative change in active contact count at convergence. The native linear spring evaluates pressure as `p = -kn * clearance` on the current active set. Some springs can open during the final update and still appear with negative pressure in the printed field. This is not adhesive contact and is not grounds for clipping the output.

The bundled small reference reproduced that mechanism on a partially opening frictional interface. On an identical mesh, tightening force residuals alone retained the negative sample; `delcon=0` removed it. This isolates the mechanism in that reference. It does not prove that every future negative-pressure result has the same cause.

The toolkit now emits `*CONTROLS,PARAMETERS=CONTACT` with zero accepted change in contact count by default. Optional `contact_control.contact_change_relative_tolerance` accepts 0..0.001, permitting an explicit former-default adverse reference. Count stability is not identity or complementarity proof: the original native negative-pressure and Coulomb checks still apply to every returned stage. The negative-pressure rejection threshold remains -1e-7 MPa.

An additional same-mesh diagnostic using the installed solver's iterative linear methods retained a negative pressure even with zero count tolerance; that alternative was rejected. A two-point unilateral tabular encoding also crashed this local CCX build and was not adopted. These are reasons to retain the actual native-field checks and qualify a solver build, rather than assume a control setting alone establishes valid contact. The supported toolkit continues to use its verified native LINEAR path; no tabular law or alternative solver is silently substituted.

For a changing contact state, choose explicit gradual loading, for example:

```json
"contact_control": {
  "initial_increment": 0.1,
  "maximum_increment": 0.2,
  "minimum_increment": 0.000001,
  "max_increments": 200,
  "contact_change_relative_tolerance": 0
}
```

These numbers are an example, not a universal convergence guarantee. Every stage must still reach its full endpoint. Sensitivity checks must retain the declared physical load, geometry and acceptance gates. Contact caching/reuse remains unsupported.

The bolt **locked** stage now starts with one full increment: the preceding
adjustment is frozen while the same fixed loads are retained, so there is no
physical load ramp to subdivide. This still runs the native equilibrium solve,
permits cutback, and preserves the full locked-state fields and all pressure,
bolt-lock, balance and mesh-convergence checks. Preload and service ramps retain
their declared controls. For a large contact mesh, inspect actual `.sta` progress
before retrying; repeated equilibrations of an unchanged state can be expensive.
Do not assume a larger initial increment is appropriate when slip, separation or
other path dependence matters. Compare against a completed finer-increment
reference before accepting an alternative loading strategy.

On a native timeout, `job.solver-diagnostic.json` records completed increments,
equation count, factorization count and contact spring counts. It does not infer
convergence from a small printed residual or make a timeout into a structural
failure. Fix mesh distribution or justified numerical staging before increasing
any resource allowance.

When an already verified preload/lock strategy should be retained, optional `service_initial_increment` and `service_maximum_increment` override only the service stage. For example, global initial/maximum increments of 1 can retain an established preload step while service overrides 0.1/0.2 gradually apply the external load. Both inherit the same minimum increment and increment budget. This controls the numerical continuation, never the final load magnitude. The bolt/friction suite includes an analytical three-stage service-ramp reference.

A rejected `contact-diagnostic.json` identifies the contact, output time and all offending element/face samples, including the original signed pressure and native clearance. In the current CCX face-to-face implementation positive clearance means separation. `nominal_linear_law_residual_mpa` helps diagnose `p + kn*clearance`; it is not an acceptance override. Native input, DAT and executable hashes bind the diagnostic. The result stays invalid and cannot receive a favorable comparison or capacity.

Inspect `job.solver.log` while a solve runs; the child process writes its native iteration trace there. A missing completed endpoint, rising residual or timeout is not a solved load. A stale stage timestamp is not evidence that a process is still running.

Run the reproducible reference:

```powershell
python scripts/simplecae_cli.py validate --suite contact-opening --out NEW_DIRECTORY
```

It includes an intentionally rejected legacy-count reference, a strict-count three-mesh solve and a strict incremental three-mesh solve. The transverse guide is a mathematical fixture; do not copy it to a real mounting without physical justification. See `examples/mechanics/contact-partial-opening.case.json` for the input.

Primary implementation/documentation: [official spring force](https://github.com/Dhondtguido/CalculiX/blob/master/src/springforc_f2f.f), [active spring generation](https://github.com/Dhondtguido/CalculiX/blob/master/src/gencontelem_f2f.f), and the CalculiX 2.23 manual sections 6.10.2 and `*CONTROLS,PARAMETERS=CONTACT`. The underlying solver still requires independent numerical checks; changing a solver parameter does not calibrate an installation.
