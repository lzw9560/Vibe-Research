# -*- coding: utf-8 -*-
"""S162 反前视引擎三层测试——Decision + Accounting design-agnostic + Executor pluggable fill。

覆盖验收标准：
  R1a Trades dataclass（signal_date+fill_type，entry_price Executor 填）
  R1b generate_trade_decision stub（TODO 待 qlib 源码核实）
  R1  Accounting design-agnostic（path_return+cost+survivorship，不含 day_paired/IC）
  R1  Executor pluggable fill（FillPolicy 接口，T+1OpenFill offset≥1，IntradayConditionalFill stub）
  R2  反前视架构级（FillPolicy offset≥1 batch enforcement）
  R3  A 股成交规则（T+1 + 涨跌停闸门 + 停牌，Executor 层）
  R5  gap bypasses engine（IntradayConditionalFill stub 返 untradeable）
  simulate_holding 拆分重构 + T+1 guard (idx+2>=len) 保 + backward compat
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from engine.decision import (  # noqa: E402
    DEFAULT_LOT_SIZE,
    FILL_ACCEPTED,
    FILL_INTRADAY_CONDITIONAL,
    FILL_PENDING,
    FILL_T_PLUS_1_OPEN,
    FILL_UNTRADEABLE,
    Trades,
    generate_trade_decision,
)
from engine.fill_policies import (  # noqa: E402
    FillPolicy,
    IntradayConditionalFill,
    T1OpenFill,
)
from engine.executor import Executor, fillability_check  # noqa: E402
from engine.accounting import (  # noqa: E402
    COMMISSION_MIN_YUAN,
    ROUND_TRIP_COST_PCT,
    STAMP_DUTY_PCT,
    PathReturn,
    _cost_pct,
    path_return,
    path_return_as_dict,
)
from engine.bar_utils import (  # noqa: E402
    _limit_pct_for_code,
    is_halted,
    is_unbuyable_next_bar,
)

SIGNAL = "2026-08-01"


def _bar(date, o, h, l, c, **kw):
    """SimpleNamespace bar（strategy_backtest 风格）。"""
    return SimpleNamespace(date=date, open=o, high=h, low=l, close=c, **kw)


def _dbar(date, o, h, l, c, **kw):
    """dict bar（kline_returns/baostock 风格，带 pctChg/volume）。"""
    d = {"date": date, "open": o, "high": h, "low": l, "close": c}
    d.update(kw)
    return d


def _make_trades(code="", fill_type=FILL_T_PLUS_1_OPEN):
    return Trades(
        code=code, signal_date=SIGNAL, fill_type=fill_type,
        direction="long", size=DEFAULT_LOT_SIZE,
    )


# ===========================================================================
# R1a 三层解耦：Decision → Executor → Accounting 各司其职
# ===========================================================================

class TestThreeLayerDecoupling:
    def test_decision_produces_trades_without_entry_price(self):
        """R1a：Decision 产 Trades，entry_price=None（Executor 填，Decision 不带价）。"""
        t = _make_trades(code="000001")
        assert t.entry_price is None
        assert t.fill_status == FILL_PENDING
        assert not t.is_accepted()

    def test_executor_fills_entry_price_only(self):
        """R1a：Executor 填 entry_price（FillPolicy 唯一源），不算 return。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        t = _make_trades()
        filled = Executor().execute(t, bars, T1OpenFill())
        assert filled.entry_price == 10.5  # bars[idx+1].open
        assert filled.is_accepted()
        assert filled.fill_status == FILL_ACCEPTED

    def test_accounting_computes_return_from_filled_trades(self):
        """R1：Accounting 算 return，entry_price 来自 Trades（非 bars 重读）。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),  # take
        ]
        t = _make_trades()
        filled = Executor().execute(t, bars, T1OpenFill())
        pr = path_return(filled, bars, stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=3)
        assert pr is not None
        assert pr.exit_reason == "take"
        assert pr.gross_return_pct == 8.0
        # entry_price 由 Executor 填，Accounting 不重读 bars[idx+1].open
        assert filled.entry_price == 10.5

    def test_refused_fills_have_no_return(self):
        """R1：Accounting 只对 ACCEPTED 的 fills 算 return；refused → None。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        # pending（未 fill）→ None
        t_pending = _make_trades()
        assert path_return(t_pending, bars, -3.0, 8.0, 3) is None
        # untradeable → None
        t_refused = t_pending.with_fill(None, FILL_UNTRADEABLE, "test")
        assert path_return(t_refused, bars, -3.0, 8.0, 3) is None


