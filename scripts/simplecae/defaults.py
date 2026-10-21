"""Configurable execution/display starting points, never numerical acceptance."""
from threading import TIMEOUT_MAX as MAX_WAIT_SECONDS
DEFAULT_EXECUTION_BUDGET = 3000
DEFAULT_NATIVE_TIMEOUT = 3000
DEFAULT_PREVIEW_TRIANGLES = 250_000
DEFAULT_INPUT_TRIANGLES = 250_000
DEFAULT_VIEWER_FILE_BYTES = 256*1024**2
DEFAULT_STRUCTURAL_ELEMENTS = 500_000
DEFAULT_THERMAL_ELEMENTS = 100_000
DEFAULT_MODAL_ELEMENTS = 20_000
DEFAULT_THERMAL_FIELD_VALUES = 30_000_000
PLANNING_HEADROOM = 1.5


def execution_defaults():
    return {'worker_budget_seconds': DEFAULT_EXECUTION_BUDGET,
            'native_timeout_seconds': DEFAULT_NATIVE_TIMEOUT,
            'preview_triangles': DEFAULT_PREVIEW_TRIANGLES,
            'input_triangles': DEFAULT_INPUT_TRIANGLES,
            'viewer_file_bytes': DEFAULT_VIEWER_FILE_BYTES,
            'structural_elements': DEFAULT_STRUCTURAL_ELEMENTS,
            'thermal_elements': DEFAULT_THERMAL_ELEMENTS,
            'modal_elements': DEFAULT_MODAL_ELEMENTS,
            'thermal_field_values': DEFAULT_THERMAL_FIELD_VALUES,
            'planning_headroom': PLANNING_HEADROOM,
            'meaning': 'Starting allowances only; explicit user limits win. No accuracy/acceptance changes or memory-fit guarantee.'}
