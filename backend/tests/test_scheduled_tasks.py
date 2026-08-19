# -*- coding: utf-8 -*-
"""S084 C1-C4：盘后 derived 异步预采集 task 单测。

覆盖（reframe 阶段 C）：
- C1：derived_precompute 任务类型注册 + seed 默认任务（cron 0 17 * * 0-4，龙虎榜 16:30 后）
- C2：executor 对昨日涨停股算 derived 落 seal_derived_features（INSERT OR REPLACE）
- C3：derived_source 读 seal_derived_features（命中即返，不实时算）
- C4：缺快照跳过 / 单只失败不阻塞 / 涨停池空不崩（不臆造）
"""
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import scheduled_tasks as st


@pytest.fixture
def isolated_derived_env(tmp_path, monkeypatch):
    """隔离 seal_intraday.db（seal_derived_features 表）+ market_data.db，跑迁移建表。"""
    # 1. 隔离 seal_intraday.db（collector + derived 预采集落库共用 seal_derived_features）
    seal_db = tmp_path / "seal_intraday.db"
    monkeypatch.setattr("risk.seal_intraday_collector._DB_PATH", str(seal_db))
    monkeypatch.setattr("risk.seal_intraday_collector.SEAL_INTRADAY_DB_PATH", str(seal_db))
    from risk.seal_intraday_collector import run_migrations
    run_migrations()

    # 2. 隔离 market_data.db（TaskExecutor run 记录依赖 scheduled_tasks._DB_PATH）
    import scheduled_tasks as st_mod
    import workflow_state_repo as wsr
    market_db = tmp_path / "market_data.db"
    monkeypatch.setattr(st_mod, "_DB_PATH", str(market_db))
    monkeypatch.setattr(wsr, "_DB_PATH", str(market_db))
    st_mod._ensure_tables()
    return str(seal_db)


# ---------------------------------------------------------------------------
# C1：任务类型注册 + seed 默认任务 + cron 17:00 匹配（龙虎榜 16:30 后）
class TestDerivedPrecomputeRegistration:
    def test_type_registered_in_executors(self):
        assert "derived_precompute" in st.TaskExecutor()._executors

    def test_seed_creates_derived_precompute_task(self, isolated_market_db):
        st._ensure_seed_tasks()
        tasks = [t for t in st._manager.list_tasks() if t.name == "derived_precompute"]
        assert len(tasks) == 1
        assert tasks[0].task_type == "derived_precompute"
        assert tasks[0].cron_expr == "0 17 * * 0-4"  # 17:00 工作日（0=周一约定，龙虎榜 16:30 后）
        assert tasks[0].enabled is True

    def test_seed_derived_precompute_idempotent(self, isolated_market_db):
        st._ensure_seed_tasks()
        st._ensure_seed_tasks()
        tasks = [t for t in st._manager.list_tasks() if t.name == "derived_precompute"]
        assert len(tasks) == 1

    def test_cron_1700_matches_weekday_only(self):
        """cron 0 17 * * 0-4：工作日 17:00 命中，周末/16:59 不命中。"""
        from limitup_screener import BEIJING_TZ

        # 回溯到一个确定的周一
        mon_1700 = datetime(2026, 8, 19, 17, 0, tzinfo=BEIJING_TZ)
        while mon_1700.weekday() != 0:
            mon_1700 -= timedelta(days=1)
        assert mon_1700.weekday() == 0
        # 周一 17:00 命中
        assert st.cron_match("0 17 * * 0-4", mon_1700)
        # 周一 16:59 不命中（17:00 前一分钟）
        assert not st.cron_match("0 17 * * 0-4", mon_1700 - timedelta(minutes=1))
        # 周日 17:00 不命中（周末跳过）
        sun_1700 = mon_1700 - timedelta(days=1)
        assert sun_1700.weekday() == 6
        assert not st.cron_match("0 17 * * 0-4", sun_1700)


