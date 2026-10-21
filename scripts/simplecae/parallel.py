"""Measured solver resource choices. These never change a mechanical criterion."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from pathlib import Path
import json
import math
import os
import platform

from .case import sha256, write_json


def available_cpus():
    """Respect process affinity as well as the machine's logical CPU count."""
    total = os.cpu_count() or 1
    try:
        total = min(total, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        if os.name == "nt":
            try:
                import ctypes
                kernel = ctypes.windll.kernel32
                kernel.GetCurrentProcess.restype = ctypes.c_void_p
                kernel.GetProcessAffinityMask.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
                mask, system = ctypes.c_size_t(), ctypes.c_size_t()
                if kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(),
                                                ctypes.byref(mask), ctypes.byref(system)):
                    total = min(total, mask.value.bit_count())
            except (AttributeError, OSError):
                pass
    return max(1, total)


def hardware_identity():
    from .execution import processor_label
    return {"platform": platform.system(), "machine": platform.machine(),
            "processor": processor_label(), "logical_cpus": os.cpu_count()}


def deck_work(path):
    """Small deck inventory, not a sparse-memory estimate or physics parser."""
    nodes = elements = 0
    section = ""
    contact = False
    for row in Path(path).read_text(encoding="ascii").splitlines():
        line = row.strip().upper()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            section = line.split(",")[0]
            contact |= section == "*CONTACT PAIR"
        elif section == "*NODE":
            nodes += 1
        elif section == "*ELEMENT":
            elements += 1
    return {"nodes": nodes, "elements": elements, "contact": contact}


def deck_field_coverage(path):
    """Expected fields of self-contained SimpleCAE C3D10 decks, not arbitrary INP."""
    nodes, elements, fixed = set(), set(), set()
    section = ""
    for row in Path(path).read_text(encoding="ascii").splitlines():
        line = row.strip().upper()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            tokens = [v.strip() for v in line.split(",")]
            section = ""
            if tokens[0] == "*NODE" and "NSET=NALL" in tokens:
                section = "nodes"
            elif tokens[0] == "*ELEMENT" and "ELSET=EALL" in tokens:
                if "TYPE=C3D10" not in tokens:
                    raise ValueError("Calibration requires SimpleCAE C3D10 EALL elements")
                section = "elements"
            elif tokens[0] == "*NSET" and "NSET=FIXED" in tokens:
                if "GENERATE" in tokens:
                    raise ValueError("Calibration requires the exported explicit FIXED node set")
                section = "fixed"
            continue
        if section in ("nodes", "elements"):
            (nodes if section == "nodes" else elements).add(int(line.split(",")[0]))
        elif section == "fixed":
            fixed.update(int(v.strip()) for v in line.split(",") if v.strip())
    if not nodes or not elements or not fixed or not fixed <= nodes:
        raise ValueError("Calibration requires complete exported NALL, C3D10 EALL and FIXED sets")
    ips = {(element, ip) for element in elements for ip in (1, 2, 3, 4)}
    return {"displacements": nodes, "reactions": fixed, "stresses": ips, "strains": ips}


def verify_field_coverage(fields, expected, expected_steps=None):
    if expected_steps is not None and any(
            not any(abs(time-step) <= 1e-7 for time in fields["fields"])
            for step in range(1, expected_steps+1)):
        raise ValueError("Calibration lacks a complete printed endpoint for a native load step")
    for time, row in fields["fields"].items():
        for name, ids in expected.items():
            if set(row[name]) != ids:
                raise ValueError(f"Calibration {name} coverage is incomplete or differs from the input at time {time}")


def default_profile_path():
    from .solver import ROOT
    return ROOT / ".tools" / f"parallel-{platform.system().lower()}.json"


