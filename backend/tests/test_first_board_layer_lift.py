# -*- coding: utf-8 -*-
"""S077 first_board_layer_lift 纯逻辑离线单测（spec §8）。

不联网：合成 first_boards/kline，验逐层剔除 + apply_layers 递减 + 策略口径标的收益 +
day-paired lift（含非配对日跳过）+ 四态。live main 下轮接线。
AAA 结构 + 描述性命名。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
sys.path.insert(0, str(ROOT))

import tools.first_board_layer_lift as m  # noqa: E402


# ── 层1 封板质量 ──────────────────────────────────────────────────────────────

def test_layer1_break_times_2_excluded():
    ok, r = m.exclude_layer1_seal_quality({"break_times": 2, "seal_amount": 1e8, "float_cap": 1e9})
    assert ok is False and "炸板2次" in r


def test_layer1_seal_ratio_boundary_keep_and_below_exclude():
    # min_seal_ratio=0.001 (0.1%)：<0.1% 剔；=0.1% 边界 keep
    ok, _ = m.exclude_layer1_seal_quality({"break_times": 0, "seal_amount": 1e6, "float_cap": 1e9})  # =0.1%
    assert ok is True  # 边界 keep（< 才剔）
    ok, r = m.exclude_layer1_seal_quality({"break_times": 0, "seal_amount": 5e5, "float_cap": 1e9})  # 0.05%
    assert ok is False and "封单" in r


def test_layer1_data_missing_keeps_not_over_exclude():
    # 字段缺失→跳过对应条件，不误剔
    ok, r = m.exclude_layer1_seal_quality({})
    assert ok is True and r is None
    ok, _ = m.exclude_layer1_seal_quality({"break_times": 0, "seal_amount": None, "float_cap": 1e9})
    assert ok is True  # 封单 None → 跳过封单条件


# ── 层2 筹码结构 ─────────────────────────────────────────────────────────────

def test_layer2_turnover_above_30_excluded():
    ok, r = m.exclude_layer2_chip_structure({"turnover_pct": 35})
    assert ok is False and "换手35%松动" in r


def test_layer2_turnover_missing_keeps():
    assert m.exclude_layer2_chip_structure({})[0] is True
    assert m.exclude_layer2_chip_structure({"turnover_pct": 10})[0] is True


# ── 层3 市场环境（孤板；创业板不剔除）────────────────────────────────────────

def test_layer3_isolated_board_excluded():
    ok, r = m.exclude_layer3_market_env({"sector_zt_count": 1, "concept_tags": []})
    assert ok is False and "孤板" in r


def test_layer3_sector_linkage_or_theme_keeps():
    assert m.exclude_layer3_market_env({"sector_zt_count": 3, "concept_tags": []})[0] is True   # 板块联动
    assert m.exclude_layer3_market_env({"sector_zt_count": 1, "concept_tags": ["AI"]})[0] is True  # 有题材


def test_layer3_chinext_no_special_exclude_but_isolated_still_excluded():
    # grill-decisions.md：创业板"不剔除"= 无创业板专属剔除条件（改分组展示）；
    # 孤板剔除仍适用所有（含创业板）。reading(B)：创业板孤板仍剔。
    assert m.exclude_layer3_market_env({"sector_zt_count": 3, "concept_tags": []})[0] is True  # 创业板有联动 keep
    ok, r = m.exclude_layer3_market_env({"sector_zt_count": 1, "concept_tags": []})  # 创业板孤板
    assert ok is False and "孤板" in r  # 孤板仍剔


# ── apply_layers 逐层递减 ────────────────────────────────────────────────────

def test_apply_layers_progressive_filtering():
    # Arrange：6 只，各触发不同层剔除
    fbs = [
        {"code": "fb1", "break_times": 2, "seal_amount": 1e8, "float_cap": 1e9},  # 层1 炸板
        {"code": "fb2", "break_times": 0, "seal_amount": 5e5, "float_cap": 1e9},  # 层1 封单<0.1%
        {"code": "fb3", "break_times": 0, "seal_amount": 1e8, "float_cap": 1e9, "turnover_pct": 35},  # 层2 换手
        {"code": "fb4", "break_times": 0, "seal_amount": 1e8, "float_cap": 1e9,
         "turnover_pct": 10, "sector_zt_count": 1, "concept_tags": []},  # 层3 孤板
        {"code": "fb5", "break_times": 0, "seal_amount": 1e8, "float_cap": 1e9,
         "turnover_pct": 10, "sector_zt_count": 3},  # clean
        {"code": "fb6", "break_times": 0, "seal_amount": 1e8, "float_cap": 1e9,
         "turnover_pct": 10, "sector_zt_count": 2},  # clean
    ]
    # Act
    layers = m.apply_layers(fbs)
    # Assert：逐层递减
    assert layers["layer0"] == ["fb1", "fb2", "fb3", "fb4", "fb5", "fb6"]
    assert layers["layer1"] == ["fb3", "fb4", "fb5", "fb6"]  # fb1/fb2 层1剔
    assert layers["layer2"] == ["fb4", "fb5", "fb6"]          # fb3 层2剔
    assert layers["layer3"] == ["fb5", "fb6"]                 # fb4 层3剔
    assert len(layers["excluded"]) == 4
    by_layer = {1: [], 2: [], 3: []}
    for e in layers["excluded"]:
        by_layer[e["layer"]].append(e["code"])
    assert set(by_layer[1]) == {"fb1", "fb2"}
    assert by_layer[2] == ["fb3"]
    assert by_layer[3] == ["fb4"]


# ── 策略口径标的收益 ─────────────────────────────────────────────────────────

def test_target_return_strategy_caliber_not_overnight():
    # (D+2 close - D+1 open)/D+1 open * 100 ≠ Phase 0 隔夜 (D+1open-D close)
    assert m.target_return(10.0, 11.0) == 10.0    # (11-10)/10*100
    assert m.target_return(10.0, 9.0) == -10.0
    assert m.target_return(None, 11.0) is None
    assert m.target_return(10.0, None) is None
    assert m.target_return(0.0, 11.0) is None      # open<=0


# ── day-paired lift（非池化，§44 day-cluster 防假象）─────────────────────────

def test_day_paired_lift_basic():
    # Arrange
    surv = {"2026-08-01": [2.0, 3.0], "2026-08-02": [-1.0, 4.0]}
    raw = {"2026-08-01": [1.0, -2.0], "2026-08-02": [0.5, 0.5]}
    # Act
    r = m.day_paired_lift(surv, raw)
    # Assert：day1 surv wr=1.0 / raw wr=0.5 → lift 2.0；day2 surv 0.5 / raw 1.0 → lift 0.5；avg 1.25
    assert r["n_days"] == 2
    assert r["day_lifts"][0]["winrate_lift"] == 2.0
    assert r["day_lifts"][1]["winrate_lift"] == 0.5
    assert r["winrate_lift_avg"] == 1.25
    assert r["surv_n_pooled"] == 4 and r["raw_n_pooled"] == 4


def test_day_paired_lift_skips_unpaired_day():
    # 08-03 仅 surv 有，08-02 仅 raw 有 → 不可配对，跳
    surv = {"2026-08-01": [2.0, 3.0], "2026-08-03": [1.0]}
    raw = {"2026-08-01": [1.0, -2.0], "2026-08-02": [0.5]}
    r = m.day_paired_lift(surv, raw)
    assert r["n_days"] == 1
    assert r["day_lifts"][0]["date"] == "2026-08-01"


# ── §44 四态 ─────────────────────────────────────────────────────────────────

def test_four_state_all_states():
    assert m.four_state(2.5, 30) == "validated"     # lift≥2 + n≥30
    assert m.four_state(1.5, 30) == "未validated"   # 1≤lift<2
    assert m.four_state(0.8, 30) == "劣于随机"       # <1
    assert m.four_state(2.5, 10) == "探索性"         # n<30 overrides
    assert m.four_state(None, 30) == "探索性"        # lift None


# ── live 辅助纯函数（数据解析口径，易错点）──────────────────────────────────

_BARS = [
    {"date": "2026-08-01", "open": 10.0, "close": 11.0, "turn": 5.0},
    {"date": "2026-08-02", "open": 10.5, "close": 10.8, "turn": 6.0},
    {"date": "2026-08-03", "open": 11.0, "close": 11.5, "turn": 7.0},
]


def test_to_float_garbage():
    assert m._to_float(None) is None
    assert m._to_float("-") is None
    assert m._to_float("null") is None
    assert m._to_float("1,234.5") == 1234.5
    assert m._to_float(3) == 3.0


def test_is_first_board_lbc():
    assert m._is_first_board({"lbc": 1}) is True
    assert m._is_first_board({"lbc": "1"}) is True
    assert m._is_first_board({"lbc": 0}) is True      # 缺失/0 视为首板（东财口径）
    assert m._is_first_board({"lbc": None}) is True
    assert m._is_first_board({"lbc": 2}) is False    # 连板非首板
    assert m._is_first_board({"lbc": 3}) is False


def test_d1_open_d2_close_d_in_bars():
    # D=2026-08-01（首板日），D+1=bars[1] open, D+2=bars[2] close
    assert m._d1_open_d2_close(_BARS, "2026-08-01") == (10.5, 11.5)


def test_d1_open_d2_close_d_not_in_bars_uses_first_after():
    # D 早于 bars 首日 → D+1=首个>D=bars[0]，D+2=bars[1] close
    assert m._d1_open_d2_close(_BARS, "2026-07-31") == (10.0, 10.8)


def test_d1_open_d2_close_d_is_last_bar_returns_none():
    # D=末 bar → D+1 越界 → (None, None)
    assert m._d1_open_d2_close(_BARS, "2026-08-03") == (None, None)


def test_d1_open_d2_close_empty_bars():
    assert m._d1_open_d2_close([], "2026-08-01") == (None, None)


def test_turn_for_date_found_and_missing():
    assert m._turn_for_date(_BARS, "2026-08-02") == 6.0
    assert m._turn_for_date(_BARS, "2026-09-01") is None


def test_sector_zt_count_from_pool():
    pool = [{"hybk": "AI"}, {"hybk": "AI"}, {"hybk": "芯片"}, {"hybk": "AI"}]
    assert m._sector_zt_count_from_pool(pool, "AI") == 3
    assert m._sector_zt_count_from_pool(pool, None) == 0   # 空 hybk→孤板
    assert m._sector_zt_count_from_pool(pool, "无此板块") == 0


def test_normalize_fb_full():
    item = {"c": "600127", "n": "金健", "zbc": 0, "fund": 1e8, "ltsz": 1e9, "hybk": "AI"}
    pool = [{"hybk": "AI"}, {"hybk": "AI"}]
    fb = m._normalize_fb(item, pool, _BARS, "2026-08-01")
    assert fb["code"] == "600127"
    assert fb["name"] == "金健"
    assert fb["break_times"] == 0.0
    assert fb["seal_amount"] == 1e8
    assert fb["float_cap"] == 1e9
    assert fb["turnover_pct"] == 5.0  # bars[0] turn（D=08-01）
    assert fb["sector_zt_count"] == 2
    assert fb["concept_tags"] == []  # 简化：不 fetch 题材
    assert fb["hybk"] == "AI"


# ── baostock 算涨停历史（_compute_zt_history）──────────────────────────────

_BARS_HISTORY = [
    {"date": "2026-08-01", "open": 10.0, "close": 10.5, "turn": 5.0, "pctChg": 5.0},   # 非涨停
    {"date": "2026-08-02", "open": 10.5, "close": 11.55, "turn": 8.0, "pctChg": 10.0},  # 涨停 首板
    {"date": "2026-08-03", "open": 11.55, "close": 12.7, "turn": 9.0, "pctChg": 10.0}, # 涨停 二板
    {"date": "2026-08-04", "open": 12.7, "close": 13.0, "turn": 4.0, "pctChg": 2.4},   # 非涨停
    {"date": "2026-08-05", "open": 13.0, "close": 14.3, "turn": 12.0, "pctChg": 10.0}, # 涨停 首板
    {"date": "2026-08-06", "open": 14.3, "close": 14.5, "turn": 6.0, "pctChg": 1.4},  # 非涨停
    {"date": "2026-08-07", "open": 14.5, "close": 15.95, "turn": 3.0, "pctChg": 10.0}, # 涨停 首板（末 bar，d2 None）
]


def test_compute_zt_history_lbc_and_first_board():
    events = m._compute_zt_history({"600127": _BARS_HISTORY})
    # 4 涨停 events: 08-02(首板), 08-03(二板), 08-05(首板), 08-07(首板 d2 None)
    assert len(events) == 4
    by_date = {e["date"]: e for e in events}
    # 08-02: 首板 lbc=1, turnover=8
    e = by_date["2026-08-02"]
    assert e["is_first_board"] is True and e["lbc"] == 1
    assert e["turnover_pct"] == 8.0
    # 08-03: 二板 lbc=2 not first
    e = by_date["2026-08-03"]
    assert e["is_first_board"] is False and e["lbc"] == 2
    # 08-05: 首板 lbc=1, target_return > 0
    e = by_date["2026-08-05"]
    assert e["is_first_board"] is True and e["lbc"] == 1
    assert e["target_return"] is not None and e["target_return"] > 0
    # 08-07: 首板但末 bar → d1/d2 None → target_return None
    e = by_date["2026-08-07"]
    assert e["is_first_board"] is True
    assert e["target_return"] is None


def test_compute_zt_history_pct_threshold():
    # pctChg 5 < 9.9 → 不算涨停
    assert m._compute_zt_history({"c": [
        {"date": "D", "open": 1.0, "close": 1.0, "turn": 1.0, "pctChg": 5.0}]}) == []
    # pctChg 10 >= 9.9 → 涨停；首板（前无非涨停日 → lbc=1）
    events = m._compute_zt_history({"c": [
        {"date": "D1", "open": 1.0, "close": 1.0, "turn": 1.0, "pctChg": 10.0},
        {"date": "D2", "open": 1.0, "close": 1.0, "turn": 1.0, "pctChg": 1.0}]})
    assert len(events) == 1
    assert events[0]["is_first_board"] is True


def test_compute_zt_history_empty_and_missing_pctchg():
    # 空 bars / 无 pctChg → 无事件
    assert m._compute_zt_history({"c": []}) == []
    assert m._compute_zt_history({"c": [
        {"date": "D", "open": 1.0, "close": 1.0, "turn": 1.0}]}) == []  # 无 pctChg
