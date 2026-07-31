"""Ensemble model — SoftVoteEnsemble (S017).

HistGradientBoosting + CatBoost soft-voting ensemble.
On Windows lightgbm fit() raises OSError (access violation); we gracefully
fall back to HistGradientBoostingClassifier.  On Linux/macOS the same code
path will try lightgbm first and succeed — no platform sniffing needed.

TODO: Cross-platform backend selection — on Linux/macOS prefer LightGBM;
      keep HistGB as universal fallback.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import numpy as np
from catboost import CatBoostClassifier
from sklearn.ensemble import HistGradientBoostingClassifier

logger = logging.getLogger(__name__)


class SoftVoteEnsemble:
    """Soft-voting ensemble of a tree booster and CatBoost.

    Parameters
    ----------
    catboost_kwargs:
        Passed to ``CatBoostClassifier``.
    histgb_kwargs:
        Passed to ``HistGradientBoostingClassifier`` (or ``LGBMClassifier``
        on platforms where lightgbm works).
    """

    def __init__(
        self,
        *,
        catboost_kwargs: dict[str, Any] | None = None,
        histgb_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._catboost_kwargs = catboost_kwargs or {}
        self._histgb_kwargs = histgb_kwargs or {}
        self._tree: Any | None = None
        self._cat: Any | None = None
        self._backend: str = ""

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SoftVoteEnsemble":
        """Fit both base models.  Returns self."""
        # ---- tree booster (lightgbm preferred, histgb fallback) ----
        try:
            if sys.platform == "win32":
                # LightGBM fit() hangs on Windows (OSError/access violation);
                # force immediate fallback to avoid un-catchable hang.
                raise OSError(
                    "lightgbm disabled on Windows (known hang)"
                )
            from lightgbm import LGBMClassifier

            self._tree = LGBMClassifier(
                n_estimators=50,
                random_state=42,
                **self._histgb_kwargs,
            )
            self._tree.fit(X, y)
            self._backend = "lightgbm"
        except (OSError, Exception) as exc:  # noqa: BLE001
            logger.debug("lightgbm fit failed (%s), falling back to histgb", exc)
            # Windows: avoid OpenMP deadlock when stale Python processes exist
            if sys.platform == "win32":
                os.environ["OMP_NUM_THREADS"] = "1"
            self._tree = HistGradientBoostingClassifier(
                max_iter=100,
                random_state=42,
                **self._histgb_kwargs,
            )
            self._tree.fit(X, y)
            self._backend = "histgb"

        # ---- catboost ----
        cat_seed = self._catboost_kwargs.get("random_seed", 42)
        cat_kwargs = {
            **self._catboost_kwargs,
            "iterations": 50,
            "verbose": 0,
            "random_seed": cat_seed,
        }
        self._cat = CatBoostClassifier(**cat_kwargs)
        self._cat.fit(X, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return averaged predict_proba of both models."""
        if self._tree is None or self._cat is None:
            raise RuntimeError("Model not fitted yet.")
        p_tree = self._tree.predict_proba(X)
        p_cat = self._cat.predict_proba(X)
        return (p_tree + p_cat) / 2.0

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return argmax of averaged probabilities."""
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1)

    def backends(self) -> list[str]:
        """Return list of actually-used backend names."""
        return [self._backend, "catboost"]
