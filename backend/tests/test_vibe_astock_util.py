"""vibe_astock_util 单测（P4-T1a util.py 4 函数 + P4-T1b trade_calendar 4 函数）。"""
from __future__ import annotations

import datetime
import json
import os

import pytest

from utils import vibe_astock_util as u
from utils.vibe_astock_util import (
    atomic_write_json,
    china_now,
    china_today,
    is_a_share_closed,
    is_settled,
    latest_closed_session,
    live_quotes_are_close_of,
    trade_dates_ending_at,
    validate_trade_date,
)


def _mock_now(y, mo, d, h, mi):
    """构造固定时间（naive，is_a_share_closed/latest_closed_session 只看时分日期）。"""
    return datetime.datetime(y, mo, d, h, mi)


def test_china_now_returns_datetime():
    assert isinstance(china_now(), datetime.datetime)


def test_china_today_is_today_format():
    assert china_today() == china_now().strftime("%Y-%m-%d")
    assert len(china_today()) == 10  # YYYY-MM-DD


def test_validate_trade_date_accepts_today():
    today = china_today()
    assert validate_trade_date(today) == today


def test_validate_trade_date_accepts_past():
    d = (datetime.datetime.strptime(china_today(), "%Y-%m-%d") - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    assert validate_trade_date(d) == d


def test_validate_trade_date_rejects_future():
    future = (datetime.datetime.strptime(china_today(), "%Y-%m-%d") + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        validate_trade_date(future)
        assert False, "应拒绝未来日期"
    except ValueError as e:
        assert "未来" in str(e)


def test_validate_trade_date_rejects_invalid_format():
    for bad in ["2026-13-01", "not-a-date", "2026/01/01", "20260101", "2026-02-30"]:
        try:
            validate_trade_date(bad)
            assert False, f"应拒绝 {bad}"
        except ValueError:
            pass


def test_validate_trade_date_rejects_non_string():
    for bad in [20260101, None, 3.14, ["2026-01-01"]]:
        try:
            validate_trade_date(bad)
            assert False, f"应拒绝 {bad!r}"
        except ValueError:
            pass


def test_validate_trade_date_strips_whitespace():
    assert validate_trade_date("  2026-01-01  ") == "2026-01-01"


def test_atomic_write_json_writes(tmp_path):
    path = str(tmp_path / "sub" / "out.json")
    assert atomic_write_json(path, {"a": 1, "b": [2, 3]}) is True
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh) == {"a": 1, "b": [2, 3]}


def test_atomic_write_json_creates_dir(tmp_path):
    path = str(tmp_path / "new" / "deep" / "out.json")
    assert atomic_write_json(path, {"x": 1}) is True
    assert os.path.exists(path)


def test_atomic_write_json_no_tmp_left(tmp_path):
    path = str(tmp_path / "out.json")
    atomic_write_json(path, {"x": 2})
    files = list(tmp_path.iterdir())
    assert all(not f.name.endswith(".tmp") for f in files), "不应残留 .tmp 文件"


def test_atomic_write_json_overwrites(tmp_path):
    path = str(tmp_path / "out.json")
    atomic_write_json(path, {"v": 1})
    atomic_write_json(path, {"v": 2})
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh) == {"v": 2}


def test_atomic_write_json_returns_false_on_bad_path():
    # 不可写路径：makedirs 失败 → 返回 False（不影响调用方）
    assert atomic_write_json("/nonexistent-root-no-perm/sub/out.json", {"x": 1}) is False


def test_atomic_write_json_handles_unicode(tmp_path):
    path = str(tmp_path / "out.json")
    payload = {"name": "贵州茅台", "code": "600519", "备注": "涨停"}
    assert atomic_write_json(path, payload) is True
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh) == payload


# ===== P4-T1b：trade_calendar 4 函数 + 依赖（is_a_share_closed / latest_closed_session）=====


def test_is_a_share_closed_after_1505(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    assert is_a_share_closed() is True


def test_is_a_share_closed_at_close(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 5))
    assert is_a_share_closed() is True  # 15:05 边界含


def test_is_a_share_closed_intraday(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 14, 0))
    assert is_a_share_closed() is False


def test_latest_closed_session_trading_day_after_close(monkeypatch):
    # 2026-03-10 周二（非节假日）+ 15:06 收盘后 → 今天
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    assert latest_closed_session() == "2026-03-10"


def test_latest_closed_session_trading_day_intraday(monkeypatch):
    # 2026-03-10 周二 + 14:00 盘中（未收盘）→ 上一交易日 2026-03-09 周一
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 14, 0))
    assert latest_closed_session() == "2026-03-09"


