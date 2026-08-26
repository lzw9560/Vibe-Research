# -*- coding: utf-8 -*-
"""S075 Phase 3 建仓+卖出单测（tasks.md 051-052）。

覆盖：
- 051 建仓选股（绿灯5/黄灯3/红灯0/不足N只/评分排序/止盈止损线）
- 052 止盈止损（止盈/止损/hold/默认卖/数据缺失）+ 端到端 + 通知阈值

mock 模式：monkeypatch 改 tencent_quote + NotificationService
- tencent_quote(codes) -> {code: {open: price}}
- NotificationService().is_available() / .send(content, ...)
"""

from unittest.mock import MagicMock

import pytest


# ── 公共 mock 工厂 ───────────────────────────────────────────────────

def _make_open_confirmed(n: int = 3, base_score: float = 60.0) -> list[dict]:
    """构造 N 只 open_confirmed 候选（已按 total 降序）。"""
    out = []
    for i in range(n):
        code = f"00000{i+1}"
        out.append({
            "code": code, "name": f"测试股{i+1}",
            "total": round(base_score - i * 2.0, 1),  # 降序
            "open_held": True, "vol_ratio": 1.8, "confirmed": True,
        })
    return out


def _make_tencent_quote(codes: list[str], open_price: float = 10.0) -> dict:
    """构造 tencent_quote 返回（dict[code, dict]，含 open 字段）。"""
    return {c: {"name": "测试", "open": open_price, "price": open_price,
                "last_close": 9.8, "vol_ratio": 1.8, "amount_wan": 5000.0}
            for c in codes}


def _mock_notification_service(monkeypatch, available: bool = True, send_ok: bool = True):
    """mock NotificationService 类（patch 构造函数返回 MagicMock）。"""
    mock_ns = MagicMock()
    mock_ns.is_available.return_value = available
    mock_ns.send.return_value = send_ok
    # patch notification.notification_service.NotificationService 为返回 mock_ns 的可调用对象
    mock_cls = MagicMock(return_value=mock_ns)
    monkeypatch.setattr(
        "notification.notification_service.NotificationService", mock_cls
    )
    return mock_ns


# =========================================================================
# 051 建仓选股
# =========================================================================

class TestSelectForEntry:
    """051：测试建仓选股。"""

    def test_green_light_max_5(self, monkeypatch):
        """绿灯最多 5 只，等权 25% 仓位。"""
        from strategies.first_board_position import select_for_entry, POSITION_PARAMS
        cands = _make_open_confirmed(6, base_score=65.0)  # 6 只
        codes = [c["code"] for c in cands[:5]]
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        out = select_for_entry(cands, "green")
        assert len(out) == 5  # 只取前 5 只
        assert all(s["position_pct"] == POSITION_PARAMS["green_weight"] for s in out)
        # entry_rank 1-5
        assert [s["entry_rank"] for s in out] == [1, 2, 3, 4, 5]
        # 第 6 只不应出现
        assert all(s["code"] != cands[5]["code"] for s in out)

    def test_yellow_light_max_3(self, monkeypatch):
        """黄灯最多 3 只，各 15% 仓位。"""
        from strategies.first_board_position import select_for_entry, POSITION_PARAMS
        cands = _make_open_confirmed(5, base_score=65.0)  # 5 只
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        out = select_for_entry(cands, "yellow")
        assert len(out) == 3  # 只取前 3 只
        assert all(s["position_pct"] == POSITION_PARAMS["yellow_weight"] for s in out)
        assert [s["entry_rank"] for s in out] == [1, 2, 3]

    def test_red_light_zero(self, monkeypatch):
        """红灯 0 只（暴风雨 0 仓位硬约束）。"""
        from strategies.first_board_position import select_for_entry
        cands = _make_open_confirmed(5, base_score=65.0)
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        out = select_for_entry(cands, "red")
        assert len(out) == 0  # 0 仓位硬约束

    def test_fewer_than_max(self, monkeypatch):
        """不足 N 只时只买确认的（宁缺毋滥）。"""
        from strategies.first_board_position import select_for_entry
        cands = _make_open_confirmed(2, base_score=65.0)  # 只 2 只
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        out = select_for_entry(cands, "green")  # 绿灯 5 上限，但只 2 只
        assert len(out) == 2
        assert [s["entry_rank"] for s in out] == [1, 2]

    def test_select_preserves_input_order_when_no_timestamp(self, monkeypatch):
        """S098：无 timestamp 时稳定保留输入序（不按 total auto-rank，§44 合规）。"""
        from strategies.first_board_position import select_for_entry
        cands = [
            {"code": "000003", "name": "C", "total": 55.0},
            {"code": "000001", "name": "A", "total": 65.0},
            {"code": "000002", "name": "B", "total": 60.0},
        ]
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        out = select_for_entry(cands, "green")
        # S098：无 timestamp → 稳定保留输入序（不按 total 重排，§44 不 auto-rank）
        assert out[0]["code"] == "000003"
        assert out[1]["code"] == "000001"
        assert out[2]["code"] == "000002"
        # total_score 透传（保留作字段，非排序键）
        assert out[0]["total_score"] == 55.0


