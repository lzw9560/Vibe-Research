"""Regime-switching model using GaussianMixture.

Windows: uses sklearn GaussianMixture (hmmlearn GaussianHMM hangs on Windows).
Linux/macOS: TODO — switch to GaussianHMM when cross-platform deployed.
"""

from __future__ import annotations

import numpy as np
from sklearn.mixture import GaussianMixture


class GaussianMixtureRegimeSwitcher:
    """2-3 state regime identification via GaussianMixture.

    Labels regimes by the first dimension (return) of each component mean,
    sorted descending: "bull", then "neutral", then "bear".
    """

    def __init__(self, n_components: int = 3, random_state: int = 42) -> None:
        self.n_components = n_components
        self.random_state = random_state
        self.model: GaussianMixture | None = None
        self._label_map: dict[int, str] | None = None

    def fit(self, features: np.ndarray) -> GaussianMixtureRegimeSwitcher:
        """Fit GaussianMixture on features (n_samples, n_features).

        Typical features: [daily_return, volatility].
        """
        self.model = GaussianMixture(
            n_components=self.n_components,
            random_state=self.random_state,
        )
        self.model.fit(features)
        self._label_map = self._build_label_map()
        return self

    def predict_state(self, features: np.ndarray) -> np.ndarray:
        """Return regime label for each sample."""
        if self.model is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
        return self.model.predict(features)

    def regime_labels(self) -> dict[int, str]:
        """Return label mapping {regime_index: label}.

        Labels are assigned based on the first dimension of each component mean,
        sorted descending: highest return -> "bull", lowest -> "bear".
        For n_components=3: "bull", "neutral", "bear".
        For n_components=2: "bull", "bear".
        """
        if self._label_map is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
        return self._label_map.copy()

    def backend(self) -> str:
        """Return the backend identifier.

        Returns:
            "gaussian_mixture" — current backend (Windows/Linux/macOS compatible).
            # TODO: Linux/macOS 跨平台部署时切 GaussianHMM（Windows hang 不可用）
        """
        return "gaussian_mixture"

    def _build_label_map(self) -> dict[int, str]:
        """Build label map based on component means sorted by first dimension."""
        if self.model is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
        means = self.model.means_[:, 0]
        sorted_indices = np.argsort(means)[::-1]
        if self.n_components == 3:
            labels = ["牛", "震荡", "熊"]
        elif self.n_components == 2:
            labels = ["牛", "熊"]
        else:
            raise ValueError(f"Unsupported n_components: {self.n_components}")
        return {idx: label for idx, label in zip(sorted_indices, labels)}
