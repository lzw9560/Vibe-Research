# -*- coding: utf-8 -*-
"""S206 T2: dual_pressure 诚实降级 test（TDD）。

验证 dual_pressure 从 always-False 改为三态标记：
- "unavailable": 封板检测降级，无法判定（区分"没压力"vs"判不了"）
- "no_pressure": 可确认无双重压力（主板封住→排除炸板未回封）
- "pressure": 双重压力——保留接口，待 P2 5min 分时重建

背景（spec §3.2）：_judge_seal_status 用现价近似（:453 注释自承降级），
结构性无法返回"炸板未回封"（需分时数据 S055 封单时序），故原
`dual_pressure = seal_status == "炸板未回封" and current_zone == "red"` 恒 False，
Layer 2 持仓×情绪联动整层无信息量。

本测试覆盖三个核心用例（task 要求）：
  test_dual_pressure_unavailable_when_seal_degraded
  test_dual_pressure_no_pressure_when_sealed
  test_seal_status_degraded_per_row
"""
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


# ============================================================
# 纯函数测试：_judge_seal_status 结构性无法返回炸板状态
# ============================================================

class TestJudgeSealStatusDegraded:
    """_judge_seal_status 用现价近似，结构性无法判炸板回封/未回封。"""

    def test_sealed_when_near_limit_main_board(self):
        from routers.intraday_sentiment import _judge_seal_status
        result = _judge_seal_status("600519", {"change_pct": 9.9, "current_price": 110}, {})
        assert result == "封住"

    def test_unsealed_when_below_limit(self):
        from routers.intraday_sentiment import _judge_seal_status
        result = _judge_seal_status("600519", {"change_pct": 5.0, "current_price": 105}, {})
        assert result == "未封板"

    def test_no_data_when_quote_missing(self):
        from routers.intraday_sentiment import _judge_seal_status
        result = _judge_seal_status("600519", {}, {})
        assert result == "数据未取得"

    def test_never_returns_broken_unsealed(self):
        """核心：_judge_seal_status 永不返回"炸板未回封"/"炸板回封"。"""
        from routers.intraday_sentiment import _judge_seal_status
        for pct in [0, 5, 9.7, 9.8, 9.9, 10, 15, 20]:
            result = _judge_seal_status("600519", {"change_pct": pct, "current_price": 100}, {})
            assert result != "炸板未回封", f"pct={pct} 不应返回炸板未回封"
            assert result != "炸板回封", f"pct={pct} 不应返回炸板回封"


# ============================================================
# 核心用例 1: test_dual_pressure_unavailable_when_seal_degraded
# ============================================================

class TestDualPressureUnavailable:
    """seal_status 降级时 dual_pressure 标 "unavailable"（非 False）。

    区分"没压力"(no_pressure) vs "判不了"(unavailable)——
    原 always-False 无法区分这两者，是诚实降级要解决的核心问题。
    """

    def test_dual_pressure_unavailable_when_seal_degraded(self):
        """主测试：seal_status 降级 → dual_pressure = "unavailable"。"""
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("未封板", "600519", "red")
        assert result == "unavailable"
        assert result is not False  # 非 False（区分"判不了" vs "没压力"）
        assert result != "no_pressure"  # 非"没压力"

    def test_unavailable_when_no_data(self):
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("数据未取得", "600519", "red")
        assert result == "unavailable"

    def test_unavailable_when_chinext_sealed(self):
        """创业板"封住"→degraded（9.8%阈值对20%限不适用）→unavailable。"""
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("封住", "300750", "red")
        assert result == "unavailable"

    def test_unavailable_when_star_sealed(self):
        """科创板"封住"→degraded（9.8%阈值对20%限不适用）→unavailable。"""
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("封住", "688981", "red")
        assert result == "unavailable"

    def test_unavailable_is_string_not_boolean(self):
        """unavailable 是字符串，非 boolean False。"""
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("未封板", "600519", "red")
        assert isinstance(result, str)
        assert result == "unavailable"