class TestSelectForEntryS098:
    """S098 §44 合规：select 按确认时间序（timestamp 升序，先确认先买），不按 total auto-rank。"""

    def test_select_by_confirm_timestamp(self, monkeypatch):
        """S098：按 timestamp 升序取前 N，不按 total 降序。"""
        from strategies.first_board_position import select_for_entry
        # total 降序（A>B>C）但 timestamp 乱序（B 先确认，C 最后）
        cands = [
            {"code": "000001", "name": "A", "total": 65.0, "timestamp": "2026-08-26 09:32:00"},
            {"code": "000002", "name": "B", "total": 60.0, "timestamp": "2026-08-26 09:31:00"},
            {"code": "000003", "name": "C", "total": 55.0, "timestamp": "2026-08-26 09:33:00"},
        ]
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        out = select_for_entry(cands, "green")
        # 按 timestamp 升序：B(09:31) → A(09:32) → C(09:33)，非 total 降序(A→B→C)
        assert [s["code"] for s in out] == ["000002", "000001", "000003"]
        assert [s["entry_rank"] for s in out] == [1, 2, 3]
        # total 保留作字段（非排序键）：B 排第1 但 total=60（非最高）
        assert out[0]["total_score"] == 60.0

    def test_select_not_by_total_auto_rank(self, monkeypatch):
        """S098 §44：不按 total auto-top-N；timestamp 最晚的即便 total 高也被剔。"""
        from strategies.first_board_position import select_for_entry
        # 6 只 total 降序，timestamp 递增（高分先确认，低分后确认——但 max 5 剔第6）
        cands = [
            {"code": f"00000{i+1}", "name": f"T{i+1}", "total": 70 - i * 5,
             "timestamp": f"2026-08-26 09:3{i}:00"}
            for i in range(6)
        ]
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        out = select_for_entry(cands, "green")  # 绿灯 max 5
        assert len(out) == 5
        # 按 timestamp 升序前 5：000001-000005（000006 timestamp 最晚，被剔）
        assert "000006" not in [s["code"] for s in out]
        assert [s["entry_rank"] for s in out] == [1, 2, 3, 4, 5]

    def test_stop_loss_take_profit_lines(self, monkeypatch):
        """止盈止损线计算：stop=-3% tp=+5%。"""
        from strategies.first_board_position import select_for_entry
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        out = select_for_entry(cands, "green")
        assert len(out) == 1
        s = out[0]
        assert s["entry_price"] == 10.0
        assert s["stop_loss"] == round(10.0 * 0.97, 2)   # 9.70
        assert s["take_profit"] == round(10.0 * 1.05, 2)  # 10.50

    def test_entry_price_missing(self, monkeypatch):
        """tencent_quote 取不到开盘价 → entry_price=None，止盈止损线=None。"""
        from strategies.first_board_position import select_for_entry
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: {}  # 空返回
        )
        out = select_for_entry(cands, "green")
        assert len(out) == 1
        assert out[0]["entry_price"] is None
        assert out[0]["stop_loss"] is None
        assert out[0]["take_profit"] is None

    def test_tencent_quote_exception_no_crash(self, monkeypatch):
        """tencent_quote 抛异常 → 不崩，entry_price=None。"""
        from strategies.first_board_position import select_for_entry
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        def boom(codes):
            raise ConnectionError("网络故障")
        monkeypatch.setattr("strategies.first_board_position.tencent_quote", boom)
        out = select_for_entry(cands, "green")
        assert len(out) == 1
        assert out[0]["entry_price"] is None


