"""Tests for predict.models.calibration — ConformalCalibrator.

TDD RED→GREEN→REFACTOR.
"""
import pytest
import numpy as np
from sklearn.datasets import make_classification

from predict.models.calibration import ConformalCalibrator


@pytest.fixture
def synthetic_binary() -> tuple[np.ndarray, np.ndarray]:
    """Return (X, y) for a simple binary classification problem."""
    X, y = make_classification(
        n_samples=200,
        n_features=10,
        n_informative=5,
        n_redundant=2,
        n_classes=2,
        random_state=42,
    )
    return X, y


class TestConformalCalibrator:
    # ---------- (a) instantiate + fit ----------
    def test_instantiate_and_fit_does_not_raise(self, synthetic_binary):
        X, y = synthetic_binary
        cal = ConformalCalibrator(confidence_level=0.9, random_state=42)
        result = cal.fit(X, y)
        assert result is cal
        assert hasattr(cal, "conformalizer_")

    # ---------- (b) predict_proba shape & bounds ----------
    def test_predict_proba_shape_and_bounds(self, synthetic_binary):
        X, y = synthetic_binary
        cal = ConformalCalibrator(confidence_level=0.9, random_state=42)
        cal.fit(X, y)
        prob = cal.predict_proba(X)
        assert prob.shape == (len(X), 2)
        assert np.all(prob >= 0)
        assert np.all(prob <= 1)
        np.testing.assert_allclose(prob.sum(axis=1), 1.0, atol=1e-6)

    # ---------- (c) predict_set returns non-empty boolean set ----------
    def test_predict_set_non_empty_boolean(self, synthetic_binary):
        X, y = synthetic_binary
        cal = ConformalCalibrator(confidence_level=0.9, random_state=42)
        cal.fit(X, y)
        pset = cal.predict_set(X)
        assert pset.shape[0] == len(X)
        assert pset.dtype == bool
        # At least one True per row for a 90% confidence conformal set
        assert pset.any(axis=1).all()

    # ---------- (d) predict returns expected dict keys ----------
    def test_predict_returns_dict_with_keys(self, synthetic_binary):
        X, y = synthetic_binary
        cal = ConformalCalibrator(confidence_level=0.9, random_state=42)
        cal.fit(X, y)
        out = cal.predict(X)
        assert isinstance(out, dict)
        assert "prob" in out
        assert "prediction_set" in out
        assert "confidence_level" in out
        assert out["confidence_level"] == 0.9
        assert np.array_equal(out["prob"], cal.predict_proba(X))
        assert np.array_equal(out["prediction_set"], cal.predict_set(X))

    # ---------- (e) determinism: same random_state gives identical results ----------
    def test_determinism_same_random_state(self, synthetic_binary):
        X, y = synthetic_binary
        cal1 = ConformalCalibrator(confidence_level=0.9, random_state=42)
        cal2 = ConformalCalibrator(confidence_level=0.9, random_state=42)
        cal1.fit(X, y)
        cal2.fit(X, y)
        prob1 = cal1.predict_proba(X)
        prob2 = cal2.predict_proba(X)
        np.testing.assert_array_equal(prob1, prob2)
        pset1 = cal1.predict_set(X)
        pset2 = cal2.predict_set(X)
        np.testing.assert_array_equal(pset1, pset2)

    # ---------- (f) small dataset (n=50) does not raise ----------
    def test_fit_small_dataset_does_not_raise(self):
        X, y = make_classification(
            n_samples=50,
            n_features=8,
            n_informative=4,
            n_redundant=2,
            n_classes=2,
            random_state=7,
        )
        cal = ConformalCalibrator(confidence_level=0.9, random_state=42)
        cal.fit(X, y, calib_size=0.3)
        prob = cal.predict_proba(X)
        assert prob.shape == (len(X), 2)
