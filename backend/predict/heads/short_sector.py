"""Short-sector head — S017 T2 scaffolding.

Interface-only implementation; train/predict/evaluate raise
``NotImplementedError`` until the ensemble/regime/calibration models land
in S017 T3/T4.
"""

from __future__ import annotations

from predict.feature_interface import HEAD_FEATURE_SUBSETS
from predict.heads.base import Head


class ShortSectorHead(Head):
    """Short-horizon (1-3d) sector-index prediction head."""

    name = "short_sector"
    feature_subset = HEAD_FEATURE_SUBSETS["short_sector"]

    def train(self, X, y) -> None:  # noqa: ANN001
        raise NotImplementedError(
            "S017 T3: 待 ensemble/regime/calibration 模型落地"
        )

    def predict(self, stage: str, t: str) -> dict:
        raise NotImplementedError(
            "S017 T3: 待 ensemble/regime/calibration 模型落地"
        )

    def evaluate(self) -> dict:
        raise NotImplementedError(
            "S017 T3: 待 ensemble/regime/calibration 模型落地"
        )