class TestExecuteEntry:
    """051：测试建仓记录。"""

    def test_execute_entry_adds_time_and_price(self):
        """execute_entry 加 entry_time + entry_price_actual。"""
        from strategies.first_board_position import execute_entry
        selected = [{"code": "000001", "name": "A", "entry_price": 10.0,
                     "stop_loss": 9.70, "take_profit": 10.50}]
        out = execute_entry(selected)
        assert len(out) == 1
        assert "entry_time" in out[0]
        assert out[0]["entry_price_actual"] == 10.0  # 用 selected 的 entry_price

    def test_execute_entry_with_explicit_price(self):
        """传入 entry_price 覆盖所有候选的实际建仓价。"""
        from strategies.first_board_position import execute_entry
        selected = [
            {"code": "000001", "name": "A", "entry_price": 10.0},
            {"code": "000002", "name": "B", "entry_price": 5.0},
        ]
        out = execute_entry(selected, entry_price=8.8)  # 人工确认价
        assert all(e["entry_price_actual"] == 8.8 for e in out)


# =========================================================================
# 052 止盈止损
# =========================================================================

class TestCheckExitSignals:
    """052：测试止盈止损判定。"""

    def test_take_profit_triggered(self):
        """盘中冲高>5%止盈（current_price >= take_profit 线）。"""
        from strategies.first_board_position import check_exit_signals
        holding = {"code": "000001", "entry_price_actual": 10.0,
                   "stop_loss": 9.70, "take_profit": 10.50}
        r = check_exit_signals(holding, 10.50)  # 恰好触及
        assert r["action"] == "take_profit"
        assert r["exit_price"] == 10.50
        assert "止盈" in r["reason"]
        assert "5" in r["reason"]

    def test_take_profit_above_line(self):
        """超过止盈线也触发。"""
        from strategies.first_board_position import check_exit_signals
        holding = {"code": "000001", "entry_price_actual": 10.0,
                   "stop_loss": 9.70, "take_profit": 10.50}
        r = check_exit_signals(holding, 10.80)
        assert r["action"] == "take_profit"

    def test_stop_loss_triggered(self):
        """跌破-3%止损（current_price <= stop_loss 线）。"""
        from strategies.first_board_position import check_exit_signals
        holding = {"code": "000001", "entry_price_actual": 10.0,
                   "stop_loss": 9.70, "take_profit": 10.50}
        r = check_exit_signals(holding, 9.70)  # 恰好触及
        assert r["action"] == "stop_loss"
        assert r["exit_price"] == 9.70
        assert "止损" in r["reason"]

    def test_stop_loss_below_line(self):
        """低于止损线也触发。"""
        from strategies.first_board_position import check_exit_signals
        holding = {"code": "000001", "entry_price_actual": 10.0,
                   "stop_loss": 9.70, "take_profit": 10.50}
        r = check_exit_signals(holding, 9.50)
        assert r["action"] == "stop_loss"

    def test_hold_within_range(self):
        """未触及止盈止损线 → hold，持有至 T+1 9:25/9:30 默认卖。"""
        from strategies.first_board_position import check_exit_signals
        holding = {"code": "000001", "entry_price_actual": 10.0,
                   "stop_loss": 9.70, "take_profit": 10.50}
        r = check_exit_signals(holding, 10.20)  # 在 9.70-10.50 之间
        assert r["action"] == "hold"
        assert "默认卖" in r["reason"]

    def test_default_sell_at_925(self):
        """默认 9:25 竞价/9:30 开盘卖——由调用方触发，check_exit_signals 返 hold。

        spec 2.5：default_sell 由调用方在 9:25/9:30 触发（不在 check_exit_signals 内）。
        未触及止盈止损线时返 hold，调用方在 9:25 调 execute_exit(action="default_sell")。
        """
        from strategies.first_board_position import check_exit_signals
        holding = {"code": "000001", "entry_price_actual": 10.0,
                   "stop_loss": 9.70, "take_profit": 10.50}
        r = check_exit_signals(holding, 10.10)  # 未触及线
        assert r["action"] == "hold"  # 不是 default_sell（default_sell 由调用方判定）

    def test_data_missing_degraded(self):
        """entry_price_actual 缺失 → 降级 default_sell（无法判定止盈止损线）。"""
        from strategies.first_board_position import check_exit_signals
        holding = {"code": "000001", "entry_price_actual": None,
                   "stop_loss": None, "take_profit": None}
        r = check_exit_signals(holding, 10.0)
        assert r["action"] == "default_sell"
        assert "数据缺失" in r["reason"]

    def test_current_price_missing_degraded(self):
        """current_price 缺失（None）→ 降级 default_sell。"""
        from strategies.first_board_position import check_exit_signals
        holding = {"code": "000001", "entry_price_actual": 10.0,
                   "stop_loss": 9.70, "take_profit": 10.50}
        r = check_exit_signals(holding, None)
        assert r["action"] == "default_sell"
        assert "数据缺失" in r["reason"]


