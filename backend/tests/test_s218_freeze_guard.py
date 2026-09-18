# -*- coding: utf-8 -*-
"""S218 #7 ×1.0 freeze 升级守卫测试。

守卫语义：当 regime_caps[regime] == 1.0（升级方向）时，lift_for_arm 拒绝返 ×1.0
除非 fresh harness verdict 许可（env VR_ALLOW_X1DOT0=1 或 module global
_FRESH_HARNESS_VERDICT=True）。无许可 → 保守 ×0.75。

§44 v2（s44_verifier/stats.py:483 decision rule）：oos_supporting caps at ×0.75
NOT ×1.0 until cross-regime replication。freeze 守卫把这个诚实 gate 从 harness
decision rule 接到生产 lift_for_arm —— 防止任何未来 session 把 frozen
regime_caps bull 0.75→1.0 零代码阻力直接全权重。

限定：只守升级（cap==1.0）；降级（<0.75）或 ×0.75 正常路径不守。

纯离线：monkeypatch get_effective_dimension 返定制 regime_caps 的 DimensionValidation
（隔离 frozen registry）；autouse fixture 跳过 arm_status DB 查询（隔离 TradeJournal）。
"""
from __future__ import annotations

from dataclasses import replace

import pytest

import candidate_funnel.evaluation as evaluation
import candidate_funnel.lift_override as lift_override
import engine.trade_journal as trade_journal
from candidate_funnel.evaluation import DimensionValidation, lift_for_arm


def _dim_with_regime_caps(regime_caps: dict | None) -> DimensionValidation:
    """构造测试用 DimensionValidation（regime_caps 可定制，其余字段非冻结值无关）。"""
    return DimensionValidation(
        dimension_id="consecutive_relay",
        label="连板接力臂(test fixture)",
        lift=None, n=1283, days_robust=172,
        validation_status="robust_edge",
        weight_multiplier=0.5,  # regime=None 保守 fallback（freeze 守卫不涉及此分支）
        source_script="tools/s203_consecutive_relay_harness.py",
        note="test fixture for x1.0 freeze guard",
        regime_caps=regime_caps,
    )


@pytest.fixture(autouse=True)
def _isolate_arm_status(monkeypatch):
    """跳过 arm_status DB 查询（隔离 freeze guard 逻辑，不受 dev DB 状态影响）。"""
    monkeypatch.setattr(trade_journal.TradeJournal, "query_arm_status", lambda self, arm: None)


@pytest.fixture(autouse=True)
def _reset_freeze_state(monkeypatch):
    """每个 test 默认无 fresh harness 许可 + 无 env（test 可覆盖）。"""
    monkeypatch.delenv("VR_ALLOW_X1DOT0", raising=False)
    monkeypatch.setattr(evaluation, "_FRESH_HARNESS_VERDICT", False, raising=False)


class TestX1Dot0FreezeGuard:
    """S218 #7：regime_caps==1.0 升级须 fresh harness 许可。"""

    def test_freeze_blocks_x1dot0_without_permission(self, monkeypatch):
        # regime_caps={bull:1.0} + 无 VR_ALLOW_X1DOT0 + _FRESH_HARNESS_VERDICT=False
        # → lift_for_arm 返 ×0.75（freeze 守卫降级，非 ×1.0）
        monkeypatch.setattr(lift_override, "get_effective_dimension",
                            lambda dim_id, db_path=None: _dim_with_regime_caps({"bull": 1.0}))
        mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 0.75
        assert "freeze" in note.lower()

    def test_freeze_allows_x1dot0_with_env_permission(self, monkeypatch):
        # regime_caps={bull:1.0} + VR_ALLOW_X1DOT0=1 → 返 ×1.0（许可）
        monkeypatch.setattr(lift_override, "get_effective_dimension",
                            lambda dim_id, db_path=None: _dim_with_regime_caps({"bull": 1.0}))
        monkeypatch.setenv("VR_ALLOW_X1DOT0", "1")
        mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 1.0
        assert "许可" in note

    def test_freeze_allows_x1dot0_with_global_flag(self, monkeypatch):
        # regime_caps={bull:1.0} + module global _FRESH_HARNESS_VERDICT=True → 返 ×1.0
        monkeypatch.setattr(lift_override, "get_effective_dimension",
                            lambda dim_id, db_path=None: _dim_with_regime_caps({"bull": 1.0}))
        monkeypatch.setattr(evaluation, "_FRESH_HARNESS_VERDICT", True, raising=False)
        mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 1.0
        assert "许可" in note

    def test_freeze_not_triggered_for_x0dot75(self, monkeypatch):
        # regime_caps={bull:0.75} → 返 ×0.75（不守，正常路径；status_note 无 freeze 字样）
        monkeypatch.setattr(lift_override, "get_effective_dimension",
                            lambda dim_id, db_path=None: _dim_with_regime_caps({"bull": 0.75}))
        mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 0.75
        assert "freeze" not in note.lower()

    def test_freeze_not_triggered_for_downgrade_below_x0dot75(self, monkeypatch):
        # regime_caps={bull:0.5}（降级 <0.75）→ 返 ×0.5（不守，正常降级路径）
        monkeypatch.setattr(lift_override, "get_effective_dimension",
                            lambda dim_id, db_path=None: _dim_with_regime_caps({"bull": 0.5}))
        mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 0.5
        assert "freeze" not in note.lower()


