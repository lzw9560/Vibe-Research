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

# hithink auction_snapshot 归一后 item（schema 实测自 /api/a-share/auction/snapshot）
_AUCTION_LIVE = [
    {"code": "600519", "name": "贵州茅台", "stage": "live",
     "auction_price": 1295.88, "auction_pct": -0.231, "auction_volume": 179.43,
     "auction_amount": 23251975, "auction_unmatched": 0.57,
     "auction_turnover_pct": 0.0014, "auction_yesterday_ratio_pct": 1.011,
     "auction_volume_ratio": 1.7089, "pre_close_price": 1298.88,
     "open_price": 1295.88, "last_price": 1330.0,
     "float_market_cap": 1662608529330, "source_timestamp": 1788714324149,
     "auction_phase": "live", "data_status": "ready"},
    {"code": "000001", "name": "平安银行", "stage": "live",
     "auction_price": 11.86, "auction_pct": -0.1684, "auction_volume": 5094.0,
     "auction_amount": 6041484.0, "auction_unmatched": 236.0,
     "auction_turnover_pct": 0.0026, "auction_yesterday_ratio_pct": 0.4609,
     "auction_volume_ratio": 2.269, "pre_close_price": 11.88,
     "open_price": 11.86, "last_price": 11.89,
     "float_market_cap": 230733594542.99, "source_timestamp": 1788714324149,
     "auction_phase": "live", "data_status": "ready"},
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


# ── auction snapshots ───────────────────────────────────────────────────────

def test_save_auction_snapshots_round_trip(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act
    n = ias.save_auction_snapshots("2026-09-05", "2026-09-05T09:20", "live", _AUCTION_LIVE)
    # Assert
    assert n == 2
    rows = ias.load_auctions("2026-09-05", "2026-09-05")
    assert len(rows) == 2
    r = next(r for r in rows if r["code"] == "600519")
    assert r["stage"] == "live"
    assert r["auction_volume_ratio"] == 1.7089  # §44 关键信号
    assert r["auction_price"] == 1295.88
    assert r["data_status"] == "ready"


def test_save_auction_snapshots_idempotent_no_duplicate(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act：同 ts 同 stage 写两次
    ias.save_auction_snapshots("2026-09-05", "2026-09-05T09:20", "live", _AUCTION_LIVE)
    ias.save_auction_snapshots("2026-09-05", "2026-09-05T09:20", "live", _AUCTION_LIVE)
    # Assert：仍 2 行（PK 幂等）
    assert len(ias.load_auctions("2026-09-05", "2026-09-05")) == 2


def test_save_auction_snapshots_live_trajectory_accumulates(monkeypatch, tmp_path):
    # Arrange：live 不同 ts 累积为竞价 trajectory（演化轨迹）
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act：09:16 / 09:20 / 09:24 三个 ts
    for ts in ("2026-09-05T09:16", "2026-09-05T09:20", "2026-09-05T09:24"):
        ias.save_auction_snapshots("2026-09-05", ts, "live", _AUCTION_LIVE)
    # Assert：6 行（2 code × 3 ts，trajectory 累积）
    assert len(ias.load_auctions("2026-09-05", "2026-09-05")) == 6


def test_save_auction_snapshots_live_final_separate_rows(monkeypatch, tmp_path):
    # Arrange：live 与 final 是不同 stage，同 ts 同 code 各一行
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    ias.save_auction_snapshots("2026-09-05", "2026-09-05T09:25", "live", _AUCTION_LIVE)
    final = [{**_AUCTION_LIVE[0], "stage": "final", "auction_phase": "closed"}]
    ias.save_auction_snapshots("2026-09-05", "2026-09-05T09:30", "final", final)
    # Assert：3 行（2 live + 1 final，PK 含 stage 区分）
    rows = ias.load_auctions("2026-09-05", "2026-09-05")
    assert len(rows) == 3
    stages = {r["stage"] for r in rows}
    assert stages == {"live", "final"}


def test_save_auction_snapshots_missing_field_none(monkeypatch, tmp_path):
    # Arrange：缺 auction_volume_ratio（不臆造，填 None）
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    items = [{"code": "600519", "name": "x", "stage": "final", "auction_price": 5.0}]
    # Act
    ias.save_auction_snapshots("2026-09-05", "2026-09-05T09:30", "final", items)
    # Assert
    rows = ias.load_auctions("2026-09-05", "2026-09-05")
    assert len(rows) == 1
    assert rows[0]["auction_volume_ratio"] is None
    assert rows[0]["data_status"] is None


def test_save_auction_snapshots_empty_returns_zero(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act
    n = ias.save_auction_snapshots("2026-09-05", "2026-09-05T09:20", "live", [])
    # Assert
    assert n == 0
    assert ias.load_auctions("2026-09-05", "2026-09-05") == []


def test_has_auction_snapshot_guard(monkeypatch, tmp_path):
    # Arrange：final 守门——避免静态终态每周期重复落库成伪 trajectory
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    # Act / Assert：写前 False
    assert ias.has_auction_snapshot("2026-09-05", "final") is False
    ias.save_auction_snapshots("2026-09-05", "2026-09-05T09:30", "final",
                                [{**_AUCTION_LIVE[0], "stage": "final"}])
    # 写后 True（final 已存在）
    assert ias.has_auction_snapshot("2026-09-05", "final") is True
    # live 未写，仍 False
    assert ias.has_auction_snapshot("2026-09-05", "live") is False


# ── list_accumulation_dates ──────────────────────────────────────────────────

def test_list_accumulation_dates_union_four_tables(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    ias.save_ranking_snapshots("2026-09-04", "2026-09-04T09:30", "skyrocket", _RANKINGS_SKYROCKET)
    ias.save_quote_snapshots("2026-09-05", "2026-09-05T09:30", _QUOTES)
    ias.freeze_baostock_5min("2026-09-03", "600127", "x", _BARS)
    ias.save_auction_snapshots("2026-09-04", "2026-09-04T09:20", "live", _AUCTION_LIVE)
    # Act
    dates = ias.list_accumulation_dates()
    # Assert：四表并集，升序（auction 写 09-04 与 ranking 同日，去重）
    assert dates == ["2026-09-03", "2026-09-04", "2026-09-05"]


# ── executor 门控（不联网，mock is_intraday_time / is_auction_time）──────────────

def test_intraday_snapshot_skips_outside_trading_and_auction(monkeypatch):
    """非盘中时段且非竞价时段 → no-op，不发请求。"""
    # Arrange：mock 两门控均返 False（executor 内 from vr_paths import 取 patched）
    import scheduled_tasks as st
    import vr_paths
    monkeypatch.setattr(vr_paths, "is_intraday_time", lambda now=None: False)
    monkeypatch.setattr(vr_paths, "is_auction_time", lambda now=None: False)
    executor = st.TaskExecutor()

    # Act
    result = executor._execute_intraday_microstructure_snapshot({})

    # Assert：skipped，未触达数据源
    assert result["status"] == "skipped"


def test_intraday_snapshot_auction_window_captures_live(monkeypatch, tmp_path):
    """竞价窗口（09:15-09:25）→ 只采竞价 live，跳过排名/量比（盘前未开盘）。"""
    # Arrange
    import scheduled_tasks as st
    import vr_paths
    import data.intraday_accumulation_store as ias
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    monkeypatch.setattr(vr_paths, "is_intraday_time", lambda now=None: False)
    monkeypatch.setattr(vr_paths, "is_auction_time", lambda now=None: True)
    monkeypatch.setattr(vr_paths, "last_trading_date_str", lambda: "2026-09-05")
    monkeypatch.setattr(vr_paths, "prev_trading_date_str", lambda: "2026-09-04")
    executor = st.TaskExecutor()
    # mock hithink 涨停池（prev 日）+ auction_snapshot
    import data.sources.hithink_src as hs
    monkeypatch.setattr(hs, "limit_up_pool",
                        lambda d: [{"code": "600519"}, {"code": "000001"}])
    monkeypatch.setattr(hs, "auction_snapshot",
                        lambda codes, stage="final": [dict(it, stage=stage) for it in _AUCTION_LIVE])

    # Act
    result = executor._execute_intraday_microstructure_snapshot({})

    # Assert：竞价 live 落库，排名/量比空（竞价窗口跳过）
    assert result["auction"] == {"stage": "live", "count": 2}
    assert result["rankings"] == {"skyrocket": 0, "hot_stock": 0, "anomaly": 0}
    assert result["quotes"] == 0
    rows = ias.load_auctions("2026-09-05", "2026-09-05")
    assert len(rows) == 2
    assert all(r["stage"] == "live" for r in rows)


def test_intraday_snapshot_intraday_captures_final_once(monkeypatch, tmp_path):
    """盘中窗口 → 采排名+量比+竞价 final；final 守门只采一次（避免伪 trajectory）。"""
    # Arrange
    import scheduled_tasks as st
    import vr_paths
    import data.intraday_accumulation_store as ias
    monkeypatch.setattr(ias, "_DB_PATH", str(tmp_path / "ia.db"))
    monkeypatch.setattr(vr_paths, "is_intraday_time", lambda now=None: True)
    monkeypatch.setattr(vr_paths, "is_auction_time", lambda now=None: False)
    monkeypatch.setattr(vr_paths, "last_trading_date_str", lambda: "2026-09-05")
    monkeypatch.setattr(vr_paths, "prev_trading_date_str", lambda: "2026-09-04")
    executor = st.TaskExecutor()
    import data.sources.hithink_src as hs
    monkeypatch.setattr(hs, "limit_up_pool", lambda d: [{"code": "600519"}])
    monkeypatch.setattr(hs, "auction_snapshot",
                        lambda codes, stage="final": [{**_AUCTION_LIVE[0], "stage": stage}])
    monkeypatch.setattr(hs, "skyrocket", lambda: [])
    monkeypatch.setattr(hs, "hot_stock", lambda: [])
    monkeypatch.setattr(hs, "anomaly_list", lambda: [])
    import data.sources.tencent as tenc
    monkeypatch.setattr(tenc, "fetch_raw", lambda codes: {})

    # Act：第一次盘中周期 → final 采集
    r1 = executor._execute_intraday_microstructure_snapshot({})
    assert r1["auction"] == {"stage": "final", "count": 1}
    # Act：第二次盘中周期 → final 已存在，守门跳过（count=0）
    r2 = executor._execute_intraday_microstructure_snapshot({})
    assert r2["auction"] == {"stage": "final", "count": 0}
    # Assert：final 只落库一次（1 行），不是两次伪 trajectory
    rows = ias.load_auctions("2026-09-05", "2026-09-05")
    assert len(rows) == 1


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


# ── is_auction_time 集合竞价窗口门控 ────────────────────────────────────────

def test_is_auction_time_boundaries(monkeypatch):
    """09:15-09:25 含两端 → True；09:14 / 09:26 / 盘中 → False（交易日）。"""
    import vr_paths
    from datetime import datetime as _dt
    monkeypatch.setattr(vr_paths, "is_trading_day", lambda d=None: True)

    def at(hh, mm):
        return _dt(2026, 9, 7, hh, mm)

    assert vr_paths.is_auction_time(at(9, 15)) is True   # 左边界含
    assert vr_paths.is_auction_time(at(9, 20)) is True    # 窗口内（live 演化）
    assert vr_paths.is_auction_time(at(9, 25)) is True    # 右边界含（match 时刻）
    assert vr_paths.is_auction_time(at(9, 14)) is False   # 窗口前
    assert vr_paths.is_auction_time(at(9, 26)) is False   # 窗口后
    assert vr_paths.is_auction_time(at(10, 30)) is False  # 盘中（非竞价）


def test_is_auction_time_non_trading_day_false(monkeypatch):
    """非交易日 → False（节假日/周末不竞价）。"""
    import vr_paths
    monkeypatch.setattr(vr_paths, "is_trading_day", lambda d=None: False)
    assert vr_paths.is_auction_time() is False
