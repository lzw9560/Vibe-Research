"""Mid-stock head — S017 T2 scaffolding.

Interface-only implementation; feature subset is empty (to be defined in a
later stage).  train/predict/evaluate raise ``NotImplementedError``.
"""

from __future__ import annotations

from predict.heads.base import Head


class MidStockHead(Head):
    """Mid-horizon (5-20d) individual-stock prediction head."""

    name = "mid_stock"
    feature_subset: tuple[str, ...] = ()

    def train(self, X, y) -> None:  # noqa: ANN001
        raise NotImplementedError("接口预留，待实现")

    def predict(self, stage: str, t: str) -> dict:
        raise NotImplementedError("接口预留，待实现")

    def evaluate(self) -> dict:
        raise NotImplementedError("接口预留，待实现")
