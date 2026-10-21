import json
from pathlib import Path
from simplecae.release_checks import REQUIRED_TEST_MODULES, regression_coverage, native_output_contracts


def xml(tmp_path, *, missing=None, skipped=None, failed=None):
    path = tmp_path / "results.xml"
    records = []
    for name in REQUIRED_TEST_MODULES:
        if name == missing:
            continue
        child = '<skipped/>' if name == skipped else '<failure/>' if name == failed else ''
        records.append(f'<testcase classname="tests.{name}" name="reference">{child}</testcase>')
    path.write_text('<testsuites><testsuite>'+''.join(records)+'</testsuite></testsuites>')
    return path


def test_green_process_without_new_physics_cannot_qualify_release(tmp_path):
    report = regression_coverage(xml(tmp_path, missing="test_modal_solver"), 0)
    assert not report["passed"]
    assert report["required_module_coverage"]["test_modal_solver"]["tests"] == 0


def test_skipped_or_failed_native_reference_is_not_coverage(tmp_path):
    assert not regression_coverage(xml(tmp_path, skipped="test_thermal_solid_solver"), 0)["passed"]
    assert not regression_coverage(xml(tmp_path, failed="test_motion_solver"), 0)["passed"]
    assert not regression_coverage(xml(tmp_path), 1)["passed"]
    assert regression_coverage(xml(tmp_path), 0)["passed"]


def test_native_contract_scan_does_not_misclassify_negative_test_fixtures(tmp_path):
    native = tmp_path / "standard"
    fixture = tmp_path / "pytest-tmp" / "deliberately_damaged"
    native.mkdir()
    fixture.mkdir(parents=True)
    (native / "result.json").write_text(json.dumps({
        "schema_version": "2.0", "analysis": "linear_static", "status": "invalid",
        "case": {}, "evaluation_signal": {}, "error": "Expected rejection reference",
    }), encoding="utf8")
    (fixture / "result.json").write_text("{broken", encoding="utf8")
    count, errors = native_output_contracts(tmp_path, ["standard"])
    assert count == 1 and not errors


def test_malformed_or_missing_real_native_output_still_blocks_release(tmp_path):
    native = tmp_path / "standard"
    native.mkdir()
    (native / "result.json").write_text("{}", encoding="utf8")
    count, errors = native_output_contracts(tmp_path, ["standard", "missing-suite"])
    assert count == 0 and len(errors) == 2
    assert errors[0]["contract_file"] == str(Path("standard") / "result.json")
    assert errors[1]["suite"] == "missing-suite"
