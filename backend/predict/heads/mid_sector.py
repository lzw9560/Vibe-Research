"""Mid-sector head — S017 T2 scaffolding.

Interface-only implementation; feature subset maps to ``HEAD_FEATURE_SUBSETS``
under the key ``"mid_long"``.  train/predict/evaluate raise
``NotImplementedError``.
"""

from __future__ import annotations

from predict.feature_interface import HEAD_FEATURE_SUBSETS
from predict.heads.base import Head


class MidSectorHead(Head):
    """Mid-horizon (5-20d) sector-index prediction head."""

    name = "mid_sector"
    feature_subset = HEAD_FEATURE_SUBSETS.get("mid_long", ())

    def train(self, X, y) -> None:  # noqa: ANN001
        raise NotImplementedError("接口预留，待实现")

    def predict(self, stage: str, t: str) -> dict:
        raise NotImplementedError("接口预留，待实现")

    def evaluate(self) -> dict:
        raise NotImplementedError("接口预留，待实现")
