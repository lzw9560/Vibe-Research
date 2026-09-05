# -*- coding: utf-8 -*-
"""S152 盘中 H2 harness 测试（compute_h2_features 纯函数 + day_paired_lift 接口）。

覆盖：
- A1 一字板 bars → first_lock=09:35 首bar, open_count=0, is_one_word=True
- A2 开板 bars → open_count>0, broken_duration_min>0
- A3 缺数据（空 bars / 全 None）→ None 不臆造
- A4 day_paired_lift 接口（复用 first_board_layer_lift，非池化）
"""
from __future__ import annotations

from tools.first_plate_h2_lift import (
    compute_h2_features, _is_early_lock, _is_late_lock,
    _is_open_board, _is_high_drop, _time_suffix,
)


def _bar(time: str, close: float, opn: float = 10.0) -> dict:
    return {"date": "2026-08-17", "time": time, "open": opn, "high": close,
            "low": close, "close": close, "volume": 1000.0}


def _next_bar(opn: float, close: float) -> dict:
    return {"date": "2026-08-18", "time": "20260818093500000", "open": opn, "high": close,
            "low": close, "close": close, "volume": 1000.0}


# 48 个 5min bar 时间（9:35~15:00），17 字符 baostock 格式 YYYYMMDDHHMMSSmmm
_TIMES_48 = [f"20260817{h:02d}{m:02d}00000" for h, m in (
    [(9, mm) for mm in range(35, 60, 5)] +
    [(h, mm) for h in range(10, 15) for mm in range(0, 60, 5)] +
    [(15, 0)]
)][:48]


class TestComputeH2Features:
    def test_one_word_board_all_locked(self):  # A1
        """一字板：全 bar close=涨停价，首 bar 封死，open_count=0。"""
        bars = [_bar(t, 11.15) for t in _TIMES_48]
        feat = compute_h2_features(bars, [_next_bar(11.0, 11.5)])
        assert feat is not None
        assert feat["zt_price"] == 11.15
        assert feat["first_lock_idx"] == 0
        assert feat["first_lock_time"] == _TIMES_48[0]
        assert feat["open_count"] == 0
        assert feat["broken_duration_min"] == 0
        assert feat["is_one_word"] is True
        assert _is_early_lock(feat) is True  # 09:35 <= 10:00

    def test_break_board_open_count_positive(self):  # A2
        """开板：封板后 close<zt 的 bar → open_count>0, broken_duration>0。"""
        bars = [
            _bar("20260817093500000", 10.0),  # 开盘未触涨停
            _bar("20260817094000000", 10.5),
            _bar("20260817094500000", 11.0),  # 涨停价 11.0
            _bar("20260817095000000", 10.8),  # 开板（close<zt）
            _bar("20260817095500000", 11.0),  # 重新封板
            _bar("20260817100000000", 11.0),
        ]
        feat = compute_h2_features(bars, [_next_bar(10.5, 10.8)])
        assert feat is not None
        assert feat["zt_price"] == 11.0
        assert feat["first_lock_idx"] == 2  # idx 2 首 bar 触 11.0
        assert feat["open_count"] == 1  # idx 3 的 10.8 开板
        assert feat["broken_duration_min"] == 5
        assert feat["is_one_word"] is False
        assert _is_early_lock(feat) is True  # 09:45 <= 10:00

    def test_late_lock_not_early(self):
        """晚封板（>10:00）→ _is_early_lock False。"""
        bars = [
            _bar("20260817093500000", 10.0),
            _bar("20260817140000000", 11.0),  # 14:00 封板
            _bar("20260817140500000", 11.0),
        ]
        feat = compute_h2_features(bars, [_next_bar(10.5, 10.8)])
        assert feat is not None
        assert _is_early_lock(feat) is False  # 14:00 > 10:00

    def test_empty_bars_returns_none(self):  # A3
        assert compute_h2_features([], []) is None
        assert compute_h2_features([_bar("20260817093500000", 10.0)], []) is None  # <2 bars

    def test_no_next_bars_no_return(self):  # A3 缺次日
        bars = [_bar(t, 11.0) for t in _TIMES_48[:3]]
        feat = compute_h2_features(bars, [])
        assert feat is not None
        assert feat["next_day_return"] is None  # 缺次日不臆造

    def test_next_day_return_o2c_baseline(self):
        """next_day_return = (次日 close - 次日 open) / 次日 open × 100。"""
        bars = [_bar(t, 11.0) for t in _TIMES_48[:3]]
        feat = compute_h2_features(bars, [_next_bar(10.0, 10.5)])  # open=10, close=10.5
        assert feat["next_day_return"] == 5.0  # (10.5-10)/10*100=5.0


def test_time_suffix_extraction():
    """baostock time（17 字符 YYYYMMDDHHMMSSmmm）后 9 位 = HHMMSSmmm，用于早封板比较。"""
    assert _time_suffix("20260817093500000") == "093500000"  # HH=09 MM=35 SS=00 mmm=000
    assert _time_suffix("20260817140000000") == "140000000"


def test_t23_predicates():
    """T2.3 盘中交互谓词：开板/晚封板/大回撤。"""
    one_word = {"first_lock_time": "20260817093500000", "broken_duration_min": 0.0, "max_drop_pct": 0.0}
    open_board = {"first_lock_time": "20260817094500000", "broken_duration_min": 10.0, "max_drop_pct": 1.5}
    late_lock = {"first_lock_time": "20260817143000000", "broken_duration_min": 0.0, "max_drop_pct": 0.5}
    high_drop = {"first_lock_time": "20260817100000000", "broken_duration_min": 5.0, "max_drop_pct": 4.2}
    # 开板（broken_duration>0）
    assert not _is_open_board(one_word)
    assert _is_open_board(open_board)
    # 晚封板（>14:00，end_of_day_sneak 近似）
    assert not _is_late_lock(one_word)
    assert _is_late_lock(late_lock)
    # 大回撤（>3%，weak_turn_strong 候选）
    assert not _is_high_drop(one_word)
    assert _is_high_drop(high_drop)


def test_day_paired_lift_interface_reused():
    """A4：day_paired_lift 复用 first_board_layer_lift（非池化 day-cluster）。"""
    from tools.first_board_layer_lift import day_paired_lift
    surv = [1.0, 2.0, -1.0]  # winrate 2/3=0.667
    raw = [1.0, 2.0, -1.0, -2.0, 0.5]  # winrate 3/5=0.6（0.5>0 是 win）
    r = day_paired_lift({"2026-08-17": surv}, {"2026-08-17": raw})
    assert r["n_days"] == 1
    assert r["winrate_lift_avg"] is not None
    assert abs(r["winrate_lift_avg"] - round(0.667 / 0.6, 4)) < 0.05  # lift≈1.111
