# Explicit drive and reaction attachments

An actuator's required holding force/torque comes from the original external loads and URDF virtual work. A URDF moving joint does not reveal where the actuator is mounted. Use `actuation_reactions` to route internal loads into specified links before calculating component loads.

```json
"actuation_reactions": [{
  "name": "linear_actuator",
  "joint": "jaw_slide",
  "driven": {"link":"moving_plate", "point_link_m":[0.061,-0.022,0.027]},
  "reaction": {"link":"rear_mount", "point_link_m":[0.1435,-0.022,0.027]},
  "verified": false
}]
```

Points are in each attachment link's URDF coordinates, in **metres**. `preview` shows all poses, force/couple arrows, world axes and the path `driven ← actuator → reaction`. A positive prismatic effort applies `axis_world * effort` to the driven attachment and its opposite to the reaction attachment. An independent revolute motor applies equal and opposite axial couples. Force offsets are propagated as actual moments; the pair must have zero world resultant force/moment.

The driven link must lie below that joint; its reaction must be outside that subtree. Prismatic attachments must be collinear with the world joint axis at every pose, including zero-effort poses. Off-axis mechanisms, cable/pulley transmissions, cross-coupled moving joints and mimic transmissions need an explicit transmission model; this version rejects such ambiguous declarations. It does not invent balancing couples or bearing loads.

The original `actuator_efforts` remain the effort-rating input. `joint_support_wrenches_world` contains the residual support loads after the declared drive pair. A balanced drive has zero residual effort along its free joint coordinate; this does **not** imply zero original holding effort or zero transverse bearing loads. `subtree_supported_wrenches_world` preserves the routed result.

For a FEM component at an attachment, provide a selector under the generated port name `actuation:<name>:driven` or `actuation:<name>:reaction`. Even a zero load requires that explicit mapping. Fixed and variable contributions are transferred separately; arbitrary component frames convert metre points to millimetres and N·m moments to N·mm. The preview and solver share the same transfer function. A downstream joint port still carries its subtree wrench **after** drive routing.

For DG250's declared 19 N upper-force case plus 2 N drag, the drive effort is21 N. The moving attachment receives−21 X N; the rear mount receives+21 X N. The guide's ideal axial reaction is then zero, while transverse and eccentric support moments remain. Rear-mount strength is still unassessed unless its actual CAD, material, mounting and explicit FEM ports are provided.

`verified` defaults false. A true declaration requires a `reference` to an installation check, and is still an external assertion. Unverified declared paths withhold conditional capacity. Unrouted actuators are listed as coverage gaps. Path closure does not qualify transmission strength, joints, contact compliance, fatigue or the complete installation.
