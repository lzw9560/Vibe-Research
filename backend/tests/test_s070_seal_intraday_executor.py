# -*- coding: utf-8 -*-
"""S070 D3：_execute_seal_intraday_collect executor 扩展测试（R3 日积）。

覆盖：
- collect_once 成功 → trajectory_written/derived_written > 0（AC1/AC6）
- collect_once 失败（written=0）→ 不跑派生（trajectory_written/derived_written 缺省 0）
- 派生计算抛异常 → 不阻塞主流程（result 仍返，derived_status=degraded）
- 缺快照（get_snapshots_by_code 返空）→ 跳过派生不臆造
- 落库可查（intraday_features + seal_derived_features 有行）
"""
import sqlite3
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_seal_executor_env(tmp_path, monkeypatch):
    """隔离 seal_intraday.db + market_data.db + 强制交易时段 + S089 路由层分表感知。

    返回 (db_path, date_str) 供测试落库断言。

    主库 seal_intraday.db 存 intraday_features / seal_derived_features（非分区），
    seal_intraday_snapshots 时序数据走 S089 路由层到 seal_intraday_YYYY.db 月分表。
    """
    # 1. 隔离 seal_intraday.db（collector + 派生落库共用）
    seal_db = tmp_path / "seal_intraday.db"
    monkeypatch.setattr("risk.seal_intraday_collector._DB_PATH", str(seal_db))
    monkeypatch.setattr("risk.seal_intraday_collector.SEAL_INTRADAY_DB_PATH", str(seal_db))
    from risk.seal_intraday_collector import run_migrations
    run_migrations()

    # S089：分库路由层重定向到 tmp_path（seal_intraday_snapshots 时序走分表）
    import db_partition_router as router
    import os
    monkeypatch.setattr(router, "PRIVATE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(router, "SEAL_INTRADAY_DIR", str(tmp_path))

    def _fake_db_path(year: str) -> str:
        return os.path.join(str(tmp_path), f"seal_intraday_{year}.db")

    monkeypatch.setattr(router, "seal_intraday_db_path", _fake_db_path)

    # 2. 隔离 market_data.db（TaskExecutor 依赖 scheduled_tasks._DB_PATH）
    import scheduled_tasks as st
    import workflow_state_repo as wsr
    market_db = tmp_path / "market_data.db"
    monkeypatch.setattr(st, "_DB_PATH", str(market_db))
    monkeypatch.setattr(wsr, "_DB_PATH", str(market_db))
    # 新库需建表
    st._ensure_tables()

    # 3. 强制交易时段（collect_once 门控）
    import risk.seal_intraday_collector as sic
    monkeypatch.setattr(sic, "is_intraday_trading_time", lambda now=None: True)

    return str(seal_db), "2026-08-11"


def _mock_pool_with_low():
    """mock em_zt_topic_pool + tencent_quote，返回 2 只票带 low + zdp。"""
    fake_pool = [
        {"c": "000001", "n": "平安银行", "p": 12.5, "fund": 1e8, "zbc": 0,
         "fbt": 93500, "lbc": 1, "hybk": "银行", "zdp": 10.0},
        {"c": "600519", "n": "贵州茅台", "p": 1800, "fund": 5e8, "zbc": 1,
         "fbt": 100000, "lbc": 2, "hybk": "白酒", "zdp": 10.0},
    ]
    fake_quotes = {
        "000001": {"low": 12.2},
        "600519": {"low": 1780.0},
    }
    return fake_pool, fake_quotes


class TestSealIntradayCollectExecutor:
    def test_collect_success_triggers_derived_persist(self, isolated_seal_executor_env, monkeypatch):
        """D1: collect_once 成功 → trajectory_written/derived_written > 0。"""
        seal_db, _ = isolated_seal_executor_env
        fake_pool, fake_quotes = _mock_pool_with_low()
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: fake_pool)
        monkeypatch.setattr("astock.tencent_quote", lambda codes: fake_quotes)
        # mock 规则引擎（不测 bomb_alert，避免依赖）
        monkeypatch.setattr("risk.bomb_alert_rules.check_all_rules", lambda *a, **k: [])
        monkeypatch.setattr("risk.bomb_alert_dispatcher.process_alerts", lambda *a, **k: [])

        from scheduled_tasks import TaskExecutor
        executor = TaskExecutor()
        result = executor._execute_seal_intraday_collect({})

        assert result["written"] == 2
        assert result["trajectory_written"] == 2
        assert result["derived_written"] == 2
        assert result["derived_status"] == "ok"

        # 落库可查（date 由 collect_once 用 datetime.now() 写入，从 result 取）
        actual_date = result["date"]
        conn = sqlite3.connect(seal_db)
        try:
            traj_cnt = conn.execute(
                "SELECT COUNT(*) FROM intraday_features WHERE date=? AND code IN ('000001','600519')",
                (actual_date,)
            ).fetchone()[0]
            assert traj_cnt == 2
            derived_cnt = conn.execute(
                "SELECT COUNT(*) FROM seal_derived_features WHERE date=? AND code IN ('000001','600519')",
                (actual_date,)
            ).fetchone()[0]
            assert derived_cnt == 2
        finally:
            conn.close()

    def test_collect_failure_skips_derived(self, isolated_seal_executor_env, monkeypatch):
        """D1: collect_once 失败（written=0）→ 不跑派生。"""
        # mock em_zt_topic_pool 抛异常 → collect_once 返 degraded, written=0
        def _fail(*a, **k):
            raise RuntimeError("circuit breaker open")
        monkeypatch.setattr("astock.em_zt_topic_pool", _fail)

        from scheduled_tasks import TaskExecutor
        executor = TaskExecutor()
        result = executor._execute_seal_intraday_collect({})

        assert result["written"] == 0
        assert result["data_status"] == "degraded"
        # 派生未触发：result 不含 trajectory_written/derived_written（因 written=0 分支未进）
        assert "trajectory_written" not in result
        assert "derived_written" not in result

    def test_derived_failure_does_not_block_main(self, isolated_seal_executor_env, monkeypatch):
        """D2: 派生计算抛异常 → 不阻塞主采集，derived_status=degraded。"""
        fake_pool, fake_quotes = _mock_pool_with_low()
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: fake_pool)
        monkeypatch.setattr("astock.tencent_quote", lambda codes: fake_quotes)
        monkeypatch.setattr("risk.bomb_alert_rules.check_all_rules", lambda *a, **k: [])
        monkeypatch.setattr("risk.bomb_alert_dispatcher.process_alerts", lambda *a, **k: [])
        # mock compute_trajectory 抛异常（派生失败）
        def _boom(snaps):
            raise RuntimeError("trajectory compute boom")
        monkeypatch.setattr("strategies.intraday_features.compute_trajectory", _boom)

        from scheduled_tasks import TaskExecutor
        executor = TaskExecutor()
        result = executor._execute_seal_intraday_collect({})

        # 主采集成功
        assert result["written"] == 2
        # 派生失败但不阻塞
        assert result["derived_status"] == "degraded"
        assert result["trajectory_written"] == 0  # 第一只就抛了，未写入

    def test_empty_snapshots_skips_derived(self, isolated_seal_executor_env, monkeypatch):
        """缺快照（get_snapshots_by_code 返空）→ 跳过派生不臆造。"""
        fake_pool, fake_quotes = _mock_pool_with_low()
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: fake_pool)
        monkeypatch.setattr("astock.tencent_quote", lambda codes: fake_quotes)
        monkeypatch.setattr("risk.bomb_alert_rules.check_all_rules", lambda *a, **k: [])
        monkeypatch.setattr("risk.bomb_alert_dispatcher.process_alerts", lambda *a, **k: [])
        # mock get_snapshots_by_code 返空（极端：latest 有但时序查不到）
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date=None: [])

        from scheduled_tasks import TaskExecutor
        executor = TaskExecutor()
        result = executor._execute_seal_intraday_collect({})

        assert result["written"] == 2
        # 派生跳过（snaps 空）
        assert result["trajectory_written"] == 0
        assert result["derived_written"] == 0
        # 但 derived_status 仍 ok（正常跳过非异常）
        assert result["derived_status"] == "ok"

    def test_prune_flag_works(self, isolated_seal_executor_env, monkeypatch):
        """payload prune=True 触发 prune_old_snapshots（不报错，pruned 字段在 result）。"""
        fake_pool, fake_quotes = _mock_pool_with_low()
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: fake_pool)
        monkeypatch.setattr("astock.tencent_quote", lambda codes: fake_quotes)
        monkeypatch.setattr("risk.bomb_alert_rules.check_all_rules", lambda *a, **k: [])
        monkeypatch.setattr("risk.bomb_alert_dispatcher.process_alerts", lambda *a, **k: [])

        from scheduled_tasks import TaskExecutor
        executor = TaskExecutor()
        result = executor._execute_seal_intraday_collect({"prune": True, "retention_days": 30})
        assert "pruned" in result
        assert result["pruned"] >= 0  # 空库 prune 返 0
