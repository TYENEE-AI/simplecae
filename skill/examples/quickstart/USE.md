# Two short first-use paths

For the developer preview's shortest STEP path, start with [the three-state examples](../preview/USE.md) and the `quickstart` command. The gripper path below is an advanced coverage example.

From the full skill folder:

```powershell
.\.venv\Scripts\python.exe scripts/simplecae_cli.py examples --out outputs/basic-001
.\.venv\Scripts\python.exe scripts/simplecae_cli.py preview outputs/basic-001/bracket.case.json --out outputs/bracket-loads-001
.\.venv\Scripts\python.exe scripts/simplecae_cli.py analyze outputs/basic-001/bracket.case.json --out outputs/bracket-analysis-001
.\.venv\Scripts\python.exe scripts/simplecae_cli.py analyze-gripper examples/quickstart/gripper-task.json --out outputs/gripper-task-001
```

The first path generates a known bracket/reference CAD and analyzes the stated material/fixture/load. Check the generated filename inventory; these are reference examples, not your actual mounting or material data.

The second uses a small SI-frame URDF with box visuals, explicit16×16 mm contact footprints, three gaps and the declared15–17 N measured interval±2 N. It analyzes both13 N and19 N endpoints. All physical verification flags remainfalse. The example has **no component FEM**; a grip/static-effort pass does not prove those fingers strong or the robot safe. The report exposes this missing coverage.

Copy inputs before changing them. To provoke a declared grip failure, lower the friction coefficient or add a couple in `additional_robot_loads` on a contact link and list its name in `workpiece_load_names`. This explicitly includes it in the object's grip demand; unrelated wire/guide loads remain robot loads. Do not silently update physical verification flags or reinterpret the example rating as real hardware evidence.

To use your own CAD, `prepare`/`inspect` and the relevant templates produce explicit component cases and ports. The full DG250 project used to validate this release is separate from the distributable skill; manufacturer CAD and private engineering outputs are not bundled.
