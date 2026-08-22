"""S093 飞书通知 + daily_ai_summary stub 测试（TDD）。

契约（spec §3.D R10 + §3.E R12 + §8 盲点 #5/#6）：
- candidate_funnel_precompute success → NotificationService.send() 被调
  + 卡片内容含 F 日期 / final_candidates 数 / 双重确认数
- _compute_dual_confirmation：漏斗 final_candidates ∩ breakout 交集数正确
- daily_ai_summary stub → generate_daily_summary 返空串 + 存储位文件创建
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

import scheduled_tasks as st


# ── 测试辅助 ───────────────────────────────────────────────────────────


def _make_funnel_result(final_candidates_data: list[dict]):
    """构造 funnel result mock（含 final_candidates 列表，每项可 model_dump）。"""

    class _Card:
        def __init__(self, data: dict):
            self._data = data

        def model_dump(self, mode=None):
            return dict(self._data)

    return types.SimpleNamespace(
        final_candidates=[_Card(d) for d in final_candidates_data],
        layers=[],
    )


def _make_breakout_selection(codes: list[str]):
    """构造 select_premarket_with_risk 返回 mock（candidates 含 .code）。"""
    return types.SimpleNamespace(
        candidates=[types.SimpleNamespace(code=c) for c in codes],
    )


class _MockNotificationService:
    """mock NotificationService——捕获 send() 调用内容。"""

    def __init__(self):
        self.sent: list[str] = []

    def is_available(self) -> bool:
        return True

    def send(self, content: str, **kwargs) -> bool:
        self.sent.append(content)
        return True


# ── candidate_funnel_precompute 通知触发 ─────────────────────────────


class TestCandidateFunnelPrecomputeNotification:
    """precompute success → 飞书通知触发 + 内容断言。"""

    def test_notification_sent_with_date_and_counts(self, monkeypatch):
        """precompute success → send() 被调 + 内容含 F日期/final_candidates数/双重确认数。"""
        # Arrange
        target = "2026-08-21"
        final_cands = [
            {"code": "000001", "name": "平安银行", "gene_score": {"total_score": 65.0}},
            {"code": "000002", "name": "万科A", "gene_score": {"total_score": 55.0}},
            {"code": "600519", "name": "贵州茅台", "gene_score": {"total_score": 70.0}},
        ]
        funnel_result = _make_funnel_result(final_cands)

        # mock funnel run + cache save
        import candidate_funnel.funnel as funnel_mod
        monkeypatch.setattr(funnel_mod, "run_funnel", lambda *a, **kw: funnel_result)
        import candidate_funnel.funnel_cache as fc_mod
        monkeypatch.setattr(fc_mod, "save_funnel_result", lambda *a, **kw: None)

        # mock dual confirmation + strategy map（避免重计算）
        monkeypatch.setattr(st, "_compute_dual_confirmation", lambda t, fc: 2)
        monkeypatch.setattr(st, "_compute_strategy_map", lambda t: {"000001": ["首板战法"]})

        # mock NotificationService
        mock_ns = _MockNotificationService()
        monkeypatch.setattr(
            "notification.notification_service.NotificationService",
            lambda *a, **kw: mock_ns,
        )

        # Act
        executor = st.TaskExecutor()
        result = executor._execute_candidate_funnel_precompute({"date": target})

        # Assert
        assert result["status"] == "ok"
        assert result["final_candidates_count"] == 3
        assert result["dual_confirmation_count"] == 2
        assert len(mock_ns.sent) == 1
        content = mock_ns.sent[0]
        assert target in content  # F 日期
        assert "3" in content  # final_candidates 数
        assert "2" in content  # 双重确认数

    def test_notification_not_sent_when_unavailable(self, monkeypatch):
        """NotificationService 不可用时 send 不被调，但预计算仍 success。"""
        # Arrange
        target = "2026-08-21"
        funnel_result = _make_funnel_result([])

        import candidate_funnel.funnel as funnel_mod
        monkeypatch.setattr(funnel_mod, "run_funnel", lambda *a, **kw: funnel_result)
        import candidate_funnel.funnel_cache as fc_mod
        monkeypatch.setattr(fc_mod, "save_funnel_result", lambda *a, **kw: None)
        monkeypatch.setattr(st, "_compute_dual_confirmation", lambda t, fc: 0)
        monkeypatch.setattr(st, "_compute_strategy_map", lambda t: {})

        class _UnavailableNS:
            def is_available(self):
                return False

            def send(self, content, **kw):
                raise AssertionError("不可用时不应调 send")

        monkeypatch.setattr(
            "notification.notification_service.NotificationService",
            lambda *a, **kw: _UnavailableNS(),
        )

        # Act
        executor = st.TaskExecutor()
        result = executor._execute_candidate_funnel_precompute({"date": target})

        # Assert
        assert result["status"] == "ok"
        assert result["final_candidates_count"] == 0

    def test_notification_failure_does_not_block_precompute(self, monkeypatch):
        """NotificationService.send() 抛异常 → 预计算仍 success（增强不阻断）。"""
        # Arrange
        target = "2026-08-21"
        funnel_result = _make_funnel_result(
            [{"code": "000001", "name": "test", "gene_score": {"total_score": 60.0}}]
        )

        import candidate_funnel.funnel as funnel_mod
        monkeypatch.setattr(funnel_mod, "run_funnel", lambda *a, **kw: funnel_result)
        import candidate_funnel.funnel_cache as fc_mod
        monkeypatch.setattr(fc_mod, "save_funnel_result", lambda *a, **kw: None)
        monkeypatch.setattr(st, "_compute_dual_confirmation", lambda t, fc: 0)
        monkeypatch.setattr(st, "_compute_strategy_map", lambda t: {})

        class _BoomNS:
            def is_available(self):
                return True

            def send(self, content, **kw):
                raise RuntimeError("飞书挂了")

        monkeypatch.setattr(
            "notification.notification_service.NotificationService",
            lambda *a, **kw: _BoomNS(),
        )

        # Act
        executor = st.TaskExecutor()
        result = executor._execute_candidate_funnel_precompute({"date": target})

        # Assert
        assert result["status"] == "ok"  # 通知失败不阻断
        assert result["final_candidates_count"] == 1


# ── _compute_dual_confirmation 交集逻辑 ──────────────────────────────


class TestDualConfirmation:
    """漏斗 final_candidates ∩ breakout 交集数。"""

    def test_intersection_count(self, monkeypatch):
        """funnel {001,002,003} ∩ breakout {002,004} → 1。"""
        # Arrange
        target = "2026-08-21"
        final_cards = [
            {"code": "000001"}, {"code": "000002"}, {"code": "000003"},
        ]
        # mock select_premarket_with_risk
        monkeypatch.setattr(
            "strategies.premarket_selection.select_premarket_with_risk",
            lambda forward: _make_breakout_selection(["000002", "000004"]),
        )

        # Act
        count = st._compute_dual_confirmation(target, final_cards)

        # Assert
        assert count == 1

    def test_empty_intersection(self, monkeypatch):
        """funnel {001} ∩ breakout {002} → 0。"""
        target = "2026-08-21"
        monkeypatch.setattr(
            "strategies.premarket_selection.select_premarket_with_risk",
            lambda forward: _make_breakout_selection(["000002"]),
        )
        count = st._compute_dual_confirmation(target, [{"code": "000001"}])
        assert count == 0

    def test_failure_returns_zero(self, monkeypatch):
        """select_premarket_with_risk 抛异常 → 返 0（不臆造）。"""
        target = "2026-08-21"

        def boom(forward):
            raise RuntimeError("kline cache 不存在")

        monkeypatch.setattr(
            "strategies.premarket_selection.select_premarket_with_risk", boom,
        )
        count = st._compute_dual_confirmation(target, [{"code": "000001"}])
        assert count == 0


# ── daily_ai_summary stub ─────────────────────────────────────────────


class TestDailyAISummary:
    """generate_daily_summary stub + _execute_daily_ai_summary executor。"""

    def test_generate_returns_empty_and_creates_file(self, tmp_path, monkeypatch):
        """stub 返空串 + 存储位文件创建。"""
        # Arrange
        from vr_paths import resolve_data_dir
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path))
        date = "2026-08-21"

        # Act
        summary = st.generate_daily_summary(date)

        # Assert
        assert summary == ""  # stub 返空串
        expected_path = tmp_path / "daily_summaries" / f"{date}.txt"
        assert expected_path.exists()  # 存储位文件已创建

    def test_executor_returns_status(self, monkeypatch):
        """_execute_daily_ai_summary 返 ok + summary_length=0。"""
        # Arrange
        from vr_paths import resolve_data_dir
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: "/tmp/vr-test-summaries")
        monkeypatch.setattr(
            "vr_paths.last_trading_date_str", lambda: "2026-08-21",
        )

        # Act
        executor = st.TaskExecutor()
        result = executor._execute_daily_ai_summary({})

        # Assert
        assert result["status"] == "ok"
        assert result["summary_length"] == 0
        assert "2026-08-21" in (result["date"] or "")


# ── 通知内容结构断言 ─────────────────────────────────────────────────


class TestNotificationContent:
    """_build_premarket_notification_content 内容结构。"""

    def test_content_has_all_required_fields(self):
        """内容含 F 日期 + 候选数 + 双重确认数 + top5 + 风险提醒。"""
        # Arrange
        final_cards = [
            {"code": "000001", "name": "平安银行", "gene_score": {"total_score": 65.0}},
            {"code": "000002", "name": "万科A", "gene_score": {"total_score": 55.0}},
        ]
        strategy_map = {"000001": ["首板战法", "连板接力"]}

        # Act
        content = st._build_premarket_notification_content(
            "2026-08-21", final_cards, dual_count=1, strategy_map=strategy_map,
        )

        # Assert
        assert "2026-08-21" in content  # F 日期
        assert "2" in content  # final_candidates 数
        assert "1" in content  # 双重确认数
        assert "平安银行" in content  # top5 标的名
        assert "000001" in content  # top5 code
        assert "65" in content  # 基因分
        assert "首板战法" in content  # 命中战法
        assert "连板接力" in content  # 命中战法
        assert "市场有风险" in content  # 风险提醒

    def test_content_empty_final_candidates(self):
        """空 final_candidates → 内容仍含日期+0只+风险提醒（不崩）。"""
        content = st._build_premarket_notification_content(
            "2026-08-21", [], dual_count=0, strategy_map={},
        )
        assert "2026-08-21" in content
        assert "市场有风险" in content
