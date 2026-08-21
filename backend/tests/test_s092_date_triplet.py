"""S092 T1+T2：dateTriplet 端点测试。

覆盖 spec `specs/S092-三视图交易日锚与时段推进/spec.md` §3-§5 的核心时段逻辑：
盘前/盘中/盘后过渡/盘后就绪/非交易日/手动覆盖/17:15 边界/15:00 边界。

mock 策略：patch `vr_paths._dt`（datetime 模块别名，C extension 不可变，
不能 setattr `now`，沿用 test_s056 的 FakeDateTime 整体替换惯例）。
所有日期用 2026-08-21（周五交易日，后一日 8-24 周一）。
"""
from __future__ import annotations

from datetime import date, datetime as _real_dt, timedelta as _td, timezone as _tz
from unittest import mock

import pytest

import vr_paths
from vr_paths import BEIJING_TZ, resolve_date_triplet


# ───────────────────────── helpers ─────────────────────────

class _FakeDateTime:
    """替代 datetime.datetime 类——配合 mock.patch('vr_paths._dt') 用。

    惯例参照 test_s056_weather_fuse.py::_FakeDateTime。暴露 now() 返回注入的
    固定时刻，其余类方法透传真 datetime（combine/strftime 等）。
    """

    _fixed: _real_dt = None  # class-level，由 _patch_now 注入

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._fixed.replace(tzinfo=None)
        return cls._fixed.astimezone(tz)

    # 透传真 datetime 的类方法（resolve_date_triplet 用到 combine）
    @classmethod
    def combine(cls, d, t, tzinfo=None):
        return _real_dt.combine(d, t, tzinfo=tzinfo)

    # 透传属性/类属性
    @staticmethod
    def __getattr__(name):  # 仅在类属性缺失时兜底（min/max 等）
        return getattr(_real_dt, name)


def _patch_now(monkeypatch, dt: _real_dt) -> None:
    """让 vr_paths._dt.now(tz=...) 返回 dt（dt 必须带 BEIJING_TZ）。"""
    _FakeDateTime._fixed = dt
    monkeypatch.setattr(vr_paths, "_dt", _FakeDateTime)


def _bj(year, month, day, hour, minute):
    """构造带 BEIJING_TZ 的 datetime。"""
    return _real_dt(year, month, day, hour, minute, tzinfo=BEIJING_TZ)


# 2026-08-21 是周五（交易日），8-22 周六，8-23 周日，8-24 周一（下一交易日）
# 8-20 周四（上一交易日）
T = date(2026, 8, 21)        # 今日交易日（周五）
T_prev = date(2026, 8, 20)   # 上一交易日（周四）
T_next = date(2026, 8, 24)   # 下一交易日（周一）


# ───────────────────────── 1. 盘前 ─────────────────────────

class TestPreMarket:
    """交易日盘前（00:00-09:29）。"""

    def test_pre_market_trading_day(self, monkeypatch):
        # 09:00 盘前
        _patch_now(monkeypatch, _bj(2026, 8, 21, 9, 0))
        r = resolve_date_triplet()
        assert r["stage"] == "pre_market"
        assert r["is_trading_day"] is True
        assert r["F"] == T_prev.isoformat()              # T-1
        assert r["review"] == r["F"]                     # 15:00 前未推进
        assert r["review_advanced"] is False
        assert r["today"] == T.isoformat()               # 盘前今日简报（F+1=T）
        assert r["forward"] == T.isoformat()             # 前瞻=F+1=T
        assert r["non_trading"] is False

    def test_pre_market_non_trading_day_skipped(self, monkeypatch):
        # 周六 09:00 → non_trading，不进 pre_market 分支
        _patch_now(monkeypatch, _bj(2026, 8, 22, 9, 0))
        r = resolve_date_triplet()
        assert r["stage"] == "non_trading"
        assert r["is_trading_day"] is False
        assert r["non_trading"] is True


# ───────────────────────── 2. 盘中 ─────────────────────────

