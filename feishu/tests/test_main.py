# -*- coding: utf-8 -*-
"""test_main.py — main() 函数 + argparse + BUILDERS dict 测试。

测试覆盖：
- BUILDERS dict 包含所有 mode 且值为 callable
- test 模式跳过交易日判断（直接构建卡片）
- 非交易日跳过推送（print 跳过消息 + return）
- --force 强制推送（跳过交易日判断）
- 交易日正常推送
- send_feishu 成功/失败路径
- 未知 mode（argparse choices 拦截）

mock is_trading_day / send_feishu / 各 builder，不触碰真实网络/日历。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from feishu import main as main_mod
from feishu.main import BUILDERS, main


CST = timezone(timedelta(hours=8))


# ─── BUILDERS dict ───

def test_builders_contains_all_modes():
    """BUILDERS dict 包含所有 7 个 mode。"""
    expected_modes = {"premarket", "intraday", "postmarket", "alert", "scan", "sentiment", "test"}
    assert set(BUILDERS.keys()) == expected_modes


def test_builders_all_callable():
    """所有 builder 值都是 callable。"""
    for mode, builder in BUILDERS.items():
        assert callable(builder), f"{mode} 的 builder 不是 callable"


def test_builders_test_points_to_build_test_card():
    """test mode → build_test_card。"""
    from feishu.cards import build_test_card
    assert BUILDERS["test"] is build_test_card


def test_builders_premarket_points_to_build_premarket_card():
    """premarket mode → build_premarket_card。"""
    from feishu.cards import build_premarket_card
    assert BUILDERS["premarket"] is build_premarket_card


# ─── main() test 模式（跳过交易日判断）───

def test_main_test_mode_skips_trading_day(monkeypatch, capsys):
    """test 模式不受交易日限制——即使非交易日也推送。"""
    # mock is_trading_day 返回 False（模拟非交易日）
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: False)
    # mock send_feishu 成功
    send_mock = MagicMock(return_value=True)
    monkeypatch.setattr(main_mod, "send_feishu", send_mock)
    # mock test builder
    monkeypatch.setattr(main_mod, "BUILDERS", {"test": lambda: {"header": {}, "elements": []}})

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "test"])
    main()

    # 验证 send_feishu 被调用（test 模式跳过了交易日判断）
    send_mock.assert_called_once()


def test_main_test_mode_on_non_trading_day(monkeypatch, capsys):
    """test 模式在非交易日仍推送（is_trading_day 不应被调用）。"""
    is_trading_mock = MagicMock(return_value=False)
    monkeypatch.setattr(main_mod, "is_trading_day", is_trading_mock)
    monkeypatch.setattr(main_mod, "send_feishu", MagicMock(return_value=True))
    monkeypatch.setattr(main_mod, "BUILDERS", {"test": lambda: {}})

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "test"])
    main()

    # test 模式不应检查 is_trading_day
    is_trading_mock.assert_not_called()


# ─── main() 非交易日跳过 ───

def test_main_non_trading_day_skips(monkeypatch, caplog):
    """非交易日 + 非 test 模式 + 无 --force → 跳过推送。"""
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: False)
    send_mock = MagicMock(return_value=True)
    monkeypatch.setattr(main_mod, "send_feishu", send_mock)

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "premarket"])
    with caplog.at_level("INFO"):
        main()

    # send_feishu 不应被调用
    send_mock.assert_not_called()
    assert "非交易日" in caplog.text or "跳过" in caplog.text


def test_main_non_trading_day_prints_weekday(monkeypatch, caplog):
    """跳过消息含日期和星期。"""
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: False)
    monkeypatch.setattr(main_mod, "send_feishu", MagicMock())

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "premarket"])
    with caplog.at_level("INFO"):
        main()

    # 应含日期格式 YYYY-MM-DD 和周X
    assert "周" in caplog.text


# ─── main() --force 强制推送 ───

def test_main_force_overrides_non_trading_day(monkeypatch, caplog):
    """--force 在非交易日仍推送。"""
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: False)
    send_mock = MagicMock(return_value=True)
    monkeypatch.setattr(main_mod, "send_feishu", send_mock)
    monkeypatch.setattr(main_mod, "BUILDERS", {"premarket": lambda: {}})

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "premarket", "--force"])
    with caplog.at_level("INFO"):
        main()

    send_mock.assert_called_once()
    assert "推送成功" in caplog.text


# ─── main() 交易日正常推送 ───

def test_main_trading_day_normal_push(monkeypatch, caplog):
    """交易日 + 正常 mode → 推送。"""
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: True)
    send_mock = MagicMock(return_value=True)
    monkeypatch.setattr(main_mod, "send_feishu", send_mock)
    monkeypatch.setattr(main_mod, "BUILDERS", {"premarket": lambda: {"header": {}, "elements": []}})

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "premarket"])
    with caplog.at_level("INFO"):
        main()

    send_mock.assert_called_once()
    assert "推送成功" in caplog.text
    assert "premarket" in caplog.text


# ─── main() send_feishu 失败 ───

def test_main_send_fail_exits_nonzero(monkeypatch, caplog):
    """send_feishu 返回 False → log 失败 + sys.exit(1)。"""
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: True)
    monkeypatch.setattr(main_mod, "send_feishu", MagicMock(return_value=False))
    monkeypatch.setattr(main_mod, "BUILDERS", {"premarket": lambda: {}})

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "premarket"])
    with caplog.at_level("ERROR"):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
    assert "推送失败" in caplog.text


def test_main_send_success_no_exit(monkeypatch, caplog):
    """send_feishu 返回 True → 不 exit。"""
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: True)
    monkeypatch.setattr(main_mod, "send_feishu", MagicMock(return_value=True))
    monkeypatch.setattr(main_mod, "BUILDERS", {"premarket": lambda: {}})

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "premarket"])
    with caplog.at_level("INFO"):
        main()  # 不抛 SystemExit
    assert "推送成功" in caplog.text


# ─── main() 传 mode 给 send_feishu ───

def test_main_passes_mode_to_send_feishu(monkeypatch):
    """send_feishu 被调用时 mode 参数正确。"""
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: True)
    send_mock = MagicMock(return_value=True)
    monkeypatch.setattr(main_mod, "send_feishu", send_mock)
    monkeypatch.setattr(main_mod, "BUILDERS", {"sentiment": lambda: {}})

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "sentiment"])
    main()

    # send_feishu(card, mode="sentiment")
    call_kwargs = send_mock.call_args
    assert call_kwargs.kwargs.get("mode") == "sentiment" or \
           (len(call_kwargs.args) >= 2 and call_kwargs.args[1] == "sentiment")


# ─── main() argparse 校验 ───

def test_main_invalid_mode_exits(monkeypatch):
    """无效 mode → argparse 报错退出（SystemExit）。"""
    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "invalid_mode"])
    with pytest.raises(SystemExit):
        main()


def test_main_missing_mode_arg_exits(monkeypatch):
    """缺 --mode 参数 → argparse 报错退出。"""
    monkeypatch.setattr(sys, "argv", ["feishu.main"])
    with pytest.raises(SystemExit):
        main()


# ─── main() 各 mode 调度正确 builder ───

def test_main_dispatches_correct_builder(monkeypatch):
    """验证每个 mode 调度到正确的 builder 函数。"""
    called = {}
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: True)
    monkeypatch.setattr(main_mod, "send_feishu", MagicMock(return_value=True))

    # 为每个 mode 注入一个记录调用的 mock builder
    mock_builders = {}
    for mode in ["premarket", "intraday", "postmarket", "alert", "scan", "sentiment", "test"]:
        def _make_builder(m):
            def _b():
                called[m] = True
                return {}
            return _b
        mock_builders[mode] = _make_builder(mode)
    monkeypatch.setattr(main_mod, "BUILDERS", mock_builders)

    for mode in ["premarket", "intraday", "postmarket", "alert", "scan", "sentiment", "test"]:
        called.clear()
        monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", mode])
        main()
        assert called.get(mode) is True, f"mode={mode} 未调度到对应 builder"


# ─── main() 卡片传递给 send_feishu ───

def test_main_card_passed_to_send_feishu(monkeypatch):
    """builder 返回的 card 被传给 send_feishu。"""
    test_card = {"header": {"title": "test"}, "elements": []}
    monkeypatch.setattr(main_mod, "is_trading_day", lambda dt: True)
    send_mock = MagicMock(return_value=True)
    monkeypatch.setattr(main_mod, "send_feishu", send_mock)
    monkeypatch.setattr(main_mod, "BUILDERS", {"premarket": lambda: test_card})

    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "premarket"])
    main()

    sent_card = send_mock.call_args.args[0]
    assert sent_card is test_card


# ─── main() 交易日判断用 CST 时区 ───

def test_main_uses_cst_timezone(monkeypatch):
    """is_trading_day 接收的 datetime 是 CST 时区。"""
    captured_dt = {}
    monkeypatch.setattr(main_mod, "send_feishu", MagicMock(return_value=True))
    monkeypatch.setattr(main_mod, "BUILDERS", {"premarket": lambda: {}})

    def _capture_is_trading(dt):
        captured_dt["dt"] = dt
        return True

    monkeypatch.setattr(main_mod, "is_trading_day", _capture_is_trading)
    monkeypatch.setattr(sys, "argv", ["feishu.main", "--mode", "premarket"])
    main()

    dt = captured_dt["dt"]
    assert dt.tzinfo is not None  # 有时区信息
    # CST = UTC+8
    assert dt.utcoffset() == timedelta(hours=8)
