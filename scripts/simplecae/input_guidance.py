"""Actionable file handoff boundaries; never infer missing geometry or units."""
from pathlib import Path


def require_fem_format(path):
    if Path(path).suffix.lower() == '.3mf':
        raise ValueError(
            '3MF is not a supported FEM input, including mm and inch archives. '
            'Regenerate STEP from the original text-to-cad Python source: add '
            '@step(out="STEP/model.step") (from cadgen import step) to its model '
            'function, then run <CADGEN_PY> model.py in the separate cadgen environment. '
            'Inspect the regenerated STEP dimensions. For URDF component FEM provide '
            'one <link_name>.step per analyzed link; do not apply its visual mesh '
            'scale=0.001 again to STEP. Renaming or wrapping a 3MF is not STEP export.')
