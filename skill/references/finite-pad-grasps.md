# Finite-pad wrench resistance

Use `grasp.model: "finite_pad_wrench"` when a declared two-pad grasp must resist
object force **and torque**. This is bounded wrench feasibility, not a universal
force-closure claim. It uses four corner contacts on each declared full rectangular
pad, fixed per-pad total normal force, and the inner friction pyramid
`|Ft_u| + |Ft_v| <= mu * Fn`, `Fn >= 0`.

The existing default `vertical_friction` remains for its narrower equal-opposing
normal/vertical-load case. Read `gripper-tasks.md` for that contract.

```json
"grasp": {
  "model":"finite_pad_wrench",
  "pad_wrench_mode":"declared_per_pad",
  "payload_names":["workpiece_share_0","workpiece_share_1"],
  "normal_load_names":["normal_0","normal_1"],
  "additional_tangential_load_names":["workpiece_acceleration_0","workpiece_acceleration_1"],
  "friction_coefficient":0.30,
  "slip_safety_factor":2,
  "conditions":{"friction_verified":false,"force_verified":false,"pad_contact_verified":false},
  "pad_contacts":[
    {"normal_load_name":"normal_0", "center_link_m":[0,0,0.0575],
     "tangent_u_link":[0,1,0], "tangent_v_link":[0,0,1], "half_extents_m":[0.008,0.012]},
    {"normal_load_name":"normal_1", "center_link_m":[0.035,0,0.0575],
     "tangent_u_link":[0,1,0], "tangent_v_link":[0,0,1], "half_extents_m":[0.008,0.012]}
  ]
}
```

These dimensions/values are an example. Declare actual pad/contact extent and
friction assumptions for the task. Do not infer full contact from nominal pad
dimensions: a smaller workpiece, curved face, tilt or partial separation needs
the actual contact footprint or a different model.

Pad centers and tangents are in the normal load's link frame (m). The inward
object normal is opposite the declared force on that finger. Tangents and that
normal must be orthonormal. Workpiece force/torque demand comes from the named
payload shares and additional loads, with their explicit position/force frames;
off-center COM and pure moments are included. Slip safety factor scales the
workpiece force/moment demand, not the fixed clamp command.

## Keep contact feasibility and component loads consistent

- `declared_per_pad` (default for this model) checks every pad's declared force and
  moment share as well as overall workpiece equilibrium. The LP cannot silently
  reallocate the load to a different, easier pattern than the component FEM used.
- `total_wrench` permits an optimized allocation across pads. It reports that this
  contact distribution has **not** been transferred to component FEM. A robot with
  FEM cannot obtain a combined conditional payload prediction from that mode.

Both compute a reference-wrench feasibility result and a fixed-plus-scalable
payload limit, with independently checked force and moment residuals. LP forces
and equations are normalized so N and N·m do not mix in a misleading residual.
Each contact's force and position remains in the result for inspection.

Possible failure includes insufficient vertical friction, insufficient torque
resistance, or an inconsistent per-pad load allocation. A motor or metal part
passing does not remove those failures. LP infeasibility is a model constraint
failure; a numerical LP failure is invalid computation.

The LP is not a local pressure/soft-pad/contact-separation solve. It does not
verify real friction, adhesion, control, partial contact or wear. Unknown
`pad_contact_verified`, `friction_verified` or `force_verified` keeps conditional
prediction unavailable. Complete robot/product ratings remain unavailable.

Underlying contact-wrench interpretation: [Modern Robotics, force closure](https://modernrobotics.northwestern.edu/nu-gm-book-resource/12-2-3-force-closure/).
This implementation checks a bounded prescribed wrench; it does not certify the
ability to oppose every possible wrench.
