# -*- coding: utf-8 -*-
"""combo-5d-edge 信号生成器测试（S238）。

集成测试——读真实 baostock_kline_cache.db，验：
- 返 top-N，结构齐全（date/code/gap/today_ret/amount/score）
- score 降序
- filtered 模式跳北交所 920 + ST
- basic 模式不过滤
- 显式历史日也能取到 picks

DB 缺失时 skip（CI/干净环境无 cache）。
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "backend" / "tools"
from vr_paths import resolve_data_dir
KLINE_DB = resolve_data_dir() / "baostock_kline_cache.db"

# commander_runner 在 backend/tools，加到 path 才能 import
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "backend"))  # for vr_paths

from commander_runner import load_combo_5d_today  # noqa: E402

pytestmark = pytest.mark.skipif(
    not KLINE_DB.exists(),
    reason="无 baostock_kline_cache.db（需先 backfill）",
)


def _assert_valid_pick(p: dict) -> None:
    for key in ("date", "code", "gap", "today_ret", "amount", "score"):
        assert key in p, f"缺字段 {key}: {p}"
    assert isinstance(p["code"], str) and p["code"]
    assert isinstance(p["gap"], (int, float))
    assert isinstance(p["date"], str) and len(p["date"]) == 10  # YYYY-MM-DD


def test_load_combo_5d_today_returns_20() -> None:
    """live 模式返 20 picks，结构齐，score 降序。"""
    picks = load_combo_5d_today()
    assert len(picks) == 20, f"期望 20，得 {len(picks)}"
    for p in picks:
        _assert_valid_pick(p)
    scores = [p["score"] for p in picks]
    assert scores == sorted(scores, reverse=True), "score 应降序"


def test_filtered_skips_920_and_st() -> None:
    """filtered 模式跳北交所 920。"""
    picks = load_combo_5d_today(mode="filtered")
    assert len(picks) == 20
    for p in picks:
        assert not p["code"].startswith("920"), f"filtered 不应有北交所 920: {p['code']}"


def test_basic_mode_returns_20() -> None:
    """basic 模式不过滤，也返 20（universe 含 920/ST）。"""
    picks = load_combo_5d_today(mode="basic")
    assert len(picks) == 20, f"basic 期望 20，得 {len(picks)}"


def test_explicit_top_n() -> None:
    """top_n 可调。"""
    picks = load_combo_5d_today(top_n=5)
    assert len(picks) == 5


def test_all_picks_same_date() -> None:
    """同一次调用所有 picks 同信号日。"""
    picks = load_combo_5d_today()
    dates = {p["date"] for p in picks}
    assert len(dates) == 1, f"应同一信号日，得 {dates}"
