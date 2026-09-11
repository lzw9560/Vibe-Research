# -*- coding: utf-8 -*-
"""S183 胜率变化曲线——_wilson_ci n=0 + DORMANT_ARMS + query_winrate_trends 测试。

覆盖 spec R1-R6：Wilson CI 边界（n=0/1/10/100）、DORMANT_ARMS 移 trend、
query_winrate_trends 过滤（dead_arm/unbuyable/NULL/breakeven）+ 按周累积 + 双轴标签。
"""
from __future__ import annotations


# ---------- R2: _wilson_ci n=0 返 (0,1) 宽带 ----------
def test_wilson_ci_n0_returns_wide_band():
    """n=0 返 (0,1) 诚实暴露无数据（非 (0,0) 误导'精确 0%'）。"""
    from engine.trade_journal import _wilson_ci
    assert _wilson_ci(0, 0) == (0.0, 1.0)


def test_wilson_ci_known_values():
    """Wilson CI 边界值合理性（手算验证 n=10/100）。"""
    from engine.trade_journal import _wilson_ci
    # n=10, 5 wins: p̂=0.5, Wilson CI ≈ [0.236, 0.763]
    lo, hi = _wilson_ci(5, 10)
    assert 0.20 < lo < 0.30, f"n=10 lo={lo}"
    assert 0.70 < hi < 0.80, f"n=10 hi={hi}"
    # n=100, 50 wins: p̂=0.5, Wilson CI ≈ [0.404, 0.596]
    lo, hi = _wilson_ci(50, 100)
    assert 0.39 < lo < 0.41, f"n=100 lo={lo}"
    assert 0.59 < hi < 0.61, f"n=100 hi={hi}"


# ---------- R5: DORMANT_ARMS 移 trend + ARM_VERDICT 更新 ----------
def test_dormant_arms_no_trend():
    """S181 已升级 trend 为实臂，DORMANT_ARMS 不含 trend + ARM_VERDICT trend=exploratory。"""
    from engine.trade_journal import DORMANT_ARMS, ARM_VERDICT
    assert "trend" not in DORMANT_ARMS, f"trend 仍在 DORMANT_ARMS: {DORMANT_ARMS}"
    assert ARM_VERDICT["trend"] == "exploratory"


# ---------- R1: query_winrate_trends 空表 + 过滤 + 累积 ----------
def test_query_winrate_trends_empty(tmp_path):
    """空表返 [] 非 None。"""
    from engine.trade_journal import TradeJournal
    tj = TradeJournal(db_path=tmp_path / "empty.db")
    assert tj.query_winrate_trends() == []


def test_query_winrate_trends_filters_dead_unbuyable_null_breakeven(tmp_path):
    """mock 7 records（3 有效 2win1loss + 4 排除）验证：
    is_dead_arm=1 / unbuyable / net_pnl=None / net_pnl=0 全不进分母。"""
    from engine.trade_journal import TradeJournal, JournalRecord
    tj = TradeJournal(db_path=tmp_path / "filter.db")
    recs = [
        # 3 有效（2 win 1 loss）
        JournalRecord(signal_id="w1", arm="breakout", stock_code="001", entry_price=10.0,
                      entry_date="2026-09-09", exit_date="2026-09-10", net_pnl=10.0,
                      exit_reason="max_hold", is_realized=1),
        JournalRecord(signal_id="w2", arm="breakout", stock_code="002", entry_price=10.0,
                      entry_date="2026-09-09", exit_date="2026-09-10", net_pnl=5.0,
                      exit_reason="take_profit", is_realized=1),
        JournalRecord(signal_id="l1", arm="breakout", stock_code="003", entry_price=10.0,
                      entry_date="2026-09-09", exit_date="2026-09-10", net_pnl=-3.0,
                      exit_reason="stop", is_realized=1),
        # 排除：dead_arm（gap 证否臂）
        JournalRecord(signal_id="d1", arm="gap", stock_code="004", entry_price=10.0,
                      entry_date="2026-09-09", exit_date="2026-09-10", net_pnl=100.0,
                      is_realized=1, is_dead_arm=1),
        # 排除：unbuyable
        JournalRecord(signal_id="u1", arm="breakout", stock_code="005", entry_price=10.0,
                      entry_date="2026-09-09", exit_date="2026-09-10", net_pnl=0.0,
                      exit_reason="unbuyable", is_realized=1),
        # 排除：net_pnl=None
        JournalRecord(signal_id="n1", arm="breakout", stock_code="006", entry_price=10.0,
                      entry_date="2026-09-09", exit_date="2026-09-10", net_pnl=None,
                      is_realized=1),
        # 排除：breakeven net_pnl=0（非 unbuyable）
        JournalRecord(signal_id="b1", arm="breakout", stock_code="007", entry_price=10.0,
                      entry_date="2026-09-09", exit_date="2026-09-10", net_pnl=0.0,
                      exit_reason="max_hold", is_realized=1),
    ]
    for r in recs:
        tj.insert(r)
    trends = tj.query_winrate_trends()
    assert len(trends) == 1, f"应 1 周（全 09-10 同周），实际 {len(trends)}"
    t = trends[0]
    assert t["n_decided"] == 3, f"n_decided 应 3（2win1loss），实际 {t['n_decided']}"
    assert abs(t["win_rate"] - 2 / 3) < 0.01, f"win_rate 应 0.667，实际 {t['win_rate']}"
    assert t["label"] == "insufficient_sample", f"n=3<30 应 insufficient，实际 {t['label']}"
    assert t["ci_low"] < t["win_rate"] < t["ci_high"], "win_rate 应在 CI 内"