class TestIntraday:
    """交易日盘中（09:30-14:59）。"""

    def test_intraday_stage(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 10, 30))
        r = resolve_date_triplet()
        assert r["stage"] == "intraday"
        assert r["F"] == T_prev.isoformat()
        assert r["review"] == r["F"]
        assert r["review_advanced"] is False
        assert r["today"] == T.isoformat()        # 实时盯盘 T
        assert r["forward"] == T.isoformat()


# ───────────────────────── 3. 盘后过渡 ─────────────────────────

class TestPostTransition:
    """盘后过渡窗（15:00-17:15）。"""

    def test_post_transition_review_advanced(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 15, 30))
        r = resolve_date_triplet()
        assert r["stage"] == "post_transition"
        assert r["F"] == T_prev.isoformat()                 # F 仍 T-1（8-20 周四）
        assert r["review"] == T.isoformat()                 # 复盘独立推进到 T（8-21）
        assert r["review_advanced"] is True
        assert r["today"] == T_prev.isoformat()             # 当日=简报快照 F
        assert r["forward"] == T.isoformat()                # 前瞻 F 的下一交易日=8-21（周四→周五）


# ───────────────────────── 4. 盘后就绪 ─────────────────────────

class TestPostMarket:
    """盘后就绪（17:15 后）。"""

    def test_post_market_f_advanced(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 18, 0))
        r = resolve_date_triplet()
        assert r["stage"] == "post_market"
        assert r["F"] == T.isoformat()              # F 推进到 T
        assert r["review"] == T.isoformat()         # 复盘 = T
        assert r["review_advanced"] is True
        assert r["today"] == T.isoformat()          # 当日=简报快照 F（R4 降级）
        assert r["forward"] == T_next.isoformat()   # 前瞻=F+1=T+1


# ───────────────────────── 5. 非交易日 ─────────────────────────

class TestNonTradingDay:
    """非交易日（周六/周日/节假日）。"""

    def test_saturday_stage_non_trading(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 22, 12, 0))  # 周六
        r = resolve_date_triplet()
        assert r["stage"] == "non_trading"
        assert r["is_trading_day"] is False
        assert r["non_trading"] is True
        # 周六 → F = 上一交易日（周五 8-21）
        assert r["F"] == T.isoformat()
        assert r["review"] == r["F"]
        assert r["review_advanced"] is False

    def test_non_trading_next_advance_points_to_next_trading_day(self, monkeypatch):
        # 周六 12:00 → 定时器指向下一交易日（周一）的 15:00 / 17:15
        _patch_now(monkeypatch, _bj(2026, 8, 22, 12, 0))
        r = resolve_date_triplet()
        from datetime import time as _time
        expected_review = _real_dt.combine(T_next, _time(15, 0), tzinfo=BEIJING_TZ).timestamp()
        expected_f = _real_dt.combine(T_next, _time(17, 15), tzinfo=BEIJING_TZ).timestamp()
        assert r["next_review_advance_at"] == pytest.approx(expected_review)
        assert r["next_f_advance_at"] == pytest.approx(expected_f)


# ───────────────────────── 6. 手动 date 覆盖 ─────────────────────────

class TestManualDateOverride:
    """手动 date 覆盖 F（R7），但 stage 仍按当前时刻算、定时器不推进。"""

    def test_manual_historical_date(self, monkeypatch):
        # 当前 18:00 盘后，但手动选 8-20（T_prev）
        _patch_now(monkeypatch, _bj(2026, 8, 21, 18, 0))
        r = resolve_date_triplet(T_prev)
        assert r["F"] == T_prev.isoformat()
        assert r["review"] == T_prev.isoformat()       # review=F（手动不推进）
        assert r["review_advanced"] is False          # 手动模式定时器不推进
        assert r["forward"] == T.isoformat()         # F 的下一交易日=8-21
        assert r["stage"] == "post_market"           # stage 仍按当前时刻算
        assert r["is_trading_day"] is True

    def test_manual_friday_forward_monday(self, monkeypatch):
        # 手动选周五 8-21（== 今天），但 R8a：过渡窗内选今天→复用自动态
        _patch_now(monkeypatch, _bj(2026, 8, 21, 16, 0))  # 过渡窗 16:00
        r = resolve_date_triplet(T)  # == today_bj 且交易日 → 复用自动态
        # 复用自动态：F=T_prev（8-20 周四），review_advanced=True，today=F（R4 降级）
        # forward=F 的下一交易日=8-21（周四→周五）
        assert r["F"] == T_prev.isoformat()
        assert r["review"] == T.isoformat()
        assert r["review_advanced"] is True
        assert r["forward"] == T.isoformat()

    def test_manual_non_today_friday_forward_monday(self, monkeypatch):
        # 手动选 8-14（周五，非今天）→ forward 应为 8-17（周一），非日历+1
        _patch_now(monkeypatch, _bj(2026, 8, 21, 18, 0))
        r = resolve_date_triplet(date(2026, 8, 14))
        assert r["F"] == "2026-08-14"
        assert r["forward"] == "2026-08-17"   # 周五→周一（非 8-15 周六）


