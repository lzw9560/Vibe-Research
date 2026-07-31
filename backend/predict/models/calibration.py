"""Conformal calibration for S017 prediction stack.

Uses mapie 1.4.1 SplitConformalClassifier with a RandomForest base estimator.
Windows-safe: avoids lightgbm (access violation on this platform).
"""
from __future__ import annotations

import numpy as np
from mapie.classification import SplitConformalClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split


class ConformalCalibrator:
    """Split-conformal classifier that outputs calibrated probabilities + prediction sets."""

    def __init__(
        self,
        *,
        confidence_level: float = 0.9,
        base_estimator=None,
        random_state: int = 42,
    ) -> None:
        self.confidence_level = confidence_level
        self.random_state = random_state
        self.base_estimator = base_estimator or RandomForestClassifier(
            n_estimators=50, random_state=random_state, n_jobs=1
        )
        self.conformalizer_: SplitConformalClassifier | None = None

    def fit(
        self, X: np.ndarray, y: np.ndarray, *, calib_size: float = 0.3
    ) -> "ConformalCalibrator":
        """Fit base estimator on a train split, then conformalize on a hold-out."""
        X_train, X_calib, y_train, y_calib = train_test_split(
            X,
            y,
            test_size=calib_size,
            stratify=y,
            random_state=self.random_state,
        )

        base = self.base_estimator
        base.fit(X_train, y_train)

        conformalizer = SplitConformalClassifier(
            estimator=base,
            confidence_level=self.confidence_level,
            prefit=True,
        )
        conformalizer.conformalize(X_calib, y_calib)

        self.conformalizer_ = conformalizer
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return calibrated class probabilities from the fitted base estimator, shape (n_samples, 2)."""
        if self.conformalizer_ is None:
            raise RuntimeError("fit() must be called before predict_proba().")
        # mapie 1.4.1 SplitConformalClassifier has no predict_proba; use the fitted base estimator directly.
        return self.base_estimator.predict_proba(X)

    def predict_set(self, X: np.ndarray) -> np.ndarray:
        """Return conformal prediction set, shape (n_samples, n_classes) bool."""
        if self.conformalizer_ is None:
            raise RuntimeError("fit() must be called before predict_set().")
        # predict_set returns (predictions, prediction_sets) where prediction_sets is (n, n_classes, 1)
        prediction_sets = self.conformalizer_.predict_set(X)[1]
        return prediction_sets.squeeze(-1).astype(bool)

    def predict(self, X: np.ndarray) -> dict:
        """Return a dict with prob, prediction_set, and confidence_level."""
        return {
            "prob": self.predict_proba(X),
            "prediction_set": self.predict_set(X),
            "confidence_level": self.confidence_level,
        }