class TestX1Dot0FreezeGuardRegression:
    """S218 #7 回归保护：防 future session 破坏 freeze guard。

    与 TestX1Dot0FreezeGuard（monkeypatch 整个 get_effective_dimension）互补——这里走真实
    get_effective_dimension → 真实 lift_for_arm 路径，仅 monkeypatch frozen registry 数据 +
    隔离 override DB。捕获两类回归：① guard 逻辑被移除/绕过（仍走真实路径会暴露）；
    ② frozen regime_caps 被静默改 bull 0.75→1.0 而无 fresh harness 许可。
    """

    @pytest.fixture(autouse=True)
    def _isolate_override_db(self, monkeypatch):
        """隔离 override DB + 清 cache：强制 fallback frozen baseline，测真实 frozen 数据。

        _read_override_row→None 让 get_effective_dimension 走 frozen baseline 分支
        （lift_override.py:189-191），不受 dev DB override 状态干扰。清 _EFFECTIVE_CACHE
        防 stale cache 屏蔽 registry mutation。
        """
        monkeypatch.setattr(lift_override, "_read_override_row",
                            lambda conn, dim_id: None)
        lift_override._EFFECTIVE_CACHE.clear()
        yield
        lift_override._EFFECTIVE_CACHE.clear()

    def test_freeze_guard_survives_registry_edit(self, monkeypatch):
        # 模拟 future session 编辑 frozen regime_caps bull 0.75→1.0（无 fresh harness 许可）
        # → freeze guard 仍生效：返 ×0.75（非 ×1.0），note 含 "freeze"
        # 走真实 get_effective_dimension：若 guard 逻辑被移除，mult 会变 1.0 → assert 失败
        frozen_dim = lift_override.DIMENSION_LIFT_REGISTRY["consecutive_relay"]
        edited = replace(frozen_dim,
                         regime_caps={"bull": 1.0, "bear": 0.5, "range": 0.5})
        monkeypatch.setitem(lift_override.DIMENSION_LIFT_REGISTRY,
                            "consecutive_relay", edited)
        mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 0.75
        assert "freeze" in note.lower()

    def test_freeze_guard_bypass_with_fresh_harness(self, monkeypatch):
        # 合法升级路径：registry 编辑 bull→1.0 + VR_ALLOW_X1DOT0=1 +
        # _FRESH_HARNESS_VERDICT=True（fresh harness 许可）→ 返 ×1.0
        # 走真实 get_effective_dimension：防 guard 误挡合法升级（over-blocking 回归）
        frozen_dim = lift_override.DIMENSION_LIFT_REGISTRY["consecutive_relay"]
        edited = replace(frozen_dim,
                         regime_caps={"bull": 1.0, "bear": 0.5, "range": 0.5})
        monkeypatch.setitem(lift_override.DIMENSION_LIFT_REGISTRY,
                            "consecutive_relay", edited)
        monkeypatch.setenv("VR_ALLOW_X1DOT0", "1")
        monkeypatch.setattr(evaluation, "_FRESH_HARNESS_VERDICT", True, raising=False)
        mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 1.0
        assert "许可" in note

    def test_freeze_guard_not_broken_by_consecutive_relay_default(self):
        # 当前 frozen consecutive_relay bull=0.75（registry:102）→ 返 ×0.75
        # 正常路径，guard 不守（cap!=1.0），note 无 "freeze"。
        # 回归 alert：若 future session 改 frozen bull→1.0 而无许可，guard 会触发，
        # note 进 "freeze" → 此 assert 失败，暴露静默升级。
        mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 0.75
        assert "freeze" not in note.lower()
