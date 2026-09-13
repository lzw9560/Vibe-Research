# -*- coding: utf-8 -*-
"""S44v2 P0 闭环测试：R3 30/60 天写回 + reader override-aware。

覆盖（§44v2 规约④ R3 回溯主场 + 规约② days_robust<60 cap 已落地，此处验闭环后半段）：
- write_override：写 evaluation_lifts.db 新表 + 经 lift_to_multiplier 升降级（lift≥2+days≥60→validated×1.0；
  lift<1+days≥60→劣于随机×0.1；days<60→待复验×0.5）+ 不改 frozen dict b1aba21。
- get_effective_dimension：override 优先 fallback frozen + cache + 不污染 frozen。
- apply_revalidation：injectable compute_fn（mock 验 writeback）+ default path_lift 从 forward_test DB 算。
- evaluation_backtest：到点自动写回（mock compute）+ compute 不可用 reminder fallback + not_due 不写。
- reader 接线：lift_for_arm / scoring / _apply_evaluation_layer 用 effective（override）值。

纯离线：override DB 用 tmp_path；forward_test DB 用 tmp_path 建最小表。不触网络/baostock。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from candidate_funnel.evaluation import (
    DIMENSION_LIFT_REGISTRY,
    FROZEN_COMMIT,
    lift_to_multiplier,
)
from candidate_funnel.lift_override import (
    RevalidationResult,
    apply_revalidation,
    get_effective_dimension,
    write_override,
)


# ---------------------------------------------------------------------------
# write_override：写盘 + 升降级 + 不改 frozen dict
# ---------------------------------------------------------------------------
class TestWriteOverride:
    def test_validated_upgrade_writes_x1(self, tmp_path):
        # lift≥2 + days≥60 + CI不重叠 + robust → validated ×1.0
        r = write_override("breakout", lift=2.3, n=500, days_robust=70,
                           phase="reverify", ci_overlap=False, robust=True,
                           db_path=str(tmp_path / "evaluation_lifts.db"))
        assert r["validation_status"] == "validated"
        assert r["weight_multiplier"] == 1.0
        assert r["dimension_id"] == "breakout"
        assert r["phase"] == "reverify"

    def test_falsified_demote_writes_x01(self, tmp_path):
        # lift<1 + days≥60 + robust → 劣于随机 ×0.1
        r = write_override("turnover", lift=0.85, n=2000, days_robust=120,
                           phase="reverify", robust=True,
                           db_path=str(tmp_path / "evaluation_lifts.db"))
        assert r["validation_status"] == "劣于随机"
        assert r["weight_multiplier"] == 0.1

    def test_days_lt_60_provisional_cap_x05(self, tmp_path):
        # §44v2 规约④：days<60 不能 validated 也不能证否 → 待复验 ×0.5（即使 lift≥2）
        r = write_override("breakout", lift=2.8, n=600, days_robust=42,
                           phase="first_retrospective", ci_overlap=False, robust=True,
                           db_path=str(tmp_path / "evaluation_lifts.db"))
        assert r["validation_status"] == "待复验"
        assert r["weight_multiplier"] == 0.5

    def test_upsert_replaces_existing(self, tmp_path):
        db = str(tmp_path / "evaluation_lifts.db")
        write_override("breakout", lift=0.8, n=100, days_robust=120,
                       phase="reverify", robust=True, db_path=db)
        r2 = write_override("breakout", lift=2.4, n=500, days_robust=130,
                            phase="reverify", ci_overlap=False, robust=True, db_path=db)
        assert r2["weight_multiplier"] == 1.0  # 升级覆盖原 ×0.1
        # DB 只有一行
        conn = sqlite3.connect(db)
        cnt = conn.execute("SELECT COUNT(*) FROM dimension_lift_overrides").fetchone()[0]
        conn.close()
        assert cnt == 1


# ---------------------------------------------------------------------------
# get_effective_dimension：override 优先 + fallback frozen + 不污染 frozen
# ---------------------------------------------------------------------------
class TestGetEffectiveDimension:
    def test_falls_back_to_frozen_when_no_override(self, tmp_path):
        d = get_effective_dimension("breakout", db_path=str(tmp_path / "evaluation_lifts.db"))
        assert d is not None
        assert d.lift == pytest.approx(1.363)  # frozen baseline
        assert d.weight_multiplier == 0.5
        assert d.frozen_commit == FROZEN_COMMIT

    def test_override_wins_over_frozen(self, tmp_path):
        db = str(tmp_path / "evaluation_lifts.db")
        write_override("breakout", lift=2.5, n=600, days_robust=80,
                       phase="reverify", ci_overlap=False, robust=True, db_path=db)
        d = get_effective_dimension("breakout", db_path=db)
        assert d.lift == pytest.approx(2.5)
        assert d.weight_multiplier == 1.0  # override validated
        assert d.days_robust == 80

    def test_unknown_dim_returns_none(self, tmp_path):
        assert get_effective_dimension("nonexistent", db_path=str(tmp_path / "e.db")) is None

    def test_override_does_not_mutate_frozen_registry(self, tmp_path):
        # 工程底线：frozen dict FROZEN_COMMIT b1aba21 read-only，写回不改 baseline
        db = str(tmp_path / "evaluation_lifts.db")
        write_override("breakout", lift=9.99, n=999, days_robust=999,
                       phase="reverify", ci_overlap=False, robust=True, db_path=db)
        get_effective_dimension("breakout", db_path=db)
        frozen = DIMENSION_LIFT_REGISTRY["breakout"]
        assert frozen.lift == pytest.approx(1.363), "frozen baseline 被改了！"
        assert frozen.weight_multiplier == 0.5
        assert frozen.days_robust == 42
        assert frozen.frozen_commit == FROZEN_COMMIT

    def test_cache_serves_second_read_without_db_hit(self, tmp_path, monkeypatch):
        db = str(tmp_path / "evaluation_lifts.db")
        # 第一次读 fallback frozen → 缓存
        d1 = get_effective_dimension("breakout", db_path=db)
        assert d1.lift == pytest.approx(1.363)
        # 篡改 sqlite3.connect 确保第二次读走缓存（不查 DB）
        def _boom(*a, **k):
            raise AssertionError("cache miss → 不该连 DB")
        monkeypatch.setattr(sqlite3, "connect", _boom)
        d2 = get_effective_dimension("breakout", db_path=db)
        assert d2.lift == pytest.approx(1.363)


# ---------------------------------------------------------------------------
# apply_revalidation：injectable compute_fn + default path_lift
# ---------------------------------------------------------------------------
class TestApplyRevalidation:
    def test_mock_compute_writes_overrides_for_returned_dims(self, tmp_path):
        db = str(tmp_path / "evaluation_lifts.db")
        calls = []

        def compute(dim_id):
            calls.append(dim_id)
            if dim_id == "breakout":
                return RevalidationResult(lift=2.4, n=500, days_robust=80,
                                           ci_overlap=False, robust=True,
                                           source_script="mock_compute")
            return None  # 其他 dim skip

        r = apply_revalidation("reverify", compute_fn=compute, db_path=db)
        assert "breakout" in r["written"]
        assert r["errors"] == []
        d = get_effective_dimension("breakout", db_path=db)
        assert d.weight_multiplier == 1.0  # validated

    def test_compute_none_for_dim_is_skipped_not_error(self, tmp_path):
        db = str(tmp_path / "evaluation_lifts.db")
        r = apply_revalidation("reverify",
                               compute_fn=lambda dim_id: None, db_path=db)
        assert r["written"] == []
        assert r["errors"] == []

    def test_compute_raises_is_error_not_crash(self, tmp_path):
        db = str(tmp_path / "evaluation_lifts.db")

        def boom(dim_id):
            if dim_id == "breakout":
                raise RuntimeError("baostock down")
            return None

        r = apply_revalidation("reverify", compute_fn=boom, db_path=db)
        assert "breakout" in r["errors"]
        assert r["written"] == []  # 崩的 dim 没写

    def test_default_compute_path_lift_from_forward_test_db(self, tmp_path):
        # 建 forward_test_records + universe_returns 最小表，验 default path_lift compute
        ft_db = str(tmp_path / "gene_scores.db")
        conn = sqlite3.connect(ft_db)
        conn.executescript("""
            CREATE TABLE forward_test_records (
                signal_date TEXT, code TEXT, strategy_code TEXT,
                return_path REAL, is_unbuyable INTEGER DEFAULT 0
            );
            CREATE TABLE universe_returns (
                signal_date TEXT, code TEXT,
                return_path REAL, is_unbuyable INTEGER DEFAULT 0
            );
        """)
        # Day1: picks 3 (2 win path>0, 1 lose), universe 10 (4 win) → lift = (2/3)/(4/10)=1.667
        # Day2: picks 2 (2 win), universe 10 (5 win) → lift = (2/2)/(5/10)=2.0
        # avg lift = (1.667+2.0)/2 = 1.8335 ; days_robust=2 ; n_picks=5
        for code, rp in [("c1", 5.0), ("c2", 3.0), ("c3", -2.0)]:
            conn.execute("INSERT INTO forward_test_records(signal_date,code,return_path,is_unbuyable) VALUES('2026-08-01',?,?,0)", (code, rp))
        for code, rp in [("u1",4.0),("u2",3.0),("u3",2.0),("u4",1.0),("u5",-1.0),("u6",-2.0),("u7",-3.0),("u8",-4.0),("u9",-5.0),("u10",-6.0)]:
            conn.execute("INSERT INTO universe_returns(signal_date,code,return_path,is_unbuyable) VALUES('2026-08-01',?,?,0)", (code, rp))
        for code, rp in [("c1", 6.0), ("c2", 4.0)]:
            conn.execute("INSERT INTO forward_test_records(signal_date,code,return_path,is_unbuyable) VALUES('2026-08-02',?,?,0)", (code, rp))
        for code, rp in [("u1",5.0),("u2",4.0),("u3",3.0),("u4",2.0),("u5",1.0),("u6",-1.0),("u7",-2.0),("u8",-3.0),("u9",-4.0),("u10",-5.0)]:
            conn.execute("INSERT INTO universe_returns(signal_date,code,return_path,is_unbuyable) VALUES('2026-08-02',?,?,0)", (code, rp))
        conn.commit()
        conn.close()

        db = str(tmp_path / "evaluation_lifts.db")
        r = apply_revalidation("reverify", db_path=db, gene_scores_db_path=ft_db)
        assert "path_lift" in r["written"]
        d = get_effective_dimension("path_lift", db_path=db)
        assert d is not None
        assert d.days_robust == 2
        assert d.lift == pytest.approx(1.8335, rel=1e-3)


# ---------------------------------------------------------------------------
# evaluation_backtest：到点自动写回 + reminder fallback + not_due
# ---------------------------------------------------------------------------
class _FakeConn:
    """假 conn：evaluation_backtest 的 days/n 双 count（DISTINCT signal_date / is_unbuyable）。"""

    def __init__(self, days, n):
        self._days = days
        self._n = n

    def execute(self, q, *a):
        days, n = self._days, self._n

        class _R:
            def fetchone(_self):
                if "DISTINCT signal_date" in q:
                    return (days,)
                if "is_unbuyable" in q:
                    return (n,)
                return (0,)

        return _R()

    def close(self):
        pass


class TestEvaluationBacktestWriteback:
    def test_not_due_no_writeback(self, monkeypatch, tmp_path):
        import scheduled_tasks as st
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _FakeConn(10, 50))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path),
                            raising=False)
        written = []
        monkeypatch.setattr(
            "scheduler.executors.backtest.apply_revalidation",
            lambda *a, **k: written.append(k.get("phase")) or {"written": [], "errors": []},
        )
        r = st._execute_evaluation_backtest(None, {})
        assert r["status"] == "not_due"
        assert written == []  # 未到期不写回

    def test_first_retrospective_due_writes_back(self, monkeypatch, tmp_path):
        import scheduled_tasks as st
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _FakeConn(40, 150))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path),
                            raising=False)
        monkeypatch.setattr(
            "scheduler.executors.backtest.apply_revalidation",
            lambda phase, **k: {"written": ["path_lift"], "errors": [],
                                "phase": phase},
        )
        r = st._execute_evaluation_backtest(None, {})
        assert r["phase"] == "first_retrospective"
        assert r.get("written_back") == ["path_lift"]
        assert (tmp_path / "s151_evaluation_backtest_due.json").exists()

    def test_reverify_due_writes_back(self, monkeypatch, tmp_path):
        import scheduled_tasks as st
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _FakeConn(65, 200))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path),
                            raising=False)
        monkeypatch.setattr(
            "scheduler.executors.backtest.apply_revalidation",
            lambda phase, **k: {"written": ["breakout"], "errors": [], "phase": phase},
        )
        r = st._execute_evaluation_backtest(None, {})
        assert r["phase"] == "reverify"
        assert r.get("written_back") == ["breakout"]

    def test_compute_empty_falls_back_to_reminder(self, monkeypatch, tmp_path):
        # compute 返空（baostock 不可用等）→ reminder fallback（status due + action 命令）
        import scheduled_tasks as st
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _FakeConn(40, 150))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path),
                            raising=False)
        monkeypatch.setattr(
            "scheduler.executors.backtest.apply_revalidation",
            lambda phase, **k: {"written": [], "errors": [], "phase": phase},
        )
        r = st._execute_evaluation_backtest(None, {})
        assert r["status"] == "due"
        assert r.get("written_back") == []
        assert "action" in r  # reminder 命令串保留
        assert (tmp_path / "s151_evaluation_backtest_due.json").exists()


# ---------------------------------------------------------------------------
# reader 接线：lift_for_arm / scoring 用 effective（override）
# ---------------------------------------------------------------------------
class TestReaderUsesOverride:
    def test_lift_for_arm_uses_override_upgrade(self, tmp_path, monkeypatch):
        # trend 臂单维映射 trend_swing（frozen days=0<60 → ×0.5）；override 升级
        # days=80+lift=2.5 → validated ×1.0。单维臂避免 breakout 多维 min 干扰。
        db = str(tmp_path / "evaluation_lifts.db")
        write_override("trend_swing", lift=2.5, n=600, days_robust=80,
                       phase="reverify", ci_overlap=False, robust=True, db_path=db)
        monkeypatch.setattr("candidate_funnel.lift_override._override_db_path",
                            lambda: db)
        from candidate_funnel.evaluation import lift_for_arm
        mult, note = lift_for_arm("trend")
        assert mult == 1.0, f"override 升级后 trend 臂应 ×1.0，got {mult}（{note}）"

    def test_lift_for_arm_falls_back_to_frozen_no_override(self, tmp_path, monkeypatch):
        monkeypatch.setattr("candidate_funnel.lift_override._override_db_path",
                            lambda: str(tmp_path / "empty.db"))
        from candidate_funnel.evaluation import lift_for_arm
        mult, _ = lift_for_arm("trend")
        assert mult == 0.5  # frozen trend_swing days=0<60 → ×0.5
