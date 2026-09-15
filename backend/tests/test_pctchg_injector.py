# -*- coding: utf-8 -*-
"""S204 R14 T1b: pctChg harness 注入 test（TDD RED→GREEN）。

验证：baostock cache bar 无 pctChg → is_unbuyable_next_bar 误判一字板可买（bug）；
enrich_pctchg 注入后一字板正确判不可买。
"""
from __future__ import annotations

import json

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


def test_pctchg_overrides_zero_for_real_cache_shape():
    """真实 cache 形态：bar **有** pctChg=0.0（baostock 一字板数据缺口）→ enrich 必须覆盖为计算值。

    实测 baostock_kline_cache.json（5231 股 / 105506 bars 抽样 50 股）：字段含 pctChg（10 keys 非 7），
    但 0.3% bars pctChg=0.0——其中一字板 63 个（真 bug：is_unbuyable 读 0.0<9.8 误判可买）。
    旧 enrich 用 `b.get("pctChg", calc)`——键存在（值 0.0）→ 返 0.0 非计算值 → bug 未修。
    修：existing==0.0/缺失 → 用 close 差覆盖；非零 baostock 原值保留（99.98% 准确，8383 match/2 mismatch）。
    """
    prev = {"date": "2026-01-01", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 100, "amount": 1000}
    # 真实 cache 形态：一字涨停板 + pctChg=0.0（baostock 对一字板返 0.0 的数据缺口）
    one_word_zero_pct = {"date": "2026-01-02", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 100, "amount": 1100, "pctChg": 0.0}
    enriched = enrich_pctchg([prev, one_word_zero_pct])
    assert enriched[1]["pctChg"] == 10.0  # 覆盖 0.0 为计算值（旧逻辑保留 0.0 = bug 未修）
    assert is_unbuyable_next_bar(enriched[1], "600000") is True  # 修后正确判不可买


def test_pctchg_overrides_zero_non_oneline_harmless():
    """非一字板但 pctChg=0.0（208/271 实测）→ 覆盖为计算值，is_unbuyable 仍 False（四价不等）——无害改进。

    这些 bar 有真实价格波动但 baostock 返 pctChg=0.0；覆盖为 close 差复算值不改变 is_unbuyable
    （四价不等→返 False 正确，非涨停），但让 pctChg 字段诚实（下游若读 pctChg 不再拿到假 0.0）。
    """
    prev = {"date": "2026-01-01", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 100, "amount": 1000}
    moving_zero_pct = {"date": "2026-01-02", "open": 10.4, "high": 10.5, "low": 9.8, "close": 10.3, "volume": 200, "amount": 2100, "pctChg": 0.0}
    enriched = enrich_pctchg([prev, moving_zero_pct])
    assert enriched[1]["pctChg"] == 3.0  # (10.3-10)/10*100——覆盖假 0.0
    assert is_unbuyable_next_bar(enriched[1], "600000") is False  # 四价不等→非一字板→可买（正确）


def test_load_kline_cache_wires_enrich_pctchg(monkeypatch, tmp_path):
    """S204 T1 wiring 验收：_load_kline_cache 对返回 bars 调 enrich_pctchg（覆盖 baostock 0.0 缺口）。

    合成 cache（一字板 pctChg=0.0）→ _load_kline_cache → 返回 bar pctChg 被覆盖为计算值。
    防止"enrich_pctchg 模块存在但零生产调用方"的看着做完其实没陷阱（2026-09-16 审计教训）。
    """
    import tools.first_board_premium_baseline as fb
    fake = tmp_path / "baostock_kline_cache.json"
    fake.write_text(json.dumps({
        "600000": [
            {"date": "2026-01-01", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 100, "amount": 1000},
            {"date": "2026-01-02", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 100, "amount": 1100, "pctChg": 0.0},
        ]
    }))
    monkeypatch.setattr(fb, "KLINE_CACHE", fake)
    monkeypatch.setattr(fb, "_KLINE_CACHE_MEMO", None)  # reset memo（mtime-key 已自动失效，此为防御显式）
    cache = fb._load_kline_cache()
    bar = cache["600000"][1]
    assert bar["pctChg"] == 10.0  # 0.0 被 enrich 覆盖（wiring 生效）
    assert is_unbuyable_next_bar(bar, "600000") is True  # 一字板正确判不可买