def test_query_winrate_trends_cumulative_by_week(tmp_path):
    """跨 2 周累积：第 1 周 1win→1.0，第 2 周 +1win+1loss→2/3=0.667。"""
    from engine.trade_journal import TradeJournal, JournalRecord
    tj = TradeJournal(db_path=tmp_path / "cum.db")
    # week 1 (09-07 周, exit 09-08 周二)
    tj.insert(JournalRecord(signal_id="w1", arm="breakout", stock_code="001",
                            entry_price=10.0, entry_date="2026-09-07",
                            exit_date="2026-09-08", net_pnl=10.0,
                            exit_reason="max_hold", is_realized=1))
    # week 2 (09-14 周, exit 09-15 周二)
    tj.insert(JournalRecord(signal_id="w2", arm="breakout", stock_code="002",
                            entry_price=10.0, entry_date="2026-09-14",
                            exit_date="2026-09-15", net_pnl=5.0,
                            exit_reason="take_profit", is_realized=1))
    tj.insert(JournalRecord(signal_id="l1", arm="breakout", stock_code="003",
                            entry_price=10.0, entry_date="2026-09-14",
                            exit_date="2026-09-15", net_pnl=-3.0,
                            exit_reason="stop", is_realized=1))
    trends = tj.query_winrate_trends()
    assert len(trends) == 2, f"应 2 周，实际 {len(trends)}"
    # week 1: 1 win / 1 = 1.0
    assert abs(trends[0]["win_rate"] - 1.0) < 0.01
    assert trends[0]["n_decided"] == 1
    # week 2 累积: 2 win / 3 = 0.667
    assert abs(trends[1]["win_rate"] - 2 / 3) < 0.01
    assert trends[1]["n_decided"] == 3
    assert trends[1]["n_days"] == 2, f"2 个唯一 exit_date，实际 {trends[1]['n_days']}"


def test_query_winrate_trends_label_thresholds(tmp_path):
    """双轴标签边界：n<30 insufficient / n≥30 且 n_days<60 underpowered / n≥30 且 n_days≥60 robust。

    用 30 条同日（n_days=1）→ n≥30 但 n_days<60 → underpowered。
    """
    from engine.trade_journal import TradeJournal, JournalRecord
    tj = TradeJournal(db_path=tmp_path / "label.db")
    # 30 条同 exit_date → n=30, n_days=1 → underpowered（n≥30 但 days<60）
    for i in range(30):
        tj.insert(JournalRecord(signal_id=f"s{i}", arm="breakout", stock_code="001",
                                entry_price=10.0, entry_date="2026-09-09",
                                exit_date="2026-09-10", net_pnl=1.0,
                                exit_reason="max_hold", is_realized=1))
    trends = tj.query_winrate_trends()
    assert len(trends) == 1
    assert trends[0]["n_decided"] == 30
    assert trends[0]["label"] == "underpowered", f"n=30 n_days=1 应 underpowered，实际 {trends[0]['label']}"
