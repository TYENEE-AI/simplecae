# Two-finger grip application and load generation

Use `gripper-task task.json --out FRESH_DIRECTORY`, then `analyze gripper.robot.json`. The task supplies a URDF, poses, two contact links, their link-local contact points and outward unit normals, workpiece mass, **normal force per finger**, friction and slip safety factor. No material, contact geometry, motor rating or measured friction is inferred.

For the complete1.2 workflow, use `check task.json --kind gripper-task` and `analyze-gripper task.json --out FRESH_DIRECTORY`. The optional explicit input version is `gripper-task-1.0`; old unversioned tasks remain accepted. `package_roots` maps URDF packages to paths relative to the task, and `massless_links` explicitly declares intentionally inertial-free frames. Neither is inferred. `force_measurement` generates required uncertainty endpoints; see [force uncertainty](force-uncertainty.md).

General extra forces/couples go in `additional_robot_loads`. Names also listed in `workpiece_load_names` are explicitly included in the grip/object wrench demand; wire drag and unrelated robot loads are not automatically object loads. Finite pads can therefore reject an object twist even if its net weight passes. Selected object loads must use contact links and compatible frames. `probes` and `actuation_reactions` pass through the canonical robot contracts. See [finite pads](finite-pad-grasps.md), [task measurements](task-measurements.md) and [drive paths](actuation-paths.md).

```json
{
  "task_id":"desktop-gripper-loads",
  "model_path":"robot/gripper.urdf",
  "poses":[{"name":"grasp25","joints":{"jaw_slide":0.007}}],
  "contacts":[
    {"link":"fixed_pad","position_m":[0,0.004,0.047],"normal_link":[-1,0,0]},
    {"link":"moving_pad","position_m":[0,0.004,0.047],"normal_link":[1,0,0]}
  ],
  "payload_mass_kg":0.25,
  "normal_force_per_finger_n":12,
  "friction_coefficient":0.3,
  "acceleration_along_gravity_m_s2":0,
  "slip_safety_factor":2
}
```

The generated load case splits workpiece weight equally, keeps opposing normal-force commands fixed, and applies any supplied worst-case acceleration along world gravity at each link-local contact point. Force/moment `frame` and optional `position_frame` are independent; the latter defaults to `frame` for older cases. Relative URDF and component paths resolve against the task file, not the output folder.

Required tangential resistance is `slip_safety_factor * m * (|g| + a)`. Available resistance is `2 * mu * normal_force_per_finger`. Do not count a load factor twice: acceleration and a safety factor are separate explicit inputs. The 250g/12N/mu=0.3 example with safety factor 2 and no acceleration requires 4.903N and offers 7.2N; mu=0.2 offers 4.8N and fails, even with passing structure and actuator criteria. At zero friction no favorable margin is returned.

Actual robot cases carry `grasp` references to the workpiece payload shares, two fixed normal loads and optional named extra tangential loads. Those references must belong to the two contact links. The assessment checks equal opposing normals perpendicular to gravity and gravity-aligned tangential demand for every pose. Unequal/angled jaws, lateral loads or load reversal need a different contact-wrench model and are rejected by this simplified balance. Object rotational wrench closure, local pressure, pad compression, contact changes and actual friction calibration remain outside it.

Grip failure enters the robot status, bottleneck and feedback. A missing requested assessment suppresses favorable comparison signals. A conditional payload multiplier is additionally limited by friction and remains unavailable until both `grasp.conditions.friction_verified` and `force_verified`, plus the robot/component conditions, are verified. A successful equilibrium calculation is not a measurement of either parameter or an overall gripper rating.

Optional task fields include `components`, `required_components`, `additional_robot_loads` (for explicit guide drag or other robot loads), `effort_safety_factor`, the four robot `conditions`, and `grasp_conditions`. When absent, physical conditions remain false. For a real product, derive continuous drive capability from the selected motor/transmission at service speed, and validate the grip-force control and minimum friction experimentally.
