"""Require current physics/workflow tests in release evidence, including skips."""
from pathlib import Path
import json
from defusedxml import ElementTree

REQUIRED_TEST_MODULES = (
    "test_thermal_network", "test_thermal_solid", "test_thermal_solid_solver",
    "test_modal", "test_modal_solver", "test_modal_matching",
    "test_motion", "test_motion_solver", "test_durability",
    "test_stress_regions", "test_task", "test_complex_tasks",
    "test_rigid_calculation_tasks", "test_parallel",
)


def regression_coverage(path, returncode):
    root = ElementTree.parse(Path(path)).getroot()
    cases = list(root.iter("testcase"))
    records = {}
    for module in REQUIRED_TEST_MODULES:
        selected = [c for c in cases if module in c.get("classname", "").split(".")]
        failed = [c for c in selected if c.find("failure") is not None or c.find("error") is not None]
        skipped = [c for c in selected if c.find("skipped") is not None]
        records[module] = {"tests": len(selected), "failed": len(failed), "skipped": len(skipped),
                           "passed": bool(selected) and not failed and not skipped}
    failed = sum(c.find("failure") is not None or c.find("error") is not None for c in cases)
    skipped = sum(c.find("skipped") is not None for c in cases)
    return {"passed": returncode == 0 and bool(cases) and not failed
                      and all(r["passed"] for r in records.values()),
            "tests": len(cases), "failed": failed, "skipped": skipped,
            "required_module_coverage": records,
            "meaning": "Software and declared numerical references; not a physical product certification."}


def native_output_contracts(out, suites):
    """Check actual native suite outputs, not intentionally damaged pytest fixtures."""
    from .schemas import check_contract
    out = Path(out)
    count, errors = 0, []
    for suite in suites:
        if Path(suite).name != suite or suite in ("", ".", ".."):
            raise ValueError("Native suite must be a direct output directory")
        folder = out / suite
        if not folder.is_dir():
            errors.append({"suite": suite, "error": "Native suite output directory is missing"})
            continue
        for name, kind in (("result.json", "result"), ("signal.json", "signal"),
                           ("candidate-comparison.json", "comparison")):
            for file in folder.rglob(name):
                try:
                    check_contract(json.loads(file.read_text(encoding="utf-8-sig")), kind)
                    count += 1
                except Exception as exc:
                    errors.append({"contract_file": str(file.relative_to(out)), "error": str(exc)})
    return count, errors
