# -*- coding: utf-8 -*-
"""test_tactics_candidate_pool —— 竞价候选池生成测试（S235 T15）。AAA 结构。"""
from __future__ import annotations

from tactics.candidate_pool import generate_auction_candidates


def _stock(code, chg):
    return {"thscode": code, "price_change_ratio_pct": chg}


# ---------------------------------------------------------------------------
# 筛选 + 排序
# ---------------------------------------------------------------------------

def test_filters_above_threshold():
    # 跌 3%、5%（边界）不入；跌 6%、10% 入
    stocks = [
        _stock("600001", -3.0),
        _stock("600002", -5.0),  # 边界（< 严格，-5 不入）
        _stock("600003", -6.0),
        _stock("600004", -10.0),
    ]
    got = generate_auction_candidates(stocks)
    # 600003 + 600004 入
    assert set(got) == {"600003", "600004"}


def test_sorted_by_drop_desc():
    # 跌幅最大（最负）在前
    stocks = [
        _stock("600001", -6.0),
        _stock("600002", -10.0),
        _stock("600003", -7.0),
    ]
    got = generate_auction_candidates(stocks)
    assert got == ["600002", "600003", "600001"]  # -10, -7, -6


def test_max_n_truncation():
    # 250 只跌>5%，截 200
    stocks = [_stock(f"{600000+i}", -6.0 - i * 0.01) for i in range(250)]
    got = generate_auction_candidates(stocks, max_n=200)
    assert len(got) == 200


def test_empty_input():
    assert generate_auction_candidates([]) == []


def test_no_qualified():
    stocks = [_stock("600001", -3.0), _stock("600002", -4.9)]
    assert generate_auction_candidates(stocks) == []


# ---------------------------------------------------------------------------
# 字段容错
# ---------------------------------------------------------------------------

def test_missing_fields_skipped():
    stocks = [
        {"thscode": "600001", "price_change_ratio_pct": -6.0},  # 完整
        {"thscode": None, "price_change_ratio_pct": -10.0},     # code None
        {"price_change_ratio_pct": -8.0},                       # 缺 code
        {"thscode": "600002"},                                  # 缺 chg
        {"thscode": "600003", "price_change_ratio_pct": "abc"},  # chg 非数
    ]
    got = generate_auction_candidates(stocks)
    assert got == ["600001"]


def test_custom_threshold():
    # 自定义门槛跌 > 3%
    stocks = [_stock("600001", -3.5), _stock("600002", -6.0)]
    got = generate_auction_candidates(stocks, drop_threshold=-3.0)
    assert set(got) == {"600001", "600002"}


# ---------------------------------------------------------------------------
# 真实快照形状（来自 feishu_daily_push.get_market_snapshot_all）
# ---------------------------------------------------------------------------

def test_real_snapshot_shape():
    # 模拟 hithink-finance market snapshot 返回的 item 形状
    stocks = [
        {"thscode": "603778", "price_change_ratio_pct": -8.5, "last_price": 9.4, "turnover": 1e8},
        {"thscode": "000001", "price_change_ratio_pct": -1.2, "last_price": 12.0, "turnover": 5e8},
        {"thscode": "300750", "price_change_ratio_pct": -6.0, "last_price": 200, "turnover": 3e8},
    ]
    got = generate_auction_candidates(stocks)
    assert got == ["603778", "300750"]  # -8.5 在前，-6.0 次