# ============================================================
# 核心用例 2: test_dual_pressure_no_pressure_when_sealed
# ============================================================

class TestDualPressureNoPressureWhenSealed:
    """seal_status='封住'(主板) → dual_pressure 标 "no_pressure"。

    主板"封住"(pct>=9.8) 能确认当前封住→正向排除"炸板未回封"→无双重压力。
    zone 不影响：确认封住即排除炸板，与色带无关。
    """

    def test_dual_pressure_no_pressure_when_sealed(self):
        """主测试：seal_status='封住' + zone='green' → no_pressure。"""
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("封住", "600519", "green")
        assert result == "no_pressure"
        assert result is not False  # 非 False
        assert result != "unavailable"  # 非"判不了"

    def test_no_pressure_when_sealed_red_zone(self):
        """主板"封住"+red zone → no_pressure（确认封住排除炸板，与 zone 无关）。"""
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("封住", "600519", "red")
        assert result == "no_pressure"

    def test_no_pressure_main_board_sh(self):
        """沪市主板"封住"→no_pressure。"""
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("封住", "600000", "yellow")
        assert result == "no_pressure"

    def test_no_pressure_main_board_sz(self):
        """深市主板"封住"→no_pressure。"""
        from routers.intraday_sentiment import _compute_dual_pressure
        result = _compute_dual_pressure("封住", "000001", "yellow")
        assert result == "no_pressure"


# ============================================================
# 核心用例 3: test_seal_status_degraded_per_row
# ============================================================

