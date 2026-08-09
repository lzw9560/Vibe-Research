# -*- coding: utf-8 -*-
"""S040 · 历史回填 + backtest_lite K 线缓存 单测（全离线，无 live 网络）。

覆盖：
- trading_days_back / trading_days_between 交易日枚举（跳周末）
- db_stats / existing_dates DB 只读统计（临时 sqlite）
- _calc_next_day_return kline_cache 缓存命中 / offset 读取 / 缓存写回
- run_backtest_async 传入 kline_cache（offset = 日历天数 + 15）
- backfill_dates：dry-run 探测（mock em_zt_topic_pool）、空池 / 连续失败中止、已有日期跳过
"""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest


# ── 交易日枚举 ────────────────────────────────────────────────

def test_trading_days_back_skips_weekends():
    import backfill_history as bf
    # 从 2026-08-10（周一）往前取 5 个交易日，应不含周末
    days = bf.trading_days_back("2026-08-10", 5)
    assert len(days) == 5
    assert days == sorted(days)  # 升序
    assert days[-1] == "2026-08-07"  # 周五
    for d in days:
        from datetime import datetime
        assert datetime.strptime(d, "%Y-%m-%d").weekday() < 5


def test_trading_days_between_inclusive():
    import backfill_history as bf
    # 2026-08-03(周一) ~ 2026-08-09(周日)：周一~周五 5 个交易日，周末不含
    days = bf.trading_days_between("2026-08-03", "2026-08-09")
    assert days == ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]


def test_trading_days_back_empty_calendar_ok():
    """trading_calendar.json 缺失时应降级为仅跳周末，不抛异常。"""
    import backfill_history as bf
    days = bf.trading_days_back("2026-01-05", 3)  # 含元旦假期后第一周
    assert len(days) == 3
    assert all(d < "2026-01-05" for d in days)


# ── DB 只读统计 ──────────────────────────────────────────────

