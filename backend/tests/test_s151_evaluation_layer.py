# -*- coding: utf-8 -*-
"""S151 漏斗评价层测试（R1-R5 + R3）。

覆盖：
- R1 DIMENSION_LIFT_REGISTRY 冻结值完整性（5 维度 + vol_surge 参照，frozen_commit 非空）
- R2 lift_to_multiplier 四态映射（劣于随机/未validated/validated/探索性/待复验）
- R5 _apply_evaluation_layer 即时处理（turnover demoted + gene unranked + normal）+ 诚实标注
- R3 evaluation_backtest executor（30日首次/60日复验/not_due 双门槛 + checkpoint 写盘）

纯离线：R1/R2/R5 直接调函数（无 DB），R3 用 _FakeConn2 monkeypatch sqlite3.connect
（同 test_task_executor.TestS066ValidationCheckpoint 范式——get_healthy_conn 内部走 sqlite3.connect）。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from candidate_funnel.evaluation import (
    DIMENSION_LIFT_REGISTRY,
    FROZEN_COMMIT,
    lift_to_multiplier,
    _apply_evaluation_layer,
)
import scheduled_tasks as st


# ---------------------------------------------------------------------------
# R1：DIMENSION_LIFT_REGISTRY 冻结值完整性（禁臆造——全来自 §44 脚本输出）
# ---------------------------------------------------------------------------
class TestDimensionLiftRegistry:
    def test_registry_has_all_twelve_dimensions(self):
        # 选股 5 + 盘中 S152 2 + breakout 精细化 S153 2 + 板块/regime 2 + 参照 1 = 12
        ids = set(DIMENSION_LIFT_REGISTRY.keys())
        assert ids == {"gene_score", "breakout", "turnover", "seal_amount",
                       "path_lift", "first_plate_h2", "late_lock", "vol_surge_ref",
                       "platform_breakout", "low_absorption", "sector_heat", "sector_phase"}

    def test_all_dimensions_have_frozen_commit(self):  # A1
        for dim_id, dim in DIMENSION_LIFT_REGISTRY.items():
            assert dim.frozen_commit == FROZEN_COMMIT, f"{dim_id} frozen_commit mismatch"
            assert dim.frozen_commit, f"{dim_id} frozen_commit empty"

    def test_frozen_values_match_spec(self):
        # R1 spec 冻结值（来自 §44 脚本输出，禁心算）
        g = DIMENSION_LIFT_REGISTRY["gene_score"]
        assert g.lift == pytest.approx(0.030)
        assert g.weight_multiplier == 0.1
        assert g.validation_status == "劣于随机"
        b = DIMENSION_LIFT_REGISTRY["breakout"]
        assert b.lift == pytest.approx(1.363)
        assert b.weight_multiplier == 0.5  # §F：按梯度 ×0.5（非用户框架 ×0.1）
        assert b.validation_status == "未validated"
        t = DIMENSION_LIFT_REGISTRY["turnover"]
        assert t.lift == pytest.approx(0.9979)
        assert t.weight_multiplier == 0.1
        assert t.validation_status == "劣于随机"
        s = DIMENSION_LIFT_REGISTRY["seal_amount"]
        assert s.weight_multiplier == 1.0  # 探索性（n 小 + 5 日非 robust）
        assert s.validation_status == "探索性"
        p = DIMENSION_LIFT_REGISTRY["path_lift"]
        assert p.lift == pytest.approx(0.978)
        assert p.weight_multiplier == 0.1
        v = DIMENSION_LIFT_REGISTRY["vol_surge_ref"]
        assert v.weight_multiplier == 0.5  # S155 证伪：per-T 1.974<2→未validated×0.5（参照不参与选股降权，never applied）

    def test_source_script_non_empty(self):
        # 禁臆造溯源：每维度 source_script 非空
        for dim_id, dim in DIMENSION_LIFT_REGISTRY.items():
            assert dim.source_script, f"{dim_id} source_script empty"


# ---------------------------------------------------------------------------
# R2：lift_to_multiplier 四态映射（纯函数）
# ---------------------------------------------------------------------------
class TestLiftToMultiplier:
    def test_turnover_robust_below_1_is_demoted(self):  # A2
        # days≥60 + lift<1 + robust → 劣于随机 ×0.1
        status, mult = lift_to_multiplier(0.9979, 14366, robust=True, days_robust=167)
        assert status == "劣于随机"
        assert mult == 0.1

    def test_breakout_between_1_and_2_is_unvalidated(self):  # A3
        status, mult = lift_to_multiplier(1.363, 43691, robust=True, days_robust=60)
        assert status == "未validated"
        assert mult == 0.5

    def test_vol_surge_above_2_no_overlap_is_validated(self):  # A4
        # days≥60 + lift≥2 + CI不重叠 → validated ×1.0（reconcile: 与 verifier robust_edge 一致）
        status, mult = lift_to_multiplier(2.046, 43691, ci_overlap=False, robust=True, days_robust=60)
        assert status == "validated"
        assert mult == 1.0

    def test_n_below_30_is_exploratory(self):
        # n<30 + days≥60 → 探索性 ×1.0
        status, mult = lift_to_multiplier(2.5, 29, ci_overlap=False, robust=True, days_robust=60)
        assert status == "探索性"
        assert mult == 1.0

    def test_lift_none_is_exploratory(self):
        # lift=None + days≥60 → 探索性 ×1.0
        status, mult = lift_to_multiplier(None, 100, days_robust=60)
        assert status == "探索性"
        assert mult == 1.0

    def test_lift_above_2_ci_overlap_is_pending_reverify(self):
        # lift≥2 + CI 重叠 + days≥60 → 待复验 ×1.0
        status, mult = lift_to_multiplier(2.1, 100, ci_overlap=True, robust=True, days_robust=60)
        assert status == "待复验"
        assert mult == 1.0

    # --- R8 §44v2: days_robust<60 provisional cap ×0.5 ---

    def test_days_below_60_lift_above_2_provisional_cap(self):
        # §44v2 reconcile: lift≥2 but days<60 → 不能 validated → 待复验 ×0.5
        # (gap 42-day run would get this, not "validated ×1.0")
        status, mult = lift_to_multiplier(2.5, 500, ci_overlap=False, robust=True, days_robust=42)
        assert status == "待复验"
        assert mult == 0.5

    def test_days_below_60_lift_below_1_cannot_falsify(self):
        # §44v2 R6: lift<1 but days<60 → 不能证否 → 待复验 ×0.5（非 劣于随机 ×0.1）
        status, mult = lift_to_multiplier(0.03, 2332, robust=True, days_robust=38)
        assert status == "待复验"
        assert mult == 0.5

    def test_days_below_60_between_1_and_2_unvalidated(self):
        # 1≤lift<2 + days<60 → 未validated ×0.5（cap 不变）
        status, mult = lift_to_multiplier(1.36, 43691, robust=True, days_robust=42)
        assert status == "未validated"
        assert mult == 0.5

    def test_days_below_60_n_below_30_exploratory_capped(self):
        # n<30 + days<60 → 探索性 ×0.5（provisional cap, 非 ×1.0）
        status, mult = lift_to_multiplier(2.5, 29, ci_overlap=False, robust=True, days_robust=5)
        assert status == "探索性"
        assert mult == 0.5

    def test_days_below_60_lift_none_exploratory_capped(self):
        # lift=None + days<60 → 探索性 ×0.5
        status, mult = lift_to_multiplier(None, 100, days_robust=5)
        assert status == "探索性"
        assert mult == 0.5

    def test_gap_42_day_underpowered_not_validated(self):
        # §44v2 reconcile: gap days_robust=42<60 → 即使 lift≥2 也不 validated ×1.0
        # verifier 说 underpowered, lift_to_multiplier 也说 待复验 ×0.5（不再两套不一致判据）
        status, mult = lift_to_multiplier(2.1, 2700, ci_overlap=False, robust=True, days_robust=42)
        assert status == "待复验"
        assert mult == 0.5

    def test_days_exactly_60_sufficient(self):
        # days=60 → days_sufficient=True（边界值，≥60）
        status, mult = lift_to_multiplier(2.5, 500, ci_overlap=False, robust=True, days_robust=60)
        assert status == "validated"
        assert mult == 1.0


# ---------------------------------------------------------------------------
# R5：_apply_evaluation_layer 即时处理 + 诚实标注
# ---------------------------------------------------------------------------
class TestApplyEvaluationLayer:
    def test_turnover_demoted(self):  # A6
        card = SimpleNamespace(code="000001", gene_score=None)
        activity = {"000001": {"turnover_pct": 35.0}}
        cards, _ = _apply_evaluation_layer([card], {}, activity, None, "2026-09-05")
        assert cards[0].evaluation["lift_status"] == "demoted"
        assert cards[0].evaluation["score_weight"] == 0.1
        assert "turnover" in cards[0].evaluation["demoted_dims"]

    def test_gene_unranked(self):  # A7
        # R8: gene days_robust=38<60 → lift_to_multiplier 返 待复验 ×0.5（provisional cap）
        # 非 frozen ×0.1（days<60 不能证否，R6 gate）
        card = SimpleNamespace(code="000001", gene_score={"total_score": 50})
        cards, _ = _apply_evaluation_layer([card], {}, {}, None, "2026-09-05")
        assert cards[0].evaluation["lift_status"] == "unranked"
        assert cards[0].evaluation["score_weight"] == 0.5
        assert "gene_score" in cards[0].evaluation["demoted_dims"]

    def test_both_turnover_and_gene_double_demotion(self):
        # R8: turnover ×0.1（days=167≥60, lift<1→劣于随机）+ gene ×0.5（days=38<60→待复验）
        # score_weight = 0.1 × 0.5 = 0.05
        card = SimpleNamespace(code="000001", gene_score={"total_score": 50})
        activity = {"000001": {"turnover_pct": 35.0}}
        cards, _ = _apply_evaluation_layer([card], {}, activity, None, "2026-09-05")
        assert cards[0].evaluation["lift_status"] == "demoted"
        assert cards[0].evaluation["score_weight"] == 0.05
        assert set(cards[0].evaluation["demoted_dims"]) == {"turnover", "gene_score"}

    def test_normal_card_no_demotion(self):
        card = SimpleNamespace(code="000001", gene_score=None)
        cards, _ = _apply_evaluation_layer([card], {}, {}, None, "2026-09-05")
        assert cards[0].evaluation["lift_status"] == "normal"
        assert cards[0].evaluation["score_weight"] == 1.0

    def test_evaluation_none_when_card_frozen_no_eval_field(self):  # A8
        # card 无 evaluation 字段（R4 未实现时）→ 设值抛 AttributeError 被捕获不阻断
        @dataclass(frozen=True)
        class _FrozenCard:
            code: str
            gene_score: object = None

        card = _FrozenCard("000001")
        cards, summary = _apply_evaluation_layer([card], {}, {}, None, "2026-09-05")
        assert not hasattr(card, "evaluation")  # 未注入（frozen 拒绝）
        # evaluation_summary 仍构建（不依赖 card 注入成功）
        assert summary["honest_label"] == "选股层无validated维度,edge待盘中验证"

    def test_evaluation_summary_shape(self):  # A5
        _, summary = _apply_evaluation_layer([], {}, {}, None, "2026-09-05")
        assert summary["honest_label"] == "选股层无validated维度,edge待盘中验证"
        # 11 维度（排 vol_surge_ref 参照；含 S152 first_plate_h2/late_lock + S153 platform_breakout/low_absorption + 板块 sector_heat/sector_phase）
        assert len(summary["dimensions"]) == 11
        dim_ids = {d["dimension_id"] for d in summary["dimensions"]}
        assert dim_ids == {"gene_score", "breakout", "turnover", "seal_amount",
                           "path_lift", "first_plate_h2", "late_lock",
                           "platform_breakout", "low_absorption", "sector_heat", "sector_phase"}
        assert "seal_amount" in summary["pending_dims"]  # 探索性
        assert summary["frozen_commit"] == FROZEN_COMMIT


# ---------------------------------------------------------------------------
# R3：evaluation_backtest executor（30日首次/60日复验提醒，复用 s066 范式）
# ---------------------------------------------------------------------------
class _FakeConn2:
    """假 conn：按 query 关键字返 days/n 双 count（evaluation_backtest 双查询）。

    get_healthy_conn 内部 sqlite3.connect → 被 monkeypatch sqlite3.connect 拦截；
    row_factory 赋值无 __slots__ 接受；PRAGMA execute 返 _R（fetchone 返 (0,)，结果被忽略）。
    """

    def __init__(self, days: int, n: int):
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
                return (0,)  # PRAGMA journal_mode=... 等忽略

        return _R()

    def close(self):
        pass


class TestEvaluationBacktest:
    def test_not_due_days_accumulating(self, monkeypatch):  # A14 未到期
        monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: _FakeConn2(10, 50))
        r = st._execute_evaluation_backtest(None, {})
        assert r["status"] == "not_due"
        assert r["signal_days"] == 10
        assert r["picks_n"] == 50
        assert "10/30" in r["note"]

    def test_not_due_n_accumulating(self, monkeypatch):
        # days≥30 但 n<100 → n 积累中（第二档门槛）
        monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: _FakeConn2(35, 50))
        r = st._execute_evaluation_backtest(None, {})
        assert r["status"] == "not_due"
        assert r["signal_days"] == 35
        assert "n=50/100" in r["note"]

    def test_first_retrospective_due_writes_checkpoint(self, monkeypatch, tmp_path):  # A14
        # 30≤days<60 + n≥100 → 首次回溯 DUE
        monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: _FakeConn2(40, 150))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path), raising=False)
        r = st._execute_evaluation_backtest(None, {})
        assert r["status"] == "due"
        assert r["phase"] == "first_retrospective"
        assert r["signal_days"] == 40
        assert r["picks_n"] == 150
        assert "first_board_layer_lift" in r["action"]
        assert (tmp_path / "s151_evaluation_backtest_due.json").exists()

    def test_reverify_due(self, monkeypatch, tmp_path):  # A14
        # days≥60 → 复验 DUE
        monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: _FakeConn2(65, 200))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path), raising=False)
        r = st._execute_evaluation_backtest(None, {})
        assert r["status"] == "due"
        assert r["phase"] == "reverify"
        assert "升级/降级" in r["action"]
        assert (tmp_path / "s151_evaluation_backtest_due.json").exists()

    def test_registered_in_executors(self):
        # R3 executor 在 TaskExecutor._executors 注册
        from scheduled_tasks import TaskExecutor
        assert "evaluation_backtest" in TaskExecutor()._executors
