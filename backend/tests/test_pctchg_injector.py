# -*- coding: utf-8 -*-
"""S204 R14 T1b: pctChg harness 注入 test（TDD RED→GREEN）。

验证：baostock cache bar 无 pctChg → is_unbuyable_next_bar 误判一字板可买（bug）；
enrich_pctchg 注入后一字板正确判不可买。
"""
from __future__ import annotations

from engine.bar_utils import is_unbuyable_next_bar
from engine.pctchg_injector import enrich_pctchg


def test_pctchg_injection_fixes_one_line_board():
    """cache bar 无 pctChg → is_unbuyable False（bug）；enrich 后一字板 True。

    bug 复现：一字涨停板（high==low==open==close=11，前日 close 10 → +10%），
    cache 无 pctChg → _bar_get 返 0.0 < 9.8（主板 threshold）→ is_unbuyable=False（误判可买）。
    enrich 注入 pctChg=10.0 ≥ 9.8 → is_unbuyable=True（修后正确判不可买）。
    """
    prev = {"date": "2026-01-01", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 100, "amount": 1000}
    one_word_limit_up = {"date": "2026-01-02", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 100, "amount": 1100}
    # 不注入（cache 原样无 pctChg）：bug——一字板误判可买
    assert is_unbuyable_next_bar(one_word_limit_up, "600000") is False
    # 注入后：修后正确判不可买
    enriched = enrich_pctchg([prev, one_word_limit_up])
    assert enriched[1]["pctChg"] == 10.0
    assert is_unbuyable_next_bar(enriched[1], "600000") is True


def test_pctchg_reproducible():
    """注入值=(close[d]-close[d-1])/close[d-1]*100，可复算非臆造。"""
    bars = [{"close": 10.0}, {"close": 11.0}, {"close": 12.1}]
    out = enrich_pctchg(bars)
    assert out[0]["pctChg"] == 0.0  # 首日无前收
    assert abs(out[1]["pctChg"] - 10.0) < 0.01  # (11-10)/10*100
    assert abs(out[2]["pctChg"] - 10.0) < 0.01  # (12.1-11)/11*100=10.0


def test_enrich_immutable():
    """原 bars list 不被修改（返新 list，原 bar 不加键）。"""
    bars = [{"close": 10.0}, {"close": 11.0}]
    original = [dict(b) for b in bars]
    _ = enrich_pctchg(bars)
    assert bars == original
    assert "pctChg" not in bars[0]  # 原 bar 不加键


def test_pctchg_preserves_existing():
    """bar 已有 pctChg（baostock 原值）保留不覆盖——T1a refresh cache 后原值优先。"""
    bars = [{"close": 10.0}, {"close": 11.0, "pctChg": 9.9}]  # 第二 bar 有 baostock 原值
    out = enrich_pctchg(bars)
    assert out[1]["pctChg"] == 9.9  # 保留原值不覆盖


def test_pctchg_first_day_zero():
    """首日无前收 → pctChg=0.0（不臆造）。"""
    bars = [{"close": 10.0, "date": "2026-01-01"}]
    out = enrich_pctchg(bars)
    assert out[0]["pctChg"] == 0.0


def test_pctchg_st_5pct_threshold():
    """ST 股一字板 5% 阈值：isST='1' + pctChg=+5.0 → is_unbuyable True（5%-0.2=4.8）。

    T2 配套：isST 派生后，ST 股一字板用 5% 阈值非 10%。
    """
    prev = {"close": 10.0}
    st_one_word = {"open": 10.5, "high": 10.5, "low": 10.5, "close": 10.5, "isST": "1"}
    enriched = enrich_pctchg([prev, st_one_word])
    assert enriched[1]["pctChg"] == 5.0  # (10.5-10)/10*100
    assert is_unbuyable_next_bar(enriched[1], "600000") is True  # ST 5% threshold=4.8, 5.0≥4.8
