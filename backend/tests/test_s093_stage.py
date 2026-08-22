"""S093 T1：stage 枚举修订测试。

覆盖 spec `specs/S093-三视图内容重组与飞书通知/spec.md` §3.A（R1-R3）的 stage 边界修订：
- pre_open 新分支（09:00-09:30）→ stage=pre_open + today=forward
- intraday 15:30 边界（15:29 intraday / 15:30 post_transition）
- post_transition 15:30 边界
- 定时器 next_review_advance_at 用 15:30
- today 条件含 pre_open（09:15 盘前当日数据日=forward 不是 F 快照）

mock 策略同 test_s092_date_triplet.py：patch `vr_paths._dt`（datetime 模块别名）。
所有日期用 2026-08-21（周五交易日，后一日 8-24 周一）。
"""
from __future__ import annotations

from datetime import date, datetime as _real_dt, timezone as _tz
from unittest import mock

import pytest

import vr_paths
from vr_paths import BEIJING_TZ, resolve_date_triplet


# ───────────────────────── helpers（同 test_s092 风格） ─────────────────────────

class _FakeDateTime:
    """替代 datetime.datetime 类——配合 mock.patch('vr_paths._dt') 用。"""

    _fixed: _real_dt = None

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._fixed.replace(tzinfo=None)
        return cls._fixed.astimezone(tz)

    @classmethod
    def combine(cls, d, t, tzinfo=None):
        return _real_dt.combine(d, t, tzinfo=tzinfo)

    @staticmethod
    def __getattr__(name):
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


# ───────────────────────── 1. pre_open 新分支 ─────────────────────────

class TestPreOpen:
    """pre_open 新分支（09:00-09:30 集合竞价/开盘准备，S093 新增）。"""

    def test_0900_is_pre_open(self, monkeypatch):
        """09:00 整点 → pre_open（not pre_market，09:00 是 pre_market/pre_open 分界）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 9, 0))
        r = resolve_date_triplet()
        assert r["stage"] == "pre_open"
        assert r["is_trading_day"] is True

    def test_0915_is_pre_open(self, monkeypatch):
        """09:15 集合竞价 → pre_open。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 9, 15))
        r = resolve_date_triplet()
        assert r["stage"] == "pre_open"

    def test_0929_is_pre_open(self, monkeypatch):
        """09:29 最后一分钟 pre_open（09:30 是 pre_open/intraday 分界）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 9, 29))
        r = resolve_date_triplet()
        assert r["stage"] == "pre_open"

    def test_pre_open_today_is_forward(self, monkeypatch):
        """pre_open 时段 today=forward（=F 的下一交易日=T），不是 F 快照。

        Oracle 阻断项 #5：today 条件含 pre_open，否则 09:00-09:30 当日数据日掉回 F 快照。
        """
        _patch_now(monkeypatch, _bj(2026, 8, 21, 9, 15))
        r = resolve_date_triplet()
        assert r["stage"] == "pre_open"
        assert r["today"] == T.isoformat()              # today = T（forward）
        assert r["forward"] == T.isoformat()            # forward = T
        assert r["today"] == r["forward"]                # today == forward
        assert r["today"] != r["F"]                      # 不是 F 快照
        assert r["F"] == T_prev.isoformat()              # F = T-1

    def test_pre_open_review_not_advanced(self, monkeypatch):
        """pre_open 时段 review 未推进（15:30 前未推进）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 9, 15))
        r = resolve_date_triplet()
        assert r["review_advanced"] is False
        assert r["review"] == r["F"]                     # review = F = T_prev


# ───────────────────────── 2. intraday 15:30 边界 ─────────────────────────

