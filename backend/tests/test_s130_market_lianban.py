# -*- coding: utf-8 -*-
"""S130 R2：market.py lianban_stocks or-0→None（对齐 S121 tencent 0→None 范式）。

涨停池个股清单的 price/pct/amount 三字段缺失时原本 `or 0`→0.0 当真值喂 LLM，
现 `or None`→None 让 AI 见 null 辨缺失（0 永不合法：涨停股 price/pct/amount=0 异常）。

测试钉死三条（spec §3 R2.3）：
①bar 缺 price 'p' → price is None（非 0）；
②真值不变（p=19920→19.92）；
③排序不崩（amount=None 排序兜底）。
另钉 0→None 语义（p=0 / zdp=0 → None）。
"""
from __future__ import annotations

import os
import sys

import astock
import market

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATE = "2026-08-10"  # 显式交易日，走 _emotion date-is-not-None 分支


def _patch_guards(monkeypatch):
    """bypass 交易日历/盘前守卫 + _sentiment 网络取数，让 _emotion 跑到 lianban_stocks。"""
    import vr_paths
    monkeypatch.setattr(vr_paths, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(market, "_sentiment", lambda _date=None: {})


def _emotion_with_pool(monkeypatch, zt_pool):
    """mock em_zt_topic_pool：zt 池返 zt_pool，zb/dt/yzt 返空。"""
    _patch_guards(monkeypatch)

    def fake_pool(pool_type, _date_str, _sort, raise_on_failure=False):
        if pool_type == "getTopicZTPool":
            return zt_pool
        return []

    monkeypatch.setattr(astock, "em_zt_topic_pool", fake_pool)
    return market._emotion(DATE)


def test_missing_price_field_yields_none_not_zero(monkeypatch):
    """R2.3①：bar 缺 'p' 键 → price is None（非 0，防 LLM 见 0 当真价）。"""
    zt = [{"c": "600001", "n": "缺价股", "lbc": 2, "zdp": 10.0,
           "amount": 500000.0, "ltsz": 2e9, "hybk": "医药"}]  # 无 'p' 键
    out = _emotion_with_pool(monkeypatch, zt)
    stocks = out["lianban_stocks"]
    assert len(stocks) == 1
    assert stocks[0]["price"] is None, "缺失 price 应为 None 而非 0（0→None，对齐 S121）"


def test_real_price_value_preserved(monkeypatch):
    """R2.3②：真值不变——p=19920 → price=19.92（19920/1000）。"""
    zt = [{"c": "600002", "n": "实价股", "lbc": 3, "p": 19920, "zdp": 9.98,
           "amount": 1234567.0, "ltsz": 5e9, "hybk": "半导体"}]
    out = _emotion_with_pool(monkeypatch, zt)
    stocks = out["lianban_stocks"]
    assert stocks[0]["price"] == 19.92, "真值应原样保留（19.92 or None = 19.92）"


def test_sort_with_amount_none_no_crash(monkeypatch):
    """R2.3③：amount=None 排序兜底不崩——sort key `-(x["amount"] or 0)` 守数值。"""
    zt = [
        {"c": "600003", "n": "有额股", "lbc": 2, "p": 10000, "zdp": 10.0,
         "amount": 800000.0, "ltsz": 1e9, "hybk": "电子"},
        {"c": "600004", "n": "缺额股", "lbc": 2, "p": 12000, "zdp": 10.0,
         "ltsz": 1.5e9, "hybk": "化工"},  # 无 'amount' 键 → None
    ]
    out = _emotion_with_pool(monkeypatch, zt)  # 排序不应抛 TypeError
    stocks = out["lianban_stocks"]
    assert len(stocks) == 2, "两只 2 板股都应进 lianban_stocks"
    # 缺额股 amount=None，不应崩
    none_amt = [s for s in stocks if s["amount"] is None]
    assert len(none_amt) == 1, "缺额股 amount 应为 None（非 0）"


def test_zero_price_becomes_none(monkeypatch):
    """0→None 语义：p=0（涨停股 price=0 异常）→ price=None。"""
    zt = [{"c": "600005", "n": "零价股", "lbc": 2, "p": 0, "zdp": 10.0,
           "amount": 300000.0, "ltsz": 8e8, "hybk": "纺织"}]
    out = _emotion_with_pool(monkeypatch, zt)
    assert out["lianban_stocks"][0]["price"] is None, "p=0 falsy→None（0 永不合法）"


def test_zero_pct_becomes_none(monkeypatch):
    """0→None 语义：zdp=0.0（涨停股 pct=0 异常）→ pct=None。"""
    zt = [{"c": "600006", "n": "零幅股", "lbc": 2, "p": 15000, "zdp": 0.0,
           "amount": 400000.0, "ltsz": 9e8, "hybk": "机械"}]
    out = _emotion_with_pool(monkeypatch, zt)
    assert out["lianban_stocks"][0]["pct"] is None, "zdp=0.0 falsy→None（涨停股 pct=0 异常）"


def test_real_pct_preserved_including_negative(monkeypatch):
    """真值不变：zdp=9.98→pct=9.98；负 pct=-3.5 也保留（truthy）。"""
    zt = [
        {"c": "600007", "n": "涨股", "lbc": 2, "p": 11000, "zdp": 9.98,
         "amount": 500000.0, "ltsz": 1e9, "hybk": "有色"},
        {"c": "600008", "n": "跌股", "lbc": 2, "p": 9000, "zdp": -3.5,
         "amount": 500000.0, "ltsz": 1e9, "hybk": "煤炭"},
    ]
    out = _emotion_with_pool(monkeypatch, zt)
    by_code = {s["code"]: s for s in out["lianban_stocks"]}
    assert by_code["600007"]["pct"] == 9.98
    assert by_code["600008"]["pct"] == -3.5, "负值 truthy 应原样保留"
