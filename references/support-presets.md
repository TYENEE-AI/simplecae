# Choose the actual restrained displacement components

The solid `prepare` form now supports multiple selected material regions with explicit directional presets. The case API remains explicit `dofs:[...]`; the preset compiler produces those same values rather than hiding a new boundary type.

| Preset | Axis meaning | Generated translation DOFs |
|---|---|---|
| `fixed` | None | X/Y/Z |
| `normal_seat` | Seat normal | Selected axis only |
| `sliding_guide` | Sliding axis | Other two axes |
| `pin_position` | Declared pin axis | Other two axes |
| `axial_stop` | Stop direction | Selected axis only |

Solid axes are the imported analysis axes; assembly axes are world axes. Arbitrary45° restraints are not a component subset: explicitly rotate the analysis frame or build a detailed connection model. Never silently convert them into a full clamp.

A whole face may carry a load in a free direction while guiding other directions:
for example, an XY-guided press shoe can receive a Z force on its top face. The
mesher checks the distributed nodal forces, including any applied couple, in the
actual support axes. A force component acting in a constrained direction on the
same face is rejected rather than discarded. Fully constrained shared faces remain
rejected. This does not add an inferred guide or change any declared DOF.

Python example:

```python
from simplecae.support_presets import support_from_preset
guide = support_from_preset("guide", side_face, "sliding_guide", "x")
stop = support_from_preset("real_stop", stop_face, "axial_stop", "x")
case["supports"] = [guide, stop]
```

`side_face` and `stop_face` are normal whole-face selectors with the appropriate source hash when selecting IDs. An assembly recipe also takes `body="..."`. Equivalent JSON stores the actual `dofs:[2,3]` and `dofs:[1]`. The guide records chosen presets in provenance for explanation, while the physical task contract uses the actual regions and DOFs.

A selected region constrains each selected node's displacement components. Its distribution can also prevent rigid rotations. **Pin-position** means a two-direction positional idealization; it is not a frictionless cylindrical normal-only contact, clearance fit, free-turning hinge or real pin-bearing stress model. Seat/stop constraints resist both signs; separation and one-sided contact are absent. Select genuinely representative regions and leave `supports_represent_actual_mounting` false until their applicability is supported.

The guided form shows each recipe's meaning and actual XYZ components. Add only real mounting regions, guides, seats, stops or drives. Its preview-node rank check reports remaining common rigid modes (Tx/Ty/Tz translations and Rx/Ry/Rz rotations). It refuses to export an underconstrained case and suggests adding the missing real restraint. These surface-node diagnostics do not establish stiffness, independent-body mechanism freedom or correct contact behavior. The actual volume mesh repeats the rigid-mode check before solving, and `preview` also displays its surface diagnostic without a structural verdict.

The verified guide-plus-stop reference leavesX translation free without the stop and rejects that case before the solver. With the declared real stop and an analyticν=0 reference material, axial displacement agrees with P·L/(E·A). DG250's separate normal-X seat plus Y/Z pin-position recipe reproduces its explicitly declared fixed-finger fixture; actual mounting truth, sensor flexibility and contact remain unverified.