class TestExecuteExit:
    """052：测试卖出记录。"""

    def test_return_pct_calculation(self):
        """return_pct = (exit - entry) / entry * 100。"""
        from strategies.first_board_position import execute_exit
        holding = {"code": "000001", "name": "A", "entry_price_actual": 10.0}
        r = execute_exit(holding, 10.50, "take_profit")
        assert r["return_pct"] == 5.0  # (10.50-10.0)/10.0*100
        assert r["action"] == "take_profit"
        assert r["hold_days"] == 1
        assert "exit_time" in r

    def test_stop_loss_return_negative(self):
        """止损 return_pct 为负。"""
        from strategies.first_board_position import execute_exit
        holding = {"code": "000001", "name": "A", "entry_price_actual": 10.0}
        r = execute_exit(holding, 9.70, "stop_loss")
        assert r["return_pct"] == -3.0
        assert r["action"] == "stop_loss"

    def test_entry_missing_return_none(self):
        """entry_price 缺失 → return_pct=None。"""
        from strategies.first_board_position import execute_exit
        holding = {"code": "000001", "name": "A", "entry_price_actual": None}
        r = execute_exit(holding, 10.0, "default_sell")
        assert r["return_pct"] is None


# =========================================================================
# 052 端到端 + 通知
# =========================================================================