def test_latest_closed_session_weekend(monkeypatch):
    # 2026-03-14 周六 15:06 → 上一交易日 2026-03-13 周五
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 14, 15, 6))
    assert latest_closed_session() == "2026-03-13"


def test_latest_closed_session_holiday(monkeypatch):
    # 2026-10-01 国庆节假日（在 _A_SHARE_HOLIDAYS）→ 上一交易日 2026-09-30 周三
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 10, 1, 15, 6))
    assert latest_closed_session() == "2026-09-30"


def test_is_settled_past_date(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    assert is_settled("2026-03-08") is True


def test_is_settled_today_after_close(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    assert is_settled("2026-03-10") is True


def test_is_settled_today_intraday(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 14, 0))
    assert is_settled("2026-03-10") is False  # 今天盘中未定稿


def test_is_settled_future_date(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    assert is_settled("2026-03-15") is False  # 未来


def test_trade_dates_ending_at_5(monkeypatch):
    # 2026-03-10 周二收盘后，ending 3-10 取 5 个交易日（升序）
    # 3-10(二),3-09(一),3-06(五),3-05(四),3-04(三) → 升序 [3-04,3-05,3-06,3-09,3-10]
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    assert trade_dates_ending_at("2026-03-10", 5) == [
        "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-09", "2026-03-10",
    ]


def test_trade_dates_ending_at_excludes_unsettled_today(monkeypatch):
    # 今天 3-10 盘中（未收盘）→ 3-10 不算
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 14, 0))
    dates = trade_dates_ending_at("2026-03-10", 3)
    assert "2026-03-10" not in dates
    assert dates == ["2026-03-06", "2026-03-09"]


def test_trade_dates_ending_at_weekend_end(monkeypatch):
    # end 2026-03-14 周六 → 不含 3-14，取 ending 最近 3 个交易日 3-11/3-12/3-13
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 14, 15, 6))
    assert trade_dates_ending_at("2026-03-14", 3) == [
        "2026-03-11", "2026-03-12", "2026-03-13",
    ]


def test_trade_dates_ending_at_across_holiday(monkeypatch):
    # 跨国庆：end 2026-10-08（国庆后首个交易日）取 3 个 → 10-08,10-09?,...
    # 2026-10-08 周四，10-07/10-06/10-05/10-02/10-01 节假日，10-09 周五,10-08 周四
    # 前一交易日：10-08→9-30（10-01~10-08 节假日，9-30 周三）...
    # 3 个 ending 10-08: 10-08, 9-30, 9-29
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 10, 8, 15, 6))
    dates = trade_dates_ending_at("2026-10-08", 3)
    assert dates == ["2026-09-28", "2026-09-29", "2026-09-30"]


def test_live_quotes_are_close_of_non_recent(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    ok, reason = live_quotes_are_close_of("2026-03-08")
    assert ok is False
    assert "非最近" in reason


def test_live_quotes_are_close_of_recent_match(monkeypatch):
    # 3-10 是 latest_closed_session，mock quote_trade_day 返回 3-10 + 收盘后 → ok
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    monkeypatch.setattr(u, "quote_trade_day", lambda: "2026-03-10")
    ok, _ = live_quotes_are_close_of("2026-03-10")
    assert ok is True


def test_live_quotes_are_close_of_recent_mismatch(monkeypatch):
    # 行情属于 3-11，问 3-10 → 不匹配
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    monkeypatch.setattr(u, "quote_trade_day", lambda: "2026-03-11")
    ok, reason = live_quotes_are_close_of("2026-03-10")
    assert ok is False
    assert "2026-03-11" in reason


def test_live_quotes_are_close_of_quote_fail(monkeypatch):
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 15, 6))
    monkeypatch.setattr(u, "quote_trade_day", lambda: None)
    ok, reason = live_quotes_are_close_of("2026-03-10")
    assert ok is False
    assert "判不出" in reason


def test_live_quotes_are_close_of_today_intraday(monkeypatch):
    # 3-10 盘中，quote_trade_day 返回今天 3-10（盘中场次），问 3-09 → 行情属于 3-10 不匹配
    monkeypatch.setattr(u, "china_now", lambda: _mock_now(2026, 3, 10, 14, 0))
    monkeypatch.setattr(u, "quote_trade_day", lambda: "2026-03-10")
    ok, reason = live_quotes_are_close_of("2026-03-09")
    assert ok is False
    assert "2026-03-10" in reason


@pytest.mark.live
def test_quote_trade_day_live():
    """真网络测 quote_trade_day（live 标记，离线 pytest -m 'not live' 不跑）。"""
    u._quote_day_cache.clear()
    result = u.quote_trade_day()
    assert result is None or (isinstance(result, str) and len(result) == 10)