# ---------------------------------------------------------------------------
# C2/C3/C4：executor 落库 + derived_source 读表 + 容错
class TestDerivedPrecomputeExecutor:
    def test_writes_derived_for_yesterday_zt_codes(self, isolated_derived_env, monkeypatch):
        """C2/C3：昨日涨停 codes → snapshots → compute_derived → seal_derived_features 有行，
        且 derived_source 读表命中（不实时算）。"""
        seal_db = isolated_derived_env
        yesterday = "2026-08-13"

        monkeypatch.setattr(
            "candidate_funnel.sources.zt_pool_source.fetch_zt_pool_map",
            lambda d: {"000001": {"c": "000001"}, "600519": {"c": "600519"}},
        )
        # 12 条快照（>=10 标 ok），open_count=0（全程封死）→ broken_duration_min=0
        snaps = [{"ts": "2026-08-13T09:30:00", "open_count": 0, "limit_pct": 10.0,
                  "price": 11.0, "low_price": 9.5}] * 12
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code",
                            lambda code, date: snaps)

        r = st.TaskExecutor()._execute_derived_precompute({"date": yesterday})

        assert r["status"] == "ok"
        assert r["codes"] == 2
        assert r["written"] == 2

        conn = sqlite3.connect(seal_db)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM seal_derived_features WHERE date=? AND code IN ('000001','600519')",
                (yesterday,),
            ).fetchone()[0]
            assert n == 2
        finally:
            conn.close()

        # C3：derived_source 读 seal_derived_features 命中（不实时算）
        from candidate_funnel.sources import derived_source
        with patch("risk.seal_intraday_collector.get_snapshots_by_code") as snap_spy:
            d = derived_source.fetch_derived("000001", yesterday)
        assert d is not None
        assert d["data_status"] == "ok"
        assert d["broken_duration_min"] == 0.0
        snap_spy.assert_not_called()  # 命中预采集表，不 per-code 实时算

    def test_skips_codes_without_snapshots(self, isolated_derived_env, monkeypatch):
        """C4：缺快照跳过（不臆造），不崩。"""
        monkeypatch.setattr(
            "candidate_funnel.sources.zt_pool_source.fetch_zt_pool_map",
            lambda d: {"000001": {}, "000002": {}},
        )
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code",
                            lambda code, date: [])

        r = st.TaskExecutor()._execute_derived_precompute({"date": "2026-08-13"})
        assert r["status"] == "ok"
        assert r["written"] == 0
        assert r["skipped"] == 2

    def test_empty_zt_pool_returns_zero(self, isolated_derived_env, monkeypatch):
        """非交易日/采集失败 → 涨停池空 → codes=0，不崩。"""
        monkeypatch.setattr(
            "candidate_funnel.sources.zt_pool_source.fetch_zt_pool_map", lambda d: {},
        )
        r = st.TaskExecutor()._execute_derived_precompute({"date": "2026-08-15"})
        assert r["status"] == "ok"
        assert r["codes"] == 0
        assert r["written"] == 0

    def test_single_code_failure_does_not_block_others(self, isolated_derived_env, monkeypatch):
        """C4：单只取快照异常 → 跳过该只，其余仍写（catch 不抛）。"""
        good_snaps = [{"ts": "x", "open_count": 0, "limit_pct": 10.0,
                       "price": 11.0, "low_price": 9.5}] * 12

        def fake_snapshots(code, date):
            if code == "000002":
                raise RuntimeError("boom")
            return good_snaps

        monkeypatch.setattr(
            "candidate_funnel.sources.zt_pool_source.fetch_zt_pool_map",
            lambda d: {"000001": {}, "000002": {}},
        )
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", fake_snapshots)

        r = st.TaskExecutor()._execute_derived_precompute({"date": "2026-08-13"})
        assert r["status"] == "ok"
        assert r["written"] == 1  # 000001 写入
        assert r["skipped"] == 1  # 000002 异常跳过