# ===========================================================================
# R1b generate_trade_decision stub
# ===========================================================================

def test_r1b_generate_trade_decision_stub_raises():
    """R1b：generate_trade_decision stub——TODO 待 qlib gh-proxy 源码核实，不臆造签名。"""
    with pytest.raises(NotImplementedError, match="qlib"):
        generate_trade_decision()


# ===========================================================================
# R2 反前视架构级：FillPolicy offset≥1
# ===========================================================================

class TestAntiLookahead:
    def test_t1_open_fill_uses_next_bar_open_not_signal_close(self):
        """R2：entry=bars[signal_idx+1].open（T+1），非 bars[signal_idx].close（T，look-ahead）。

        signal day close=100（如用 close=look-ahead），T+1 open=10.5 → entry=10.5。
        offset≥1 反前视架构级强约束（治 §44v1 错窗口根因）。
        """
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 100.0),  # signal close=100（look-ahead 陷阱）
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),  # T+1 open=10.5（entry 应取此）
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        result = T1OpenFill().fill(SIGNAL, bars)
        assert result.status == FILL_ACCEPTED
        assert result.entry_price == 10.5  # T+1 open，非 signal close=100
        assert result.fill_bar_idx == 1  # idx+1=1，offset≥1

    def test_t1_open_fill_refuses_when_no_next_bar(self):
        """R2：缺 T+1 bar（signal 是最后 bar）→ untradeable（offset≥1 不可满足）。"""
        bars = [_bar(SIGNAL, 10.0, 10.5, 9.5, 10.0)]
        result = T1OpenFill().fill(SIGNAL, bars)
        assert result.status == FILL_UNTRADEABLE
        assert result.entry_price is None

    def test_t1_open_fill_refuses_invalid_entry_price(self):
        """R2：T+1 open<=0 → untradeable（无意义入场价）。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 0.0, 0.0, 0.0, 0.0),  # open=0
        ]
        result = T1OpenFill().fill(SIGNAL, bars)
        assert result.status == FILL_UNTRADEABLE

    def test_fill_policy_protocol_structural_typing(self):
        """R1：FillPolicy 是 Protocol——T1OpenFill/IntradayConditionalFill 满足。"""
        assert isinstance(T1OpenFill(), FillPolicy)
        assert isinstance(IntradayConditionalFill(), FillPolicy)


# ===========================================================================
# R3 A 股成交规则：T+1 + 涨跌停闸门 + 停牌
# ===========================================================================

class TestAShareRules:
    def test_t1_buy_day_cannot_sell(self):
        """R3：A 股 T+1 买入日不可卖——T+1 触止损也跳过（T+2 起检查）。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.0, 10.2),  # T+1 low=10<10.185（触止损但跳过）
            _bar("2026-08-03", 10.3, 10.8, 10.2, 10.5),
            _bar("2026-08-04", 10.5, 10.6, 10.3, 10.4),  # T+3 max_hold exit
        ]
        filled = Executor().execute(_make_trades(), bars, T1OpenFill())
        pr = path_return(filled, bars, -3.0, 8.0, 3, apply_cost=False)
        assert pr is not None
        assert pr.exit_reason == "max_hold"  # T+1 止损跳过
        assert pr.won is False
        assert pr.return_pct == pytest.approx(-0.95, abs=0.05)

    def test_limit_up_locked_unbuyable(self):
        """R3：一字板涨停封死（四价相等+pctChg≥9.8%）→ Executor 拒绝。"""
        bars = [
            _dbar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _dbar("2026-08-02", 11.0, 11.0, 11.0, 11.0, pctChg=10.0),  # 一字涨停
            _dbar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        filled = Executor().execute(_make_trades(code="000001"), bars, T1OpenFill())
        assert not filled.is_accepted()
        assert filled.fill_status == FILL_UNTRADEABLE
        assert filled.entry_price is None
        assert "limit_up_locked" in filled.fill_reason
        assert path_return(filled, bars, -3.0, 8.0, 3) is None

    def test_halted_stock_untradeable(self):
        """R3：停牌（volume==0）→ Executor 拒绝。无 volume 字段不误判。"""
        bars_halted = [
            _dbar(SIGNAL, 10.0, 10.5, 9.5, 10.0, volume=1000),
            _dbar("2026-08-02", 10.5, 10.6, 10.5, 11.0, volume=0),  # 停牌
            _dbar("2026-08-03", 11.0, 12.0, 10.5, 11.5, volume=1000),
        ]
        filled = Executor().execute(_make_trades(), bars_halted, T1OpenFill())
        assert not filled.is_accepted()
        assert "halted" in filled.fill_reason

    def test_no_volume_field_not_misjudged_as_halted(self):
        """R3：bar 无 volume 字段（test bar 风格）→ 不误判停牌（backward compat）。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        filled = Executor().execute(_make_trades(), bars, T1OpenFill())
        assert filled.is_accepted()

    def test_down_limit_one_word_is_buyable_for_long(self):
        """R3：跌停一字板对做多可买（有人抛、买家成交）——is_unbuyable 只测涨停方向。"""
        down_bar = _dbar("d", 9.0, 9.0, 9.0, 9.0, pctChg=-10.0)
        assert is_unbuyable_next_bar(down_bar, code="000001") is False


# ===========================================================================
# Board-aware 涨跌停阈值
# ===========================================================================

class TestBoardAwareLimits:
    def test_limit_pct_for_code(self):
        """板块涨跌停幅度：主板 10% / 创业板 20% / 科创板 20% / 北交 30%。"""
        assert _limit_pct_for_code("000001") == 10.0
        assert _limit_pct_for_code("300001") == 20.0  # 创业板
        assert _limit_pct_for_code("688001") == 20.0  # 科创板
        assert _limit_pct_for_code("830001") == 30.0  # 北交所

    def test_unbuyable_thresholds_by_board(self):
        """board-aware 一字板阈值：主板 9.8% / 创业板 19.8% / ST 4.8%。"""
        def one_word(pct):
            """一字板 bar（四价相等 + pctChg=pct）。"""
            return _dbar("d", 11, 11, 11, 11, pctChg=pct)
        # 主板 10% → threshold 9.8%
        assert is_unbuyable_next_bar(one_word(10.0), code="000001") is True
        assert is_unbuyable_next_bar(one_word(9.5), code="000001") is False
        # 创业板 20% → threshold 19.8%
        assert is_unbuyable_next_bar(one_word(20.0), code="300001") is True
        assert is_unbuyable_next_bar(one_word(15.0), code="300001") is False  # 15<19.8
        # ST 5% → threshold 4.8%
        st_bar = _dbar("d", 5.25, 5.25, 5.25, 5.25, pctChg=5.0, isST=1)
        assert is_unbuyable_next_bar(st_bar, code="000001") is True

    def test_kline_returns_delegate_matches_engine(self):
        """kline_returns._is_unbuyable_next_bar 薄委托 engine（code="" → 9.8% 主板）。"""
        from strategies.kline_returns import _is_unbuyable_next_bar
        ub = _dbar("d", 11, 11, 11, 11, pctChg=10.0)
        assert _is_unbuyable_next_bar(ub) is True
        ok = _dbar("d", 10, 11, 9, 10.5, pctChg=5.0)
        assert _is_unbuyable_next_bar(ok) is False


# ===========================================================================
# R5 gap bypasses engine（IntradayConditionalFill stub）
# ===========================================================================

def test_gap_bypass_intraday_conditional_stub():
    """R5：IntradayConditionalFill stub 主动返 untradeable（活哨兵非死代码）。

    gap §44v2 run 绕过 engine 直接算 D close→D+1 open——不经此 fill。
    engine 拒绝对未建模 fill 的隔夜捕获（诚实显示不可交易）。
    """
    bars = [
        _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
        _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
        _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
    ]
    # FillPolicy 层
    result = IntradayConditionalFill().fill(SIGNAL, bars)
    assert result.status == FILL_UNTRADEABLE
    assert result.entry_price is None
    assert "not_implemented" in result.reason

    # Executor 层 → Trades untradeable → Accounting 无 return
    t = Trades(
        code="000001", signal_date=SIGNAL, fill_type=FILL_INTRADAY_CONDITIONAL,
        direction="long", size=DEFAULT_LOT_SIZE,
    )
    filled = Executor().execute(t, bars, IntradayConditionalFill())
    assert not filled.is_accepted()
    assert path_return(filled, bars, -3.0, 8.0, 3) is None


# ===========================================================================
# simulate_holding 拆分重构 + T+1 guard 保 + backward compat
# ===========================================================================

class TestSimulateHoldingSplit:
    def test_t1_guard_idx_plus_2_preserved(self):
        """simulate_holding 拆分后 T+1 guard（idx+2>=len→None）保。缺 T+2 → None。"""
        from strategies.kline_returns import simulate_holding
        bars_short = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 11.0, 10.3, 10.8),  # 只有 T+1
        ]
        assert simulate_holding(bars_short, SIGNAL, -3.0, 8.0, 1) is None

    def test_backward_compat_take_profit(self):
        """simulate_holding 委托 engine 后 apply_cost=False——take profit 精确匹配。"""
        from strategies.kline_returns import simulate_holding
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        res = simulate_holding(bars, SIGNAL, -3.0, 8.0, 3)
        assert res is not None
        assert res["won"] is True
        assert res["return_pct"] == 8.0
        assert res["exit_reason"] == "take"
        assert res["exit_date"] == "2026-08-03"
        assert res["cost_pct"] == 0.0  # backward compat: no cost

    def test_backward_compat_stop_loss(self):
        """simulate_holding 委托 engine 后 stop loss 精确匹配。"""
        from strategies.kline_returns import simulate_holding
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 10.3, 10.4, 9.5, 9.6),  # T+2 low=9.5 触止损
        ]
        res = simulate_holding(bars, SIGNAL, -3.0, 8.0, 3)
        assert res is not None
        assert res["won"] is False
        assert res["return_pct"] == -3.0
        assert res["exit_reason"] == "stop"

    def test_backward_compat_max_hold(self):
        """simulate_holding 委托 engine 后 max_hold exit 精确匹配。"""
        from strategies.kline_returns import simulate_holding
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 10.8),
            _bar("2026-08-03", 10.8, 11.0, 10.6, 10.9),
            _bar("2026-08-04", 10.9, 11.0, 10.7, 11.0),  # T+3 exit close=11.0
        ]
        res = simulate_holding(bars, SIGNAL, -3.0, 8.0, 3)
        assert res is not None
        assert res["exit_reason"] == "max_hold"
        assert res["won"] is True
        assert res["return_pct"] == pytest.approx(4.76, abs=0.05)

    def test_backward_compat_empty_bars(self):
        """simulate_holding 空 bars → None。"""
        from strategies.kline_returns import simulate_holding
        assert simulate_holding([], SIGNAL, -3.0, 8.0, 3) is None

    def test_simulate_holding_with_confirm_still_works(self):
        """simulate_holding_with_confirm 调 simulate_holding（已委托 engine）→ 仍正常。"""
        from strategies.kline_returns import simulate_holding_with_confirm
        bars = [
            _bar("2026-07-31", 9.0, 9.5, 8.5, 9.0),
            _bar(SIGNAL, 10.0, 10.6, 9.5, 10.0),  # D+1 high=10.6>10.0 确认突破
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),  # D+3 take
        ]
        res = simulate_holding_with_confirm(bars, SIGNAL, 10.0, -3.0, 8.0, 3)
        assert res is not None
        assert res["exit_reason"] == "take"


# ===========================================================================
# Accounting cost 模型 + survivorship defense-in-depth
# ===========================================================================

class TestAccountingCostAndSurvivorship:
    def test_cost_model_computation(self):
        """cost = 0.70% round-trip + 0.10% 印花 + 佣金(5元×2/notional×100)。"""
        # entry=10.5, size=100 → notional=1050
        cost = _cost_pct(10.5, 100)
        expected_commission = (COMMISSION_MIN_YUAN * 2 / 1050) * 100  # ~0.952%
        expected_cost = ROUND_TRIP_COST_PCT + STAMP_DUTY_PCT + expected_commission
        assert cost == pytest.approx(expected_cost, abs=0.01)

    def test_cost_applied_to_return(self):
        """apply_cost=True：take 8.0% → net = 8.0 - cost ≈ 6.25%。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        filled = Executor().execute(_make_trades(), bars, T1OpenFill())
        pr_net = path_return(filled, bars, -3.0, 8.0, 3, apply_cost=True)
        assert pr_net is not None
        assert pr_net.gross_return_pct == 8.0
        assert pr_net.cost_pct > 0
        assert pr_net.return_pct < 8.0  # net < gross
        assert pr_net.return_pct == pytest.approx(8.0 - pr_net.cost_pct, abs=0.05)

    def test_cost_not_applied_when_disabled(self):
        """apply_cost=False：return=gross（backward compat，无 cost）。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        filled = Executor().execute(_make_trades(), bars, T1OpenFill())
        pr = path_return(filled, bars, -3.0, 8.0, 3, apply_cost=False)
        assert pr is not None
        assert pr.return_pct == 8.0
        assert pr.cost_pct == 0.0

    def test_won_determined_by_exit_reason(self):
        """won 由 exit_reason 决定（stop→False, take→True），非 return_pct 符号。"""
        bars_take = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        bars_stop = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 10.3, 10.4, 9.5, 9.6),
        ]
        filled = Executor().execute(_make_trades(), bars_take, T1OpenFill())
        pr_take = path_return(filled, bars_take, -3.0, 8.0, 3, apply_cost=True)
        assert pr_take.won is True

        filled_stop = Executor().execute(_make_trades(), bars_stop, T1OpenFill())
        pr_stop = path_return(filled_stop, bars_stop, -3.0, 8.0, 3, apply_cost=True)
        assert pr_stop.won is False

    def test_survivorship_defense_in_depth(self):
        """Accounting survivorship 二次 guard：bypass Executor 的 accepted unbuyable → None。"""
        bars = [
            _dbar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _dbar("2026-08-02", 11.0, 11.0, 11.0, 11.0, pctChg=10.0),  # unbuyable T+1
            _dbar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        # 手动构造 accepted Trades（bypass Executor fillability check）
        t_bypassed = Trades(
            code="000001", signal_date=SIGNAL, fill_type=FILL_T_PLUS_1_OPEN,
            direction="long", size=DEFAULT_LOT_SIZE,
            entry_price=11.0, fill_status=FILL_ACCEPTED,
        )
        assert path_return(t_bypassed, bars, -3.0, 8.0, 3) is None

    def test_raw_return_series_feeds_verifier(self):
        """Accounting 喂 S161 verifier：raw per-trade return series（PathReturn 可序列化）。"""
        bars = [
            _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
            _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),
            _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),
        ]
        filled = Executor().execute(_make_trades(), bars, T1OpenFill())
        pr = path_return(filled, bars, -3.0, 8.0, 3, apply_cost=True)
        assert isinstance(pr, PathReturn)
        # raw per-trade series 字段全有（verifier 读 won/return_pct/cost_pct/gross）
        assert hasattr(pr, "won")
        assert hasattr(pr, "return_pct")
        assert hasattr(pr, "cost_pct")
        assert hasattr(pr, "gross_return_pct")
        assert hasattr(pr, "exit_reason")
        assert hasattr(pr, "exit_date")
