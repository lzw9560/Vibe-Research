"""Tests for predict.models.ensemble — S017 SoftVoteEnsemble.

TDD coverage:
(a) instantiate + fit does not raise (Windows histgb fallback)
(b) predict_proba shape (n,2), values in [0,1], rows sum≈1
(c) predict shape (n,), values in {0,1}
(d) backends() contains "catboost" and "histgb" or "lightgbm"
(e) determinism: same random_state → identical predict_proba
(f) predict_proba with single-sample input (1, n_features) does not raise
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.datasets import make_classification

from predict.models.ensemble import SoftVoteEnsemble


@pytest.fixture
def sample_data():
    X, y = make_classification(
        n_samples=200, n_features=10, n_informative=5,
        n_redundant=2, random_state=42,
    )
    return X, y


class TestSoftVoteEnsemble:
    def test_instantiate_and_fit(self, sample_data):
        X, y = sample_data
        model = SoftVoteEnsemble()
        result = model.fit(X, y)
        assert result is model

    def test_predict_proba_shape_and_bounds(self, sample_data):
        X, y = sample_data
        model = SoftVoteEnsemble().fit(X, y)
        proba = model.predict_proba(X)
        assert proba.shape == (len(X), 2)
        assert np.all(proba >= 0) and np.all(proba <= 1)
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    def test_predict_shape_and_values(self, sample_data):
        X, y = sample_data
        model = SoftVoteEnsemble().fit(X, y)
        pred = model.predict(X)
        assert pred.shape == (len(X),)
        assert set(np.unique(pred)).issubset({0, 1})

    def test_backends(self, sample_data):
        X, y = sample_data
        model = SoftVoteEnsemble().fit(X, y)
        backends = model.backends()
        assert "catboost" in backends
        assert ("histgb" in backends) or ("lightgbm" in backends)

    def test_determinism(self, sample_data):
        X, y = sample_data
        model1 = SoftVoteEnsemble().fit(X, y)
        model2 = SoftVoteEnsemble().fit(X, y)
        proba1 = model1.predict_proba(X)
        proba2 = model2.predict_proba(X)
        np.testing.assert_array_equal(proba1, proba2)

    def test_predict_proba_single_sample(self, sample_data):
        X, y = sample_data
        model = SoftVoteEnsemble().fit(X, y)
        proba = model.predict_proba(X[:1])
        assert proba.shape == (1, 2)
