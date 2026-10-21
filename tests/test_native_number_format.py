import numpy as np
import pytest
from simplecae.solver import native_real, validate_real_fields


def test_real_formatter_preserves_sign_and_exponent_within_native_field_width(tmp_path):
    values = [-1.224606353822e-18, -2.07670530951347e-5, 1.23456789012345e-123,
              -9.87654321098765e300, 0.]
    values += [float(x) for x in np.logspace(-300, 300, 121)]
    for value in values:
        token = native_real(value)
        assert len(token) <= 20
        assert float(token) == pytest.approx(value, rel=1e-12, abs=0)
    deck = tmp_path/"reference.inp"
    deck.write_text("*NODE\n1,"+",".join(native_real(x) for x in values[:3])+"\n")
    validate_real_fields(deck)
    bad = "-2.07670530951347e-05"
    assert len(bad) > 20 and abs(float(bad[:20])/float(bad)) > 1000
    deck.write_text("*NODE\n1,"+bad+",0,0\n")
    with pytest.raises(ValueError, match="F20.0"):
        validate_real_fields(deck)
    for value in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError, match="finite"):
            native_real(value)