# ───────────────────────── 7. 17:15 边界 ─────────────────────────

class TestFAdvanceBoundary:
    """F 推进 17:15 边界。"""

    def test_1714_f_is_t_prev(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 17, 14))
        r = resolve_date_triplet()
        assert r["F"] == T_prev.isoformat()
        assert r["stage"] == "post_transition"

    def test_1715_f_advances_to_today(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 17, 15))
        r = resolve_date_triplet()
        assert r["F"] == T.isoformat()
        assert r["stage"] == "post_market"


# ───────────────────────── 8. 15:00 边界 ─────────────────────────

class TestReviewAdvanceBoundary:
    """复盘独立推进 15:00 边界。"""

    def test_1459_review_not_advanced(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 14, 59))
        r = resolve_date_triplet()
        assert r["review_advanced"] is False
        assert r["review"] == r["F"]                # = T_prev
        assert r["stage"] == "intraday"

    def test_1500_review_advanced(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 15, 0))
        r = resolve_date_triplet()
        assert r["review_advanced"] is True
        assert r["review"] == T.isoformat()          # 推进到 T
        assert r["stage"] == "post_transition"


# ───────────────────────── 9. server_now & 通用结构 ─────────────────────────

class TestServerNowAndStructure:
    """server_now ISO + 返回 dict 结构完整性。"""

    def test_server_now_iso_with_tz(self, monkeypatch):
        fixed = _bj(2026, 8, 21, 15, 30)
        _patch_now(monkeypatch, fixed)
        r = resolve_date_triplet()
        assert r["server_now"] == fixed.isoformat()
        assert "+08:00" in r["server_now"]

    def test_keys_complete(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 12, 0))
        r = resolve_date_triplet()
        expected_keys = {
            "F", "review", "today", "forward", "stage", "is_trading_day",
            "review_advanced", "server_now", "next_review_advance_at",
            "next_f_advance_at", "non_trading",
        }
        assert set(r.keys()) == expected_keys

    def test_next_advance_at_is_epoch_seconds(self, monkeypatch):
        _patch_now(monkeypatch, _bj(2026, 8, 21, 9, 0))  # 盘前，今日 15:00 还没到
        r = resolve_date_triplet()
        # 今日 15:00 / 17:15 的 epoch
        from datetime import time as _time
        exp_review = _real_dt.combine(T, _time(15, 0), tzinfo=BEIJING_TZ).timestamp()
        exp_f = _real_dt.combine(T, _time(17, 15), tzinfo=BEIJING_TZ).timestamp()
        assert r["next_review_advance_at"] == pytest.approx(exp_review)
        assert r["next_f_advance_at"] == pytest.approx(exp_f)

    def test_next_advance_after_target_time_points_to_next_trading_day(self, monkeypatch):
        # 18:00 已过今日 17:15 → 下次指向下一交易日 8-24
        _patch_now(monkeypatch, _bj(2026, 8, 21, 18, 0))
        r = resolve_date_triplet()
        from datetime import time as _time
        exp_review = _real_dt.combine(T_next, _time(15, 0), tzinfo=BEIJING_TZ).timestamp()
        exp_f = _real_dt.combine(T_next, _time(17, 15), tzinfo=BEIJING_TZ).timestamp()
        assert r["next_review_advance_at"] == pytest.approx(exp_review)
        assert r["next_f_advance_at"] == pytest.approx(exp_f)