class TestRunFirstBoardPosition:
    """052：测试主入口端到端。"""

    def test_end_to_end_structure(self, monkeypatch):
        """端到端：mock candidates+judge+prices，验证返回结构完整。"""
        from strategies.first_board_position import run_first_board_position
        _mock_notification_service(monkeypatch, available=False)  # 不触发通知
        confirmed = _make_open_confirmed(3, base_score=65.0)
        judge = {"light": "green", "position_advice": "绿灯"}
        prices = {"000001": 10.0, "000002": 5.0, "000003": 8.0}
        r = run_first_board_position(confirmed, judge, prices)

        # 结构完整
        assert set(r.keys()) == {"selected", "entered", "notified", "holdings"}
        assert len(r["selected"]) == 3
        assert len(r["entered"]) == 3
        assert len(r["holdings"]) == 3
        # entered = holdings（同一对象）
        assert r["holdings"] == r["entered"]
        # entry_prices 预填覆盖
        s0 = r["selected"][0]
        assert s0["entry_price"] == 10.0
        assert s0["stop_loss"] == 9.70
        assert s0["take_profit"] == 10.50
        # entered 含 entry_time + entry_price_actual
        e0 = r["entered"][0]
        assert "entry_time" in e0
        assert e0["entry_price_actual"] == 10.0

    def test_red_light_zero_position(self, monkeypatch):
        """红灯 → 0 选股 0 建仓。"""
        from strategies.first_board_position import run_first_board_position
        _mock_notification_service(monkeypatch, available=False)
        confirmed = _make_open_confirmed(5, base_score=65.0)
        judge = {"light": "red", "position_advice": "暴风雨0仓位"}
        r = run_first_board_position(confirmed, judge, None)
        assert len(r["selected"]) == 0
        assert len(r["entered"]) == 0
        assert len(r["holdings"]) == 0

    def test_notify_entry_ready_threshold(self, monkeypatch):
        """候选≥3 只才推送建仓通知。"""
        from strategies.first_board_position import run_first_board_position
        mock_ns = _mock_notification_service(monkeypatch, available=True, send_ok=True)
        # 3 只 → 推送
        confirmed = _make_open_confirmed(3, base_score=65.0)
        judge = {"light": "green", "position_advice": "绿灯"}
        prices = {"000001": 10.0, "000002": 5.0, "000003": 8.0}
        r = run_first_board_position(confirmed, judge, prices)
        assert r["notified"] is True
        mock_ns.send.assert_called_once()
        content = mock_ns.send.call_args[0][0]  # 第一个位置参数
        assert "建仓" in content or "首板流" in content

    def test_notify_entry_below_threshold_no_push(self, monkeypatch):
        """候选<3 只不推送。"""
        from strategies.first_board_position import run_first_board_position
        mock_ns = _mock_notification_service(monkeypatch, available=True, send_ok=True)
        confirmed = _make_open_confirmed(2, base_score=65.0)  # 只 2 只
        judge = {"light": "green", "position_advice": "绿灯"}
        prices = {"000001": 10.0, "000002": 5.0}
        r = run_first_board_position(confirmed, judge, prices)
        assert r["notified"] is False
        mock_ns.send.assert_not_called()

    def test_notify_channel_unavailable(self, monkeypatch):
        """通知渠道未配置 → notified=False，不崩。"""
        from strategies.first_board_position import run_first_board_position
        _mock_notification_service(monkeypatch, available=False, send_ok=False)
        confirmed = _make_open_confirmed(3, base_score=65.0)
        judge = {"light": "green", "position_advice": "绿灯"}
        prices = {"000001": 10.0, "000002": 5.0, "000003": 8.0}
        r = run_first_board_position(confirmed, judge, prices)
        assert r["notified"] is False  # 渠道不可用

    def test_entry_prices_none_uses_tencent(self, monkeypatch):
        """entry_prices=None → 用 tencent_quote 实时取开盘价。"""
        from strategies.first_board_position import run_first_board_position
        _mock_notification_service(monkeypatch, available=False)
        confirmed = _make_open_confirmed(2, base_score=65.0)
        judge = {"light": "green", "position_advice": "绿灯"}
        # mock tencent_quote 返 open=10.0
        monkeypatch.setattr(
            "strategies.first_board_position.tencent_quote",
            lambda codes: _make_tencent_quote(codes, open_price=10.0)
        )
        r = run_first_board_position(confirmed, judge, None)  # 不预填
        assert len(r["selected"]) == 2
        assert all(s["entry_price"] == 10.0 for s in r["selected"])
        assert all(s["stop_loss"] == 9.70 for s in r["selected"])