def _make_client(holdings, quotes, zone, monkeypatch):
    """构造 TestClient，mock workflow_state_repo + astock + _current_zone。"""
    mock_wsr = types.ModuleType("workflow_state_repo")
    mock_wsr.list_states = lambda d: holdings
    monkeypatch.setitem(sys.modules, "workflow_state_repo", mock_wsr)

    mock_astock = types.ModuleType("astock")
    mock_astock.tencent_quote = lambda codes: quotes
    monkeypatch.setitem(sys.modules, "astock", mock_astock)

    from routers.intraday_sentiment import router
    monkeypatch.setattr("routers.intraday_sentiment._current_zone", lambda: zone)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestSealStatusDegradedPerRow:
    """Layer 2 端点响应含 seal_status_degraded per-row 标注。

    per stock-type 条件触发（主板封住不降级，非主板/未封板/无数据降级），
    非全局 flag（不同行可有不同值）。
    """

    def test_seal_status_degraded_per_row(self, monkeypatch):
        """主测试：响应含 seal_status_degraded per-row 字段。"""
        holdings = [{"code": "600519", "name": "贵州茅台", "status": "holding", "entry_price": 100}]
        quotes = [{"code": "600519", "change_pct": 5.0, "current_price": 105}]
        client = _make_client(holdings, quotes, "green", monkeypatch)

        resp = client.get("/api/intraday/sentiment/holdings")
        assert resp.status_code == 200
        body = resp.json()
        row = body["data"]["holdings"][0]
        assert "seal_status_degraded" in row, "每行应含 seal_status_degraded 字段"
        # 未封板 → degraded=True
        assert row["seal_status_degraded"] is True

    def test_degraded_true_when_unsealed(self, monkeypatch):
        holdings = [{"code": "600519", "name": "茅台", "status": "holding", "entry_price": 100}]
        quotes = [{"code": "600519", "change_pct": 5.0, "current_price": 105}]
        client = _make_client(holdings, quotes, "green", monkeypatch)
        resp = client.get("/api/intraday/sentiment/holdings")
        row = resp.json()["data"]["holdings"][0]
        assert row["seal_status"] == "未封板"
        assert row["seal_status_degraded"] is True

    def test_degraded_false_when_main_board_sealed(self, monkeypatch):
        holdings = [{"code": "600519", "name": "茅台", "status": "holding", "entry_price": 100}]
        quotes = [{"code": "600519", "change_pct": 9.9, "current_price": 110}]
        client = _make_client(holdings, quotes, "green", monkeypatch)
        resp = client.get("/api/intraday/sentiment/holdings")
        row = resp.json()["data"]["holdings"][0]
        assert row["seal_status"] == "封住"
        assert row["seal_status_degraded"] is False

    def test_degraded_true_when_no_data(self, monkeypatch):
        holdings = [{"code": "600519", "name": "茅台", "status": "holding", "entry_price": 100}]
        quotes = []  # 无报价
        client = _make_client(holdings, quotes, "green", monkeypatch)
        resp = client.get("/api/intraday/sentiment/holdings")
        row = resp.json()["data"]["holdings"][0]
        assert row["seal_status"] == "数据未取得"
        assert row["seal_status_degraded"] is True

    def test_degraded_true_when_chinext_sealed(self, monkeypatch):
        """创业板"封住"→degraded=True（9.8%阈值对20%限不适用）。"""
        holdings = [{"code": "300750", "name": "宁德时代", "status": "holding", "entry_price": 200}]
        quotes = [{"code": "300750", "change_pct": 9.9, "current_price": 220}]
        client = _make_client(holdings, quotes, "green", monkeypatch)
        resp = client.get("/api/intraday/sentiment/holdings")
        row = resp.json()["data"]["holdings"][0]
        assert row["seal_status"] == "封住"
        assert row["seal_status_degraded"] is True  # 创业板 20% 限→阈值不适用

    def test_degraded_per_row_not_global(self, monkeypatch):
        """seal_status_degraded 是 per-row（不同行有不同值），非全局 flag。"""
        holdings = [
            {"code": "600519", "name": "茅台", "status": "holding", "entry_price": 100},
            {"code": "300750", "name": "宁德时代", "status": "holding", "entry_price": 200},
        ]
        quotes = [
            {"code": "600519", "change_pct": 9.9, "current_price": 110},  # 主板封住→不降级
            {"code": "300750", "change_pct": 5.0, "current_price": 210},  # 创业板未封板→降级
        ]
        client = _make_client(holdings, quotes, "green", monkeypatch)
        resp = client.get("/api/intraday/sentiment/holdings")
        rows = resp.json()["data"]["holdings"]
        main_row = next(r for r in rows if r["code"] == "600519")
        chinext_row = next(r for r in rows if r["code"] == "300750")
        assert main_row["seal_status_degraded"] is False  # 主板封住→不降级
        assert chinext_row["seal_status_degraded"] is True  # 创业板未封板→降级

    def test_dual_pressure_string_in_response(self, monkeypatch):
        """端点响应 dual_pressure 是字符串（unavailable/no_pressure），非 boolean。"""
        holdings = [{"code": "600519", "name": "茅台", "status": "holding", "entry_price": 100}]
        quotes = [{"code": "600519", "change_pct": 5.0, "current_price": 105}]
        client = _make_client(holdings, quotes, "green", monkeypatch)
        resp = client.get("/api/intraday/sentiment/holdings")
        row = resp.json()["data"]["holdings"][0]
        assert row["dual_pressure"] == "unavailable"
        assert isinstance(row["dual_pressure"], str)

    def test_dual_pressure_count_always_zero_when_degraded(self, monkeypatch):
        """dual_pressure_count 恒 0（"pressure"不可达，S206 T2 deprecated）。"""
        holdings = [{"code": "600519", "name": "茅台", "status": "holding", "entry_price": 100}]
        quotes = [{"code": "600519", "change_pct": 5.0, "current_price": 105}]
        client = _make_client(holdings, quotes, "red", monkeypatch)
        resp = client.get("/api/intraday/sentiment/holdings")
        body = resp.json()["data"]
        assert body["dual_pressure_count"] == 0