def _make_tmp_db(tmp_path):
    db_path = str(tmp_path / "gene.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE gene_scores (
            date TEXT NOT NULL, code TEXT NOT NULL, PRIMARY KEY (date, code)
        )
    """)
    conn.executemany(
        "INSERT INTO gene_scores (date, code) VALUES (?, ?)",
        [("2026-07-09", "600519"), ("2026-07-09", "000001"), ("2026-07-10", "600519")],
    )
    conn.commit()
    conn.close()
    return db_path


def test_db_stats_and_existing_dates(tmp_path):
    import backfill_history as bf
    db_path = _make_tmp_db(tmp_path)
    total, earliest, latest = bf.db_stats(db_path)
    assert (total, earliest, latest) == (3, "2026-07-09", "2026-07-10")
    assert bf.existing_dates(db_path) == {"2026-07-09", "2026-07-10"}
    assert bf.db_earliest_date(db_path) == "2026-07-09"


def test_db_stats_missing_db_returns_empty(tmp_path):
    import backfill_history as bf
    total, earliest, latest = bf.db_stats(str(tmp_path / "nonexistent.db"))
    # 空库/缺表：COUNT 0，MIN/MAX None
    assert total in (0,) or (earliest is None and latest is None)


# ── backtest_lite kline_cache ────────────────────────────────

def _fake_bar(date: str, close: float):
    return SimpleNamespace(date=date, close=close)


def test_calc_next_day_return_uses_cache_and_offset(monkeypatch):
    import backtest_lite as bt

    kline_calls = []

    def fake_kline(code, category=4, offset=5):
        kline_calls.append((code, offset))
        return {"raw": code}  # 占位，kline_from_mootdx 被 monkeypatch

    # 两天 bars，同 code 跨日复用
    bars = (_fake_bar("2026-08-06", 10.0), _fake_bar("2026-08-07", 11.0))
    monkeypatch.setattr(bt.astock, "kline", fake_kline)
    monkeypatch.setattr(bt, "kline_from_mootdx", lambda code, raw: SimpleNamespace(bars=bars))

    cache: dict = {"_offset": 42}
    r1 = bt._calc_next_day_return("600519", "2026-08-06", cache)
    assert r1 == pytest.approx(0.1)  # (11-10)/10
    assert "600519" in cache and kline_calls == [("600519", 42)]

    # 第二天复用缓存：不再调 kline，offset 键保留
    r2 = bt._calc_next_day_return("600519", "2026-08-06", cache)
    assert r2 == pytest.approx(0.1)
    assert len(kline_calls) == 1


def test_calc_next_day_return_no_cache_default_offset(monkeypatch):
    import backtest_lite as bt

    kline_calls = []
    monkeypatch.setattr(bt.astock, "kline",
                        lambda code, category=4, offset=5: kline_calls.append((code, offset)) or None)
    monkeypatch.setattr(bt, "kline_from_mootdx",
                        lambda code, raw: SimpleNamespace(bars=()))

    result = bt._calc_next_day_return("600519", "2026-08-06")  # 无缓存参数
    assert result == 0.0  # 空 bars 返 0
    assert kline_calls == [("600519", 5)]


def test_calc_next_day_return_kline_error_returns_zero(monkeypatch):
    import backtest_lite as bt

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(bt.astock, "kline", boom)
    assert bt._calc_next_day_return("600519", "2026-08-06") == 0.0


def test_run_backtest_async_passes_kline_cache(monkeypatch, tmp_path):
    """run_backtest_async 内部建 kline_cache 且 offset = 日历天数 + 15。"""
    import backtest_lite as bt

    # 隔离缓存文件
    monkeypatch.setattr(bt, "_CACHE_FILE", tmp_path / "cache.json")

    seen_offsets = []

    async def fake_screener(date, *a, **k):
        g = SimpleNamespace(total_score=80, code="600519",
                            factors={"次日溢价率": 55.0})
        return SimpleNamespace(gene_scores=[g])

    def fake_kline(code, category=4, offset=5):
        seen_offsets.append(offset)
        return {}

    monkeypatch.setattr(bt.ls, "get_screener_result", fake_screener)
    monkeypatch.setattr(bt.astock, "kline", fake_kline)
    monkeypatch.setattr(bt, "kline_from_mootdx",
                        lambda code, raw: SimpleNamespace(bars=()))

    result = asyncio.run(bt.run_backtest_async("2026-07-01", "2026-08-09"))
    # 日历天数 = 39；offset = 39 + 15 = 54
    assert seen_offsets and seen_offsets[-1] == 54
    assert result.hit_rate == 0.0  # 全 0 收益
    assert result.factor_percentile_analysis is not None  # S043 字段保留


# ── backfill_dates 核心 ──────────────────────────────────────

def test_backfill_dry_run_probe_success(monkeypatch, tmp_path):
    import backfill_history as bf
    import astock

    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    db_path = _make_tmp_db(tmp_path)
    calls = []

    def fake_pool(endpoint, date, sort="fbt:asc"):
        calls.append((endpoint, date))
        return [{"c": "600519", "n": "贵州茅台"}]

    monkeypatch.setattr(astock, "em_zt_topic_pool", fake_pool)

    stats = asyncio.run(bf.backfill_dates(
        ["2026-06-01", "2026-06-02"], dry_run=True, db_path=db_path,
    ))
    assert stats["success"] == 2
    assert stats["failed"] == 0
    assert len(calls) == 2

    total, _, _ = bf.db_stats(db_path)
    assert total == 3  # dry-run 不写 DB


def test_backfill_dry_run_empty_pool(monkeypatch, tmp_path):
    import backfill_history as bf
    import astock

    db_path = _make_tmp_db(tmp_path)
    monkeypatch.setattr(astock, "em_zt_topic_pool",
                        lambda ep, d, sort="": [])

    stats = asyncio.run(bf.backfill_dates(
        ["2026-05-02"], dry_run=True, db_path=db_path,
    ))
    assert stats["empty_pool"] == 1
    assert stats["success"] == 0


def test_backfill_skips_existing_dates(monkeypatch, tmp_path):
    """幂等：--force 未设时，DB 已有日期被跳过（success=0）。"""
    import backfill_history as bf
    import astock

    db_path = _make_tmp_db(tmp_path)
    calls = []
    monkeypatch.setattr(astock, "em_zt_topic_pool",
                        lambda ep, d, sort="": calls.append(d) or [{"c": "x"}])

    stats = asyncio.run(bf.backfill_dates(
        ["2026-07-09", "2026-07-11"], dry_run=True, db_path=db_path,
    ))
    # 2026-07-09 已有 → skipped；2026-07-11 无 → success
    assert stats["skipped_existing"] == 1
    assert stats["success"] == 1
    assert "20260709" not in [c for c in calls]  # 未探测已有日期


def test_backfill_consecutive_failures_abort(monkeypatch, tmp_path):
    """连续失败达 batch_size 即中止。"""
    import backfill_history as bf
    import astock

    db_path = _make_tmp_db(tmp_path)

    def failing_pool(ep, d, sort=""):
        raise RuntimeError("mock network failure")

    monkeypatch.setattr(astock, "em_zt_topic_pool", failing_pool)
    # 熔断器状态读取容错（breaker_state 已 try/except）

    dates = [f"2026-06-{d:02d}" for d in range(1, 8)]
    stats = asyncio.run(bf.backfill_dates(
        dates, dry_run=True, batch_size=3, db_path=db_path,
    ))
    assert stats["failed"] == 3  # 连续 3 次触发中止，未跑完全部 7 天
    assert stats["success"] == 0
