# -*- coding: utf-8 -*-
"""S167 盘中微结构数据累积地基离线单测（spec §5）。

monkeypatch _DB_PATH 到 tmp（避免写真 .vibe-research/intraday_accumulation/）。
不联网：save_* 直接传预填数据，跳过 hithink/tencent/baostock 调用。
AAA + 描述性命名。

诚实框架：本测验证累积存储正确性，不测 §44 edge（prior LOW S152/S156，无 edge 声明）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
sys.path.insert(0, str(ROOT))

import data.intraday_accumulation_store as ias  # noqa: E402


_RANKINGS_SKYROCKET = [
    {"code": "600127", "name": "金健米业", "rank": 1, "heat": 9.8,
     "rank_change": 5, "rank_trend": "up"},
    {"code": "001358", "name": "兴欣新材", "rank": 2, "heat": 8.1,
     "rank_change": 3, "rank_trend": "up"},
]

_RANKINGS_ANOMALY = [
    {"code": "600127", "name": "金健米业", "tag": "涨停", "anomaly_pct": 10.0},
]

_QUOTES = {
    "600127": {"name": "金健米业", "price": 5.30, "change_pct": 10.0,
              "vol_ratio": 5.2, "turnover_pct": 8.1,
              "limit_up": 5.30, "limit_down": 4.32, "amount_wan": 20000.0},
    "001358": {"name": "兴欣新材", "price": 10.21, "change_pct": 10.0,
               "vol_ratio": 3.1, "turnover_pct": 5.0,
               "limit_up": 10.21, "limit_down": 8.35, "amount_wan": 5000.0},
}

_BARS = [
    {"date": "2026-09-05", "time": "09350000", "open": 4.80, "high": 5.30,
     "low": 4.80, "close": 5.30, "volume": 100000.0},
    {"date": "2026-09-05", "time": "09400000", "open": 5.30, "high": 5.30,
     "low": 5.30, "close": 5.30, "volume": 50000.0},
]


# ── 归一辅助 ────────────────────────────────────────────────────────────────

def test_to_float_to_int_handle_missing():
    assert ias._to_float(None) is None
    assert ias._to_float("-") is None
    assert ias._to_float("1,234.5") == 1234.5
    assert ias._to_int("3") == 3
    assert ias._to_int(None) is None


# ── ranking snapshots ──────────────────────────────────────────────────────

def test_save_ranking_snapshots_round_trip(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act
    n = ias.save_ranking_snapshots("2026-09-05", "2026-09-05T09:30", "skyrocket", _RANKINGS_SKYROCKET)
    # Assert
    assert n == 2
    rows = ias.load_rankings("2026-09-05", "2026-09-05")
    assert len(rows) == 2
    r = next(r for r in rows if r["code"] == "600127")
    assert r["source"] == "skyrocket"
    assert r["rank"] == 1
    assert r["heat"] == 9.8
    assert r["rank_trend"] == "up"


def test_save_ranking_snapshots_idempotent_no_duplicate(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act：同 ts 同 source 写两次
    ias.save_ranking_snapshots("2026-09-05", "2026-09-05T09:30", "skyrocket", _RANKINGS_SKYROCKET)
    ias.save_ranking_snapshots("2026-09-05", "2026-09-05T09:30", "skyrocket", _RANKINGS_SKYROCKET)
    # Assert：仍 2 行（PK 幂等）
    rows = ias.load_rankings("2026-09-05", "2026-09-05")
    assert len(rows) == 2


def test_save_ranking_snapshots_different_ts_accumulate(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act：两个 ts（10min 周期快照）
    ias.save_ranking_snapshots("2026-09-05", "2026-09-05T09:30", "skyrocket", _RANKINGS_SKYROCKET)
    ias.save_ranking_snapshots("2026-09-05", "2026-09-05T09:40", "skyrocket", _RANKINGS_SKYROCKET)
    # Assert：4 行（trajectory 累积，不同 ts 不覆盖）
    rows = ias.load_rankings("2026-09-05", "2026-09-05")
    assert len(rows) == 4


def test_save_ranking_snapshots_preserves_extra_json_for_anomaly(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act：异动榜带未归一字段
    ias.save_ranking_snapshots("2026-09-05", "2026-09-05T10:00", "anomaly", _RANKINGS_ANOMALY)
    # Assert：extra_json 保留 tag/anomaly_pct
    rows = ias.load_rankings("2026-09-05", "2026-09-05")
    assert len(rows) == 1
    extra = json.loads(rows[0]["extra_json"])
    assert extra["tag"] == "涨停"
    assert extra["anomaly_pct"] == 10.0


def test_save_ranking_snapshots_empty_returns_zero(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act
    n = ias.save_ranking_snapshots("2026-09-05", "2026-09-05T09:30", "skyrocket", [])
    # Assert
    assert n == 0
    assert ias.load_rankings("2026-09-05", "2026-09-05") == []


# ── quote snapshots ─────────────────────────────────────────────────────────

def test_save_quote_snapshots_round_trip(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act
    n = ias.save_quote_snapshots("2026-09-05", "2026-09-05T09:30", _QUOTES)
    # Assert
    assert n == 2
    rows = ias.load_quotes("2026-09-05", "2026-09-05")
    assert len(rows) == 2
    r = next(r for r in rows if r["code"] == "600127")
    assert r["vol_ratio"] == 5.2
    assert r["limit_up"] == 5.30


def test_save_quote_snapshots_missing_field_none(monkeypatch, tmp_path):
    # Arrange：缺 vol_ratio（不臆造，填 None）
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    quotes = {"600127": {"name": "x", "price": 5.0}}
    # Act
    ias.save_quote_snapshots("2026-09-05", "2026-09-05T09:30", quotes)
    # Assert
    rows = ias.load_quotes("2026-09-05", "2026-09-05")
    assert len(rows) == 1
    assert rows[0]["vol_ratio"] is None
    assert rows[0]["turnover_pct"] is None


# ── baostock 5min freeze ──────────────────────────────────────────────────────

def test_freeze_baostock_5min_round_trip(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act
    n = ias.freeze_baostock_5min("2026-09-05", "600127", "金健米业", _BARS)
    # Assert
    assert n == 1
    rows = ias.load_5min_freeze("2026-09-05", "2026-09-05")
    assert len(rows) == 1
    bars = json.loads(rows[0]["bars_json"])
    assert rows[0]["bar_count"] == 2
    assert bars[0]["close"] == 5.30


def test_freeze_baostock_5min_empty_bars_honest(monkeypatch, tmp_path):
    # Arrange：空 bars（baostock 缺数据/T+1 未稳）——诚实记 bar_count=0，不臆造
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act
    n = ias.freeze_baostock_5min("2026-09-05", "600127", "金健米业", [])
    # Assert
    assert n == 1
    rows = ias.load_5min_freeze("2026-09-05", "2026-09-05")
    assert rows[0]["bar_count"] == 0
    assert rows[0]["bars_json"] == "[]"


def test_freeze_baostock_5min_idempotent(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act：同 date+code 冻结两次
    ias.freeze_baostock_5min("2026-09-05", "600127", "金健米业", _BARS)
    ias.freeze_baostock_5min("2026-09-05", "600127", "金健米业", _BARS)
    # Assert：1 行（PK 幂等）
    assert len(ias.load_5min_freeze("2026-09-05", "2026-09-05")) == 1


# ── list_accumulation_dates ──────────────────────────────────────────────────

def test_list_accumulation_dates_union_three_tables(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    ias.save_ranking_snapshots("2026-09-04", "2026-09-04T09:30", "skyrocket", _RANKINGS_SKYROCKET)
    ias.save_quote_snapshots("2026-09-05", "2026-09-05T09:30", _QUOTES)
    ias.freeze_baostock_5min("2026-09-03", "600127", "x", _BARS)
    # Act
    dates = ias.list_accumulation_dates()
    # Assert：三表并集，升序
    assert dates == ["2026-09-03", "2026-09-04", "2026-09-05"]


# ── executor 门控（不联网，mock is_intraday_time）──────────────────────────────

def test_intraday_snapshot_skips_outside_trading_hours(monkeypatch):
    """非盘中时段 is_intraday_time 门控 no-op，不发请求。"""
    # Arrange：mock is_intraday_time 返 False（executor 内 from vr_paths import 时取到 patched）
    import scheduled_tasks as st
    import vr_paths
    monkeypatch.setattr(vr_paths, "is_intraday_time", lambda now=None: False)
    executor = st.TaskExecutor()

    # Act
    result = executor._execute_intraday_microstructure_snapshot({})

    # Assert：skipped，未触达数据源
    assert result["status"] == "skipped"


def test_baostock_freeze_skips_non_trading_day(monkeypatch):
    """非交易日 is_trading_day 门控跳过。"""
    import scheduled_tasks as st
    import vr_paths
    monkeypatch.setattr(vr_paths, "is_trading_day", lambda d=None: False)
    executor = st.TaskExecutor()

    # Act
    result = executor._execute_baostock_5min_freeze({})

    # Assert：skipped，未触达 baostock/hithink
    assert result["status"] == "skipped"
