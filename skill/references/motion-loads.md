# Prescribed motion loads

Use for a robot/fixture that must accelerate, rotate or brake: first ask whether
drive demand or installation load could control the design. Do not run every
link's solid FEM merely because an assembly moves. This is a bounded development
capability; use the invoked CLI's `--version` to establish installed state.

## Agent entry

Use `motion-loads-1.0` with ordinary `check`, `analyze`, `design-check`, or a
one-file task whose selected check is `method: calculation` and whose
`result_criteria` names the required criterion IDs. An Agent writes the case.
The runnable reference is `scripts/verify_motion.py`; generated JSON schemas
also describe the contract. The output is compact JSON, a URDF snapshot and
the ordinary report; no mesh/cache is needed for this check.

Inputs:

- A connected SI URDF tree, physical positive COM inertia tensors and masses.
  Explicitly list any truly ideal massless frames. Payloads should be separate
  inertial links; gravity alone on an assumed point payload omits its rotational
  inertia. Inertial-origin rotation is applied, not discarded.
- Stationary fixed base, explicit base pose and gravity vector.
- Named states, each with the position, velocity and acceleration of **every**
  independent movable joint. Revolute/continuous quantities are rad, rad/s,
  rad/s²; prismatic quantities are m, m/s, m/s². A state may have external forces,
  moments and points with explicit link/world frames. These are actions **on**
  the modeled robot, not the robot's action on its workpiece.
- State-selection basis. No continuous interpolation, trajectory peak search or
  universal acceleration factor is implied. Include known extremes separately.
- Declared allowable output effort and applicable maximum absolute speed for a
  chosen joint, or separate mount force-norm/moment-norm limits. Record the rating
  basis (including any derating) and operating range. A URDF effort limit alone
  does not establish a usable speed-dependent motor/gearbox rating.

Missing criteria produce `indeterminate`. A state outside the supplied rating's
speed range cannot pass by comparing torque alone. Exact/near-equality to a limit
is indeterminate within a fixed roundoff guard. Unverified physical conditions
stay visible even when a *stated-model* load check passes.

## What is computed

World-frame forward kinematics includes angular acceleration, centripetal,
prismatic Coriolis and changing-axis terms. Recursive Newton–Euler propagation
retains COM translation and `I alpha + omega × (I omega)`. The world-inertia
tensor is about the COM; no accidental second parallel-axis shift is applied.
An independent whole-system momentum sum checks force and moment balance.

Results retain **every simultaneous state**, joint effort, full six-component
parent-on-child joint wrench, base reaction and opposite robot-on-base action,
world reference points, COM acceleration and inertial terms. Different criteria
can have different governing states. Component-wise extrema are not assembled
into a fictional combined load.

The Viewer offers a state selector, signed joint demands, installation force/
moment vectors and expandable link inertial contributions. It shows no invented
stress contour or physical deformation. Actual task execution stages and
pass/fail/insufficient revisions use the existing Viewer history.

## Following with a structural check

For a **separate stationary installation bracket**, use the Python helper:

```python
from simplecae.motion import mount_load_cases

fragment = mount_load_cases(
    motion_result, world_from_mount, port_selector,
    name="robot interface",
    separate_mount_basis="This fixed bracket is not included in any URDF mass",
)
```

`world_from_mount` is a proper 4×4 rigid transform whose translation is in metres.
The helper checks numerical evidence, transforms the **robot-on-mount** action
into mount axes, converts moments to N·mm and reference points to mm, and returns
existing solid `load_cases` plus a separate `motion_transfer` provenance receipt.
Assign only `fragment["load_cases"]` to a validated solid `2.0` template; retain
the receipt alongside it. Include the motion result and this transfer receipt
in the structural task's `sources`; changed motion needs regenerated load cases,
not silent reuse of a formerly passed mount result. Preserve real mount supports, material, all original
loads and mount self-weight in each case. A zero robot wrench yields an empty
external load list; use actual mount gravity if applicable, never a fictitious
nonzero force. The helper never invents port distribution, bolt restraint or
mount admissibility. Use the existing surface-force/moment transfer and its
numerical audits.

This does **not** convert moving links' distributed inertia into one point force.
Moving-link solid dynamics/body-force transfer is outside this first contract.
Even a stationary bracket's equivalent-static stress check does not establish
absence of resonant amplification; assess excitation/modal risk separately.

## Feedback and comparison

A valid failure identifies the criterion, governing state and actual joint or
mount location. Inspect gravity versus translational and rotational inertia
before proposing a change. A shorter lever arm may help; adding material can
increase drive demand. Do not prescribe slowing down as a CAD improvement unless
the user authorizes a changed operating requirement.

Comparisons freeze joint states, gravity, explicit loads, ratings and their
bases, base pose, inertial masses/COM/tensors, topology/axes and task ID. URDF
joint-origin geometry may vary. This compares the **same prescribed joint
states**, not the same end-effector trajectory or reach; retain a workspace/
clearance check. Changed inertials or task speeds are separate scenarios, not
automatically ranked CAD improvements. No arbitrary design-variable framework
is introduced in this first implementation.

Unsupported: moving/floating bases in the public task contract, mimic drive
transmissions, closed loops, joint friction/backlash, drive/control simulation,
flexible response, impact, fatigue, motor thermal duty and product acceptance.
Kernel moving-base references test Newton–Euler equations but do not broaden
the public fixed-base scope.

## Verification and primary reference

Tests cover translating/eccentric masses, analytical two-link Lagrange dynamics,
gyroscopic/inertial-frame terms, prismatic Coriolis acceleration, frame changes,
nonplanar branched-tree power balance, zero-motion static equivalence, missing
inertials/states, closed loops, out-of-range ratings, mutation, simultaneous load
transfer, separate extrema, and actual Agent workers with physical checks pending.

Method reference: [Lynch and Park, Modern Robotics §8.3](https://modernrobotics.northwestern.edu/nu-gm-book-resource/8-3-newton-euler-inverse-dynamics/).
Implementation uses world-frame Newton–Euler equations; no external code was
copied or new dependency added.
