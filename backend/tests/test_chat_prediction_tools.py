"""Tests for chat.TOOLS prediction tools — S017 T11.

Verifies the two new tools dispatch through _exec_tool and return the
research-grade payload + disclaimer (no live network).
"""

from __future__ import annotations
import json

import chat
from predict.predict import Snapshot, cascade_store

_FORBIDDEN = ("买入", "卖出", "止损", "止盈", "荐股", "保证收益", "承诺收益")


def _tool_names() -> set[str]:
    return {t["function"]["name"] for t in chat.TOOLS}


def test_tools_registered() -> None:
    names = _tool_names()
    assert "prediction_short_sector" in names
    assert "prediction_intraday_framework" in names


def test_intraday_framework_tool_payload() -> None:
    out = chat._exec_tool("prediction_intraday_framework", {})
    assert out["stage"] == "s4"
    assert out["items"]
    assert "不构成投资建议" in out["disclaimer"]
    text = json.dumps(out, ensure_ascii=False)
    for w in _FORBIDDEN:
        assert w not in text


def test_short_sector_tool_pending_when_no_snapshot() -> None:
    out = chat._exec_tool("prediction_short_sector", {"stage": "s1", "date": "1999-01-01"})
    assert out["status"] == "no_snapshot"
    assert out["data"] is None
    assert "不构成投资建议" in out["disclaimer"]


def test_short_sector_tool_returns_snapshot_when_present() -> None:
    snap = Snapshot(
        head="short_sector", stage="s2", t="2099-11-30", prob=0.42,
        quantiles=(), shap_topk=(), features_used=("f0",),
        backends=("histgb", "catboost"), model_version="short_sector-v0",
    )
    cascade_store(snap)
    out = chat._exec_tool("prediction_short_sector", {"stage": "s2", "date": "2099-11-30"})
    assert out["status"] == "ok"
    assert abs(out["data"]["prob"] - 0.42) < 1e-9


def test_short_sector_tool_rejects_bad_stage() -> None:
    out = chat._exec_tool("prediction_short_sector", {"stage": "s9"})
    assert "error" in out
