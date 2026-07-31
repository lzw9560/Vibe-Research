"""Head base class — S017 T2.

Defines the abstract interface that every prediction head must implement.
All four heads (short_sector, short_stock, mid_sector, mid_stock) inherit
from this ABC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Head(ABC):
    """Abstract base class for a prediction head.

    Each head models a specific ``(time_horizon, granularity)`` pair and
    declares the feature subset it consumes.
    """

    # class-level contract (must be overridden in concrete subclasses)
    name: str = ""
    feature_subset: tuple[str, ...] = ()

    @abstractmethod
    def train(self, X, y) -> None:
        """Train the head on feature matrix *X* and label vector *y*."""
        ...

    @abstractmethod
    def predict(self, stage: str, t: str) -> dict:
        """Return prediction for *stage* at date *t*.

        Returns
        -------
        dict
            Keys: ``prob``, ``quantiles``, ``shap_topk``, ``features_used``.
        """
        ...

    @abstractmethod
    def evaluate(self) -> dict:
        """Evaluate the trained head and return metrics.

        Returns
        -------
        dict
            Arbitrary evaluation dictionary.
        """
        ...
