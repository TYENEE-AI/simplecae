# Partition a physical load patch in CAD

A wrench acting far from a whole face's centroid can require reverse nodal
tractions. If a unilateral bearing contact is intended, partition the actual
contact area and use `distribution: "bearing_only"`. It only accepts a same-direction
force distribution whose resultant and moment match the stated load. Do not move
the application point merely to obtain acceptance.

For build123d/cadgen, the runnable
[`cadgen_partitioned_plate.py`](../examples/integration/cadgen_partitioned_plate.py)
splits a finished body at X=45 mm, then fuses the complementary pieces inside
`bd.SkipClean()`. Exported geometry stays one solid with unchanged volume and two
separate top faces. Do not subsequently call `clean()` or fuse outside that
context: same-domain unification can erase the patch.

For SimpleCADAPI, the notebook
[`scad_partitioned_hook.py`](../examples/integration/scad_partitioned_hook.py)
first completes its root fillet. It intersects the final body with a tool covering
the physical patch, cuts the same tool from a second copy, and reunites the two
complementary pieces with `union_rsolid(front, back, clean=False)`. Tag the final
top patch `interface.payload` and the final mounting face `interface.mount`.
The Boolean API takes solids positionally; the `clean=False` option is essential.

Run that notebook through [the native handoff](simplecad-handoff.md), using
`hook-interfaces.required.json`. Check `inspect` on the **saved STEP**, including
solid count, unchanged volume and the extra top face. Bind and review the orange
selection preview. A successful partition or load mapping does not establish
strength, friction, anchor capacity or product acceptance.
