"""Independent Fourier-series check for the explicitly bounded slab reference."""
import argparse
import json
from pathlib import Path

import numpy as np

from simplecae.case import write_json
from simplecae.thermal_solid import signal


def verify(path):
    result = json.loads(path.read_text(encoding="utf-8"))
    case = result["case"]
    if case["mode"] != "transient" or len(case["boundaries"]) != 2:
        raise ValueError("Reference requires a transient slab with exactly two fixed-temperature ends")
    bounds = np.array(case["model"]["expected_bbox_mm"])*.001
    boundaries = sorted(case["boundaries"], key=lambda b: b["selector"]["position_mm"])
    for b, x in zip(boundaries, bounds[:, 0]):
        if (b["type"] != "temperature" or b["selector"]["type"] != "plane"
                or b["selector"]["axis"] != "x" or abs(b["selector"]["position_mm"]*.001-x) > 1e-9
                or b["temperature_c"] != case["initial_temperature_c"]):
            raise ValueError("Reference requires equal isothermal x ends and matching initial temperature")
    level = result["levels"][2]
    box_volume = float(np.prod(bounds[1]-bounds[0]))
    if not np.isclose(level["mesh"]["geometry"]["volume_mm3"]*1e-9, box_volume, rtol=1e-8, atol=0):
        raise ValueError("The imported body is not the full reference box")
    directory = path.parent/level["directory"]
    with np.load(directory/"mesh.npz", allow_pickle=False) as mesh, \
         np.load(directory/"thermal-fields.npz", allow_pickle=False) as fields:
        x, time = mesh["xyz"][:, 0]*.001-bounds[0, 0], fields["time_s"]
        material = case["material"]
        length = bounds[1, 0]-bounds[0, 0]
        k, rho, cp = (material[key] for key in ("conductivity_w_mk", "density_kg_m3", "specific_heat_j_kgk"))
        q, initial = case["volumetric_heat_w_m3"], case["initial_temperature_c"]
        reference = np.broadcast_to(initial+q/(2*k)*x*(length-x), fields["temperature_c"].shape).copy()
        for n in range(1, 200, 2):
            reference -= (4*q*length**2/(k*np.pi**3*n**3)
                * np.exp(-k/(rho*cp)*(n*np.pi/length)**2*time[:, None])
                * np.sin(n*np.pi*x/length)[None, :])
        reference[0] = initial
        error = float(np.max(np.abs(fields["temperature_c"]-reference)))
    valid = signal(result)["valid_for_comparison"]
    receipt = {"reference": "Insulated-side rectangular slab, equal isothermal ends, uniform volume heating; "
               "Fourier sine series with 100 odd terms; exact initial row.",
               "max_full_history_node_error_c": error, "reference_tolerance_c": .1,
               "numerical_gates_unchanged": result["verification"], "valid_signal": valid,
               "whole_product_pass_available": False, "passed": error < .1 and valid}
    write_json(path.parent/"analytical-verification.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    receipt = verify(args.result.resolve())
    print(json.dumps(receipt))
    if not receipt["passed"]:
        raise SystemExit(1)
