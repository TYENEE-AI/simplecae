import copy
import json
from pathlib import Path

import numpy as np
import pytest
from simplecae.parallel import (select_threads, hardware_identity, field_parity, deck_work, calibrate,
                                deck_field_coverage, verify_field_coverage)
from simplecae.case import sha256, write_json


def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLECAE_SOLVER_THREADS", "auto")
    monkeypatch.setattr("simplecae.parallel.available_cpus", lambda: 4)
    binary = tmp_path / "ccx"
    binary.write_bytes(b"identity only")
    deck = tmp_path / "job.inp"
    deck.write_text("*NODE,NSET=NALL\n1,0,0,0\n2,1,0,0\n*ELEMENT,TYPE=C3D10,ELSET=EALL\n1,1,2\n*NSET,NSET=FIXED\n1,\n*STEP\n*STATIC\n")
    profile = tmp_path / "profile.json"
    data = {"schema_version": "simplecae-parallel-1.0", "hardware": hardware_identity(),
            "solver_sha256": sha256(binary), "analysis_type": "static", "work": deck_work(deck),
            "samples": [{"threads": n, "elapsed_seconds": s, "complete": True,
                         "field_parity_passed": True,"input_field_coverage_verified":True}
                        for n, s in [(1, 10.), (2, 6.), (4, 8.)]]}
    write_json(profile, data)
    monkeypatch.setenv("SIMPLECAE_RESOURCE_PROFILE", str(profile))
    return binary, deck, profile, data


def test_auto_uses_measured_speed_not_largest_core_count(tmp_path, monkeypatch):
    binary, deck, _, _ = fixture(tmp_path, monkeypatch)
    r = select_threads(binary, deck)
    assert r["threads"] == 2 and not r["physics_changed"]
    assert select_threads(binary, deck, "thermal")["threads"] == 1
    monkeypatch.setattr("simplecae.parallel.available_cpus", lambda: 1)
    assert select_threads(binary, deck)["threads"] == 1


@pytest.mark.parametrize("change", ["binary", "hardware", "parity", "coverage", "corrupt", "smaller", "contact", "null"])
def test_profile_failure_falls_back_without_relaxing_physics(tmp_path, monkeypatch, change):
    binary, deck, profile, data = fixture(tmp_path, monkeypatch)
    if change == "binary":
        binary.write_bytes(b"changed")
    elif change == "hardware":
        data["hardware"]["processor"] = "different"
    elif change == "parity":
        for row in data["samples"][1:]:
            row["field_parity_passed"] = False
    elif change == "coverage":
        for row in data["samples"]:
            row.pop("input_field_coverage_verified")
    elif change == "smaller":
        data["work"]["nodes"] += 1
    elif change == "contact":
        data["work"]["contact"] = True
    write_json(profile, data)
    if change == "corrupt":
        profile.write_text("{")
    if change == "null":
        profile.write_text("null")
    r = select_threads(binary, deck)
    assert r["threads"] == 1 and not r["physics_changed"]


def test_every_field_and_coverage_matters_not_only_peak():
    a = {"stress": {1: np.array([1., 2., 3.]), 2: np.array([8., 9., 10.])},
         "reaction": {5: np.array([0., 2., 0.])}}
    b = copy.deepcopy(a)
    assert field_parity(a, b)
    b["stress"][1][0] += .1
    assert not field_parity(a, b)  # global peak stays 10
    b = copy.deepcopy(a)
    del b["reaction"][5]
    assert not field_parity(a, b)
    b = copy.deepcopy(a)
    b["stress"][1][0] = float("nan")
    assert not field_parity(a, b)


def test_calibration_serial_failure_never_installs_profile(tmp_path, monkeypatch):
    binary, deck, profile, _ = fixture(tmp_path, monkeypatch)
    old = profile.read_bytes()
    def crash(*args, **kwargs):
        raise RuntimeError("native crash")
    monkeypatch.setattr("simplecae.solver.execute", crash)
    with pytest.raises(ValueError, match="Serial calibration failed"):
        calibrate(deck, tmp_path / "run", binary, [1, 2], profile_path=profile)
    assert profile.read_bytes() == old
    receipt = json.loads((tmp_path / "run/profile.json").read_text())
    assert not receipt["samples"][0]["complete"] and "native crash" in receipt["samples"][0]["error"]


def test_matching_truncated_calibration_fields_do_not_qualify(tmp_path, monkeypatch):
    _,deck,_,_=fixture(tmp_path,monkeypatch)
    expected=deck_field_coverage(deck)
    complete={name:{key:[1.] for key in ids} for name,ids in expected.items()}
    fields={"fields":{1.:complete,2.:copy.deepcopy(complete),3.:copy.deepcopy(complete)}}
    verify_field_coverage(fields,expected,3)
    missing_stage=copy.deepcopy(fields)
    del missing_stage["fields"][1.]
    with pytest.raises(ValueError,match="load step"):
        verify_field_coverage(missing_stage,expected,3)
    # Both thread configurations omit the same interior IP at preload time.
    # Matching each other still cannot establish full input-model coverage.
    del fields["fields"][1.]["stresses"][(1,2)]
    assert field_parity(fields,copy.deepcopy(fields))
    with pytest.raises(ValueError,match="stresses coverage"):
        verify_field_coverage(fields,expected)
    with pytest.raises(ValueError,match="FIXED sets"):
        deck.write_text("*NODE,NSET=NALL\n1,0,0,0\n*ELEMENT,TYPE=C3D10,ELSET=EALL\n1,1\n")
        deck_field_coverage(deck)
