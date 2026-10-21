# Measured force is not true force

Use the gripper task compiler when a holding-force window and bounded sensor
error must be propagated. `normal_force_per_finger_n` is the nominal measured
command. Add an explicit budget:

```json
"force_measurement": {
  "measured_hold_interval_n":[15,17],
  "absolute_error_n":2,
  "error_verified":false,
  "holding_window_verified":false,
  "reference":"physical calibration/holding tests pending"
}
```

The true normal-force interval is `[15-2, 17+2] = [13,19] N`. This includes the
declared holding window and sensor error once each; do not add the window's
variation a second time. Nominal16N alone does not cover this uncertainty.

`gripper-task TASK.json --out FRESH_DIRECTORY` detects the budget and generates:

- `nominal.robot.json`: optional nominal reference;
- `lower_force.robot.json`: required lower-force case;
- `upper_force.robot.json`: required upper-force case;
- `force-envelope.json`: source-bound compilation manifest and remaining actions.

The CLI returns each analysis case path and `analysis_required`. The manifest is
a compilation record, **not** a solver case or analysis result. Analyze both
required case files with `analyze`, then combine their results with `summarize`.
Do not treat the nominal case as the worst case or compare different force states
as different design candidates; they have distinct task contracts.

Minimum force governs friction assurance. Both endpoints still need structural
and drive checks: a fixed opposing load can make lower force the larger absolute
effort/response. For the declared linear elastic/affine force pattern, endpoint
checks bound convex displacement/stress criteria; they do not establish a
nonlinear or buckling result at every intermediate force.

If the uncertainty includes zero normal force, the compiler reports
`contact_not_assured`, does not invent a small positive lower force, and does not
mark a complete envelope. An optional upper-force structural calculation cannot
remove that contact-loss gap. Revise or verify the control window/error budget.

Both verification flags are false by default. Setting them true requires a
recorded reference; the toolkit does not independently measure the sensor or
controller. Existing false `grasp.conditions.force_verified` is preserved, and
an unverified budget forces that condition false in all generated cases.

Finite-pad geometry can be included in each task contact using `pad`:

```json
{"link":"moving_pad", "position_m":[0.035,0.002,0.0575],
 "normal_link":[1,0,0],
 "pad":{"center_link_m":[0.035,0,0.0575], "tangent_u_link":[0,1,0],
        "tangent_v_link":[0,0,1], "half_extents_m":[0.008,0.012]}}
```

Set task `grasp_model: "finite_pad_wrench"` and, when appropriate,
`pad_wrench_mode: "declared_per_pad"`. Read `finite-pad-grasps.md` before choosing
the footprint/load-allocation model. Task `probes` is passed to generated robot
cases; contributing links still need actual component FEM.
