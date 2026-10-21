import numpy as np
import pytest
from simplecae.modal_matching import match


def test_repeated_modes_use_subspace_not_arbitrary_eigenvectors():
    a = np.eye(3).reshape((3, 1, 3))
    theta = .71
    rotation = np.array([[np.cos(theta), np.sin(theta), 0],
                         [-np.sin(theta), np.cos(theta), 0], [0, 0, -1]])
    b = (rotation@np.eye(3)).reshape((3, 1, 3))
    result = match([10, 10, 30], [10.01, 10.01, 30.05], a, b, [1])
    assert result["passed"]
    assert len(result["groups"]) == 2
    assert result["groups"][0]["min_subspace_mac"] == pytest.approx(1)


def test_crossing_modes_are_not_accepted_by_sorted_frequencies():
    a = np.eye(3).reshape((3, 1, 3))
    b = a[[1, 0, 2]]
    result = match([10, 11, 30], [10.01, 11.01, 30.01], a, b, [1])
    assert not result["passed"]
    assert result["mapping"]["0"] == 1
    assert result["mapping"]["1"] == 0


def test_equal_frequencies_do_not_hide_wrong_shapes_or_missing_modes():
    a = np.eye(4)[:2].reshape((2, 2, 2))
    b = np.eye(4)[2:].reshape((2, 2, 2))
    assert not match([10, 20], [10, 20], a, b, [1, 1])["passed"]
    with pytest.raises(ValueError):
        match([10, 20], [10], a, b[:1], [1, 1])
    with pytest.raises(ValueError, match="Rank-deficient"):
        match([10, 10], [10, 10], np.repeat(a[:1], 2, axis=0), b, [1, 1])


def test_frequency_change_cannot_hide_behind_good_mac():
    a = np.eye(3).reshape((3, 1, 3))
    assert not match([10, 20, 30], [10, 20, 31], a, a, [1])["passed"]


def test_more_than_ten_modes_preserve_hash_after_json_roundtrip():
    import json
    from simplecae.signals import digest
    a = np.eye(12).reshape((12, 4, 3))
    frequencies = np.arange(1, 13)*10.
    result = match(frequencies, frequencies, a, a, np.ones(4))
    assert result["passed"]
    assert digest(result) == digest(json.loads(json.dumps(result)))