class TestIntradayBoundary:
    """intraday 延长到 15:30（09:30-15:30），15:30 是 intraday/post_transition 分界。"""

    def test_1529_is_intraday(self, monkeypatch):
        """15:29 仍是 intraday（盘中延长 30 分钟）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 15, 29))
        r = resolve_date_triplet()
        assert r["stage"] == "intraday"

    def test_1529_review_not_advanced(self, monkeypatch):
        """15:29 review 未推进（15:30 才推进）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 15, 29))
        r = resolve_date_triplet()
        assert r["review_advanced"] is False
        assert r["review"] == r["F"]                     # = T_prev

    def test_1529_today_is_forward(self, monkeypatch):
        """15:29 仍 intraday → today=forward（实时盯盘 T）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 15, 29))
        r = resolve_date_triplet()
        assert r["today"] == T.isoformat()              # 实时盯盘 T


# ───────────────────────── 3. post_transition 15:30 边界 ─────────────────────────

class TestPostTransitionBoundary:
    """post_transition 从 15:30 开始（15:30-17:15）。"""

    def test_1530_is_post_transition(self, monkeypatch):
        """15:30 整点 → post_transition（intraday/post_transition 分界）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 15, 30))
        r = resolve_date_triplet()
        assert r["stage"] == "post_transition"

    def test_1530_review_advanced(self, monkeypatch):
        """15:30 review 推进到 T（复盘独立推进点 15:30）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 15, 30))
        r = resolve_date_triplet()
        assert r["review_advanced"] is True
        assert r["review"] == T.isoformat()              # 推进到 T

    def test_1530_today_is_f_snapshot(self, monkeypatch):
        """15:30 post_transition → today=F 简报快照（R4 降级）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 15, 30))
        r = resolve_date_triplet()
        assert r["today"] == r["F"]                      # today = F 快照
        assert r["today"] == T_prev.isoformat()          # = T_prev

    def test_1600_still_post_transition(self, monkeypatch):
        """16:00 仍是 post_transition。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 16, 0))
        r = resolve_date_triplet()
        assert r["stage"] == "post_transition"
        assert r["review_advanced"] is True


# ───────────────────────── 4. 定时器 next_review_advance_at 用 15:30 ─────────────────────────

class TestTimerAdvanceEpoch:
    """定时器推进点 15:00→15:30（Oracle 阻断项 #5）。"""

    def test_next_review_advance_at_uses_1530(self, monkeypatch):
        """盘前 → next_review_advance_at 指向今日 15:30（不是 15:00）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 8, 30))
        r = resolve_date_triplet()
        from datetime import time as _time
        exp_review = _real_dt.combine(T, _time(15, 30), tzinfo=BEIJING_TZ).timestamp()
        assert r["next_review_advance_at"] == pytest.approx(exp_review)

    def test_next_review_advance_after_1530_points_to_next_day(self, monkeypatch):
        """15:30 后 → next_review_advance_at 指向下一交易日 15:30。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 16, 0))
        r = resolve_date_triplet()
        from datetime import time as _time
        exp_review = _real_dt.combine(T_next, _time(15, 30), tzinfo=BEIJING_TZ).timestamp()
        assert r["next_review_advance_at"] == pytest.approx(exp_review)

    def test_next_f_advance_at_unchanged_1715(self, monkeypatch):
        """F 推进点不变（17:15）。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 8, 30))
        r = resolve_date_triplet()
        from datetime import time as _time
        exp_f = _real_dt.combine(T, _time(17, 15), tzinfo=BEIJING_TZ).timestamp()
        assert r["next_f_advance_at"] == pytest.approx(exp_f)


# ───────────────────────── 5. today 条件含 pre_open ─────────────────────────

class TestTodayConditionPreOpen:
    """today 条件含 pre_open（Oracle 阻断项 #5）。

    pre_open 时段 today=next_trading_date(F)=T=forward，不是 F 快照。
    若 today 条件不含 pre_open，09:00-09:30 会掉回 F 快照（today=F）。
    """

    def test_pre_open_today_equals_forward(self, monkeypatch):
        """09:15 pre_open → today=forward（T），证明 today 条件含 pre_open。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 9, 15))
        r = resolve_date_triplet()
        assert r["stage"] == "pre_open"
        assert r["today"] == T.isoformat()
        assert r["forward"] == T.isoformat()
        assert r["today"] == r["forward"]

    def test_pre_market_today_also_forward(self, monkeypatch):
        """08:30 pre_market → today=forward（T），保持一致。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 8, 30))
        r = resolve_date_triplet()
        assert r["stage"] == "pre_market"
        assert r["today"] == T.isoformat()
        assert r["today"] == r["forward"]

    def test_intraday_today_also_forward(self, monkeypatch):
        """10:30 intraday → today=forward（T），保持一致。"""
        _patch_now(monkeypatch, _bj(2026, 8, 21, 10, 30))
        r = resolve_date_triplet()
        assert r["stage"] == "intraday"
        assert r["today"] == T.isoformat()
        assert r["today"] == r["forward"]