def select_threads(ccx=None, inp=None, analysis_type="static"):
    from .execution import hardware_snapshot
    raw = os.environ.get("SIMPLECAE_SOLVER_THREADS", "auto")
    cpus = available_cpus()
    result = {"mode": raw, "available_cpus": cpus, "threads": 1,
              "available_memory_bytes": hardware_snapshot().get("available_memory_bytes"),
              "memory_prediction_available": False,
              "reason": "No applicable measured profile; serial execution.",
              "physics_changed": False}
    if raw != "auto":
        if not raw.isdecimal() or not 1 <= int(raw) <= cpus:
            raise ValueError("SIMPLECAE_SOLVER_THREADS must be auto or an integer from 1 to the available logical CPU count")
        return dict(result, threads=int(raw), reason="Explicit resource request.")
    if ccx is None or inp is None:
        return result
    profile_path = Path(os.environ.get("SIMPLECAE_RESOURCE_PROFILE") or default_profile_path())
    try:
        if not profile_path.is_file():
            return result
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if (profile["schema_version"] != "simplecae-parallel-1.0"
                or profile["solver_sha256"] != sha256(Path(ccx))
                or profile["hardware"] != hardware_identity()
                or profile["analysis_type"] != analysis_type):
            return dict(result, reason="Profile identity or analysis type differs; serial execution.")
        work = deck_work(inp)
        if (work["contact"] != profile["work"]["contact"]
                or work["nodes"] < profile["work"]["nodes"]):
            return dict(result, reason="Task is smaller or has a different contact family; serial execution.")
        candidates = []
        for sample in profile["samples"]:
            count, seconds = sample["threads"], sample["elapsed_seconds"]
            if (isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= cpus
                    and isinstance(seconds, (int, float)) and math.isfinite(seconds) and seconds > 0
                    and sample.get("field_parity_passed") is True
                    and sample.get("input_field_coverage_verified") is True
                    and sample.get("complete") is True):
                candidates.append(sample)
        serial = next((s for s in candidates if s["threads"] == 1), None)
        if serial is None:
            return dict(result, reason="Profile lacks a complete serial reference; serial execution.")
        # A small timing difference can be scheduler noise. This performance
        # threshold never participates in strength/contact/accuracy acceptance.
        useful = [s for s in candidates if s["threads"] == 1
                  or s["elapsed_seconds"] < .95 * serial["elapsed_seconds"]]
        best = min(useful, key=lambda s: s["elapsed_seconds"])
        return dict(result, threads=best["threads"], profile=str(profile_path.resolve()),
                    profile_sha256=sha256(profile_path),
                    reason="Fastest applicable measured configuration with complete field parity.",
                    reference_work=profile["work"], current_work=work,
                    performance_is_guaranteed=False)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration) as exc:
        return dict(result, reason=f"Unusable resource profile; serial execution: {exc}")


def _fields(path, analysis_type):
    if analysis_type != "static":
        raise ValueError("Calibration currently supports static decks, including staged contact; other families remain serial in auto mode")
    from .solver import parse_dat
    # Parse every final printed time independently, not only the service field.
    import re
    text = path.read_text(encoding="utf-8", errors="replace")
    times = sorted({float(t.replace("D", "E")) for t in re.findall(
        r"for set\s+\S+\s+and time\s+([+\-\d.EeDd]+)", text)})
    if not times:
        raise ValueError("Calibration deck has no printed field times")
    from .solver import dat_real
    fields = {}
    for t in times:
        row = parse_dat(path, time=t, exclude_sets=("BOLT_STATE",))
        row.pop("_source_directory", None)
        fields[t] = row
    # Include every printed contact/bolt row, too. Identifiers and textual
    # headers match exactly; floating data use the parity tolerance.
    rows = []
    for line in text.splitlines():
        tokens = []
        for token in line.split():
            try:
                value = dat_real(token)
                tokens.append(token if re.fullmatch(r"[+-]?\d+", token) else value)
            except ValueError:
                tokens.append(token)
        if tokens:
            rows.append(dict(enumerate(tokens)))
    return {"fields": fields, "native_rows": dict(enumerate(rows))}


def field_parity(reference, candidate):
    """Require identical coverage and all numerical fields, not just maxima."""
    import numpy as np
    def compare(a, b):
        if isinstance(a, dict):
            return isinstance(b, dict) and a.keys() == b.keys() and all(compare(a[k], b[k]) for k in a)
        if isinstance(a, (list, tuple, np.ndarray)):
            return np.shape(a) == np.shape(b) and bool(np.allclose(a, b, rtol=1e-6, atol=1e-9, equal_nan=False))
        if isinstance(a, (int, float, np.number)):
            return (isinstance(b, (int, float, np.number))
                    and bool(np.isfinite(a) and np.isfinite(b) and np.isclose(a, b, rtol=1e-6, atol=1e-9)))
        return a == b
    return compare(reference, candidate)


def calibrate(inp, out, ccx=None, candidates=None, timeout=DEFAULT_NATIVE_TIMEOUT, profile_path=None):
    """Explicit, retained same-deck experiments; never mutates the source deck."""
    from .solver import find_ccx, execute
    from .retention import retain_output
    inp, out = Path(inp).resolve(), Path(out).resolve()
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Calibration timeout must be finite and positive")
    binary = find_ccx(ccx)
    text = inp.read_text(encoding="ascii")
    if "*INCLUDE" in text.upper():
        raise ValueError("Calibration needs a self-contained deck; export referenced inputs first")
    work = deck_work(inp)
    if not work["nodes"] or not work["elements"] or "*STATIC" not in text.upper():
        raise ValueError("Calibration needs a nonempty static deck with complete field output")
    expected_fields = deck_field_coverage(inp)
    cpus = available_cpus()
    candidates = sorted({1, min(2, cpus), min(4, cpus)}) if candidates is None else candidates
    if (1 not in candidates or any(isinstance(n, bool) or not isinstance(n, int)
                                  or not 1 <= n <= cpus for n in candidates)):
        raise ValueError("Candidates must include serial and valid available CPU counts")
    out.mkdir(parents=True, exist_ok=False)
    expected_steps = sum(line.strip().upper().split(",")[0] == "*STEP" for line in text.splitlines())
    report = {"schema_version": "simplecae-parallel-1.0", "hardware": hardware_identity(),
              "solver_sha256": sha256(binary), "solver": str(binary),
              "input_sha256": sha256(inp), "analysis_type": "static", "work": work,
              "parity_relative_tolerance": 1e-6, "parity_absolute_tolerance": 1e-9,
              "samples": [], "meaning": "Same-deck performance and field parity, not product acceptance."}
    reference = None
    for count in sorted(set(candidates)):
        folder = out / f"threads-{count}"
        folder.mkdir()
        deck = folder / "job.inp"
        deck.write_bytes(inp.read_bytes())
        record = {"threads": count, "complete": False, "field_parity_passed": False,
                  "input_field_coverage_verified": False}
        try:
            execution = execute(binary, deck, timeout, threads=count)
            from .contact import completed_steps
            completed_steps(deck.with_suffix(".sta"), expected_steps)
            fields = _fields(deck.with_suffix(".dat"), "static")
            verify_field_coverage(fields, expected_fields, expected_steps)
            if count == 1:
                reference = fields
            record.update(complete=True, input_field_coverage_verified=True,
                          elapsed_seconds=execution["elapsed_seconds"],
                          field_parity_passed=reference is not None and field_parity(reference, fields),
                          native_work=execution["native_work"],
                          input_sha256=sha256(deck))
        except (OSError, ValueError, RuntimeError) as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        report["samples"].append(record)
        report["passed"] = all(s["complete"] and s["field_parity_passed"] for s in report["samples"])
        write_json(out / "profile.json", report)
        retain_output(folder, "compact")
        if count == 1 and not record["complete"]:
            break
    if profile_path:
        # The caller chooses the installation destination; a failed calibration
        # must not overwrite a previously usable profile.
        if not report["samples"][0]["complete"]:
            raise ValueError(f"Serial calibration failed; inspect {out / 'profile.json'}")
        write_json(Path(profile_path), report)
    return report
