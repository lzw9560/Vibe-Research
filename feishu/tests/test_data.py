# -*- coding: utf-8 -*-
"""test_data.py — run_cli 异常处理 + 数据获取函数降级测试。

测试覆盖：
- run_cli 正常路径（返回 JSON dict）
- run_cli 超时（subprocess.TimeoutExpired）→ None + warning
- run_cli JSON 解析失败 → None + warning
- run_cli 非零退出码 → None + warning
- run_cli 无可解析 JSON 行 → None + warning
- run_cli 其他异常（OSError 等）→ None + warning
- get_index_snapshot / get_hot_stocks 空数据降级（返回 []）
- get_dragon_tiger / get_limit_up_ladder / get_skyrocket 空数据降级

mock subprocess.run，不触碰真实 hithink-finance CLI。
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from feishu import data


# ─── 辅助：构造 subprocess.CompletedProcess ───

def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args="cmd", returncode=returncode, stdout=stdout, stderr=stderr
    )


# ─── run_cli 正常路径 ───

def test_run_cli_normal_json(monkeypatch):
    """正常 JSON 输出 → 返回解析后的 dict。"""
    payload = {"ok": True, "data": {"item": [{"thscode": "000001.SH"}]}}
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(stdout=json.dumps(payload))),
    )
    result = data.run_cli("hithink-finance index snapshot")
    assert result == payload
    assert result["ok"] is True


def test_run_cli_json_with_stderr_mix(monkeypatch):
    """stdout 末行是 JSON（前面混入 stderr 提示行）→ 取最后一行 JSON。"""
    stdout = 'loading...\nwarn: deprecated\n{"ok": true}'
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(stdout=stdout)),
    )
    result = data.run_cli("cmd")
    assert result == {"ok": True}


def test_run_cli_json_not_first_line(monkeypatch):
    """多行输出，取最后一个以 { 开头的行。"""
    stdout = '{"first": true}\nsome log\n{"second": true}'
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(stdout=stdout)),
    )
    result = data.run_cli("cmd")
    assert result == {"second": True}


# ─── run_cli 异常路径 ───

def test_run_cli_timeout(monkeypatch):
    """subprocess.TimeoutExpired → None + warning 日志。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd="cmd", timeout=30)),
    )
    result = data.run_cli("hithink-finance slow-cmd")
    assert result is None


def test_run_cli_nonzero_exit(monkeypatch):
    """非零退出码 → None + warning 日志（含 stderr 末行）。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(
            stdout='{"ok": false}', stderr="error: token invalid", returncode=1
        )),
    )
    result = data.run_cli("hithink-finance cmd")
    assert result is None


def test_run_cli_nonzero_exit_empty_stderr(monkeypatch):
    """非零退出码 + 空 stderr → None（不崩溃）。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(stdout="", stderr="", returncode=2)),
    )
    result = data.run_cli("cmd")
    assert result is None


def test_run_cli_json_decode_fail(monkeypatch):
    """stdout 以 { 开头但 JSON 非法 → None + warning。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(stdout='{invalid json}')),
    )
    result = data.run_cli("cmd")
    assert result is None


def test_run_cli_no_json_line(monkeypatch):
    """stdout 无以 { 开头的行 → None + warning。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(stdout="plain text\nno json here")),
    )
    result = data.run_cli("cmd")
    assert result is None


def test_run_cli_empty_stdout(monkeypatch):
    """stdout 为空 → None。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(stdout="")),
    )
    result = data.run_cli("cmd")
    assert result is None


def test_run_cli_generic_exception(monkeypatch):
    """其他异常（如 OSError）→ None + warning（不抛出）。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(side_effect=OSError("permission denied")),
    )
    result = data.run_cli("cmd")
    assert result is None


# ─── run_cli 日志验证 ───

def test_run_cli_timeout_logs_warning(monkeypatch, caplog):
    """超时时记 warning 日志，便于诊断。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd="cmd", timeout=30)),
    )
    with caplog.at_level("WARNING", logger="feishu.data"):
        data.run_cli("hithink-finance cmd")
    assert any("超时" in r.message for r in caplog.records)


def test_run_cli_nonzero_logs_returncode(monkeypatch, caplog):
    """非零退出码时日志含 returncode。"""
    monkeypatch.setattr(
        data.subprocess, "run",
        MagicMock(return_value=_completed(stderr="err", returncode=42)),
    )
    with caplog.at_level("WARNING", logger="feishu.data"):
        data.run_cli("cmd")
    assert any("42" in r.message for r in caplog.records)


# ─── get_index_snapshot 降级 ───

def test_get_index_snapshot_normal(monkeypatch):
    """正常数据 → 返回 item 列表。"""
    payload = {"ok": True, "data": {"item": [{"thscode": "000001.SH", "last_price": 3300}]}}
    monkeypatch.setattr(data, "run_cli", lambda cmd: payload)
    result = data.get_index_snapshot()
    assert len(result) == 1
    assert result[0]["thscode"] == "000001.SH"


def test_get_index_snapshot_none_result(monkeypatch):
    """run_cli 返回 None → 降级返回 []。"""
    monkeypatch.setattr(data, "run_cli", lambda cmd: None)
    assert data.get_index_snapshot() == []


def test_get_index_snapshot_ok_false(monkeypatch):
    """返回 ok=False → 降级返回 []。"""
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": False})
    assert data.get_index_snapshot() == []


def test_get_index_snapshot_missing_data(monkeypatch):
    """返回 ok=True 但无 data 键 → 降级返回 []。"""
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True})
    assert data.get_index_snapshot() == []


def test_get_index_snapshot_empty_item(monkeypatch):
    """data.item 为空列表 → 返回 []。"""
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"item": []}})
    assert data.get_index_snapshot() == []


# ─── get_hot_stocks 降级 ───

def test_get_hot_stocks_normal(monkeypatch):
    """正常数据 → 返回前 20 条。"""
    items = [{"rank": i, "name": f"stock{i}"} for i in range(25)]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"item": items}})
    result = data.get_hot_stocks()
    assert len(result) == 20  # 截断到 20


def test_get_hot_stocks_none(monkeypatch):
    """run_cli 返回 None → []。"""
    monkeypatch.setattr(data, "run_cli", lambda cmd: None)
    assert data.get_hot_stocks() == []


def test_get_hot_stocks_ok_false(monkeypatch):
    """ok=False → []。"""
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": False})
    assert data.get_hot_stocks() == []


# ─── get_dragon_tiger 降级 ───

def test_get_dragon_tiger_normal(monkeypatch):
    """正常数据 → 按 net_value 降序取前 15。"""
    items = [
        {"name": "A", "net_value": 1e8},
        {"name": "B", "net_value": 5e8},
        {"name": "C", "net_value": 3e8},
    ]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"stock_items": items}})
    result = data.get_dragon_tiger()
    assert len(result) == 3
    assert result[0]["name"] == "B"  # net_value 最大排第一
    assert result[1]["name"] == "C"
    assert result[2]["name"] == "A"


def test_get_dragon_tiger_none(monkeypatch):
    """run_cli None → []。"""
    monkeypatch.setattr(data, "run_cli", lambda cmd: None)
    assert data.get_dragon_tiger() == []


def test_get_dragon_tiger_none_net_value(monkeypatch):
    """net_value 为 None 的项不崩溃（sort key 用 0 兜底）。"""
    items = [{"name": "A", "net_value": None}, {"name": "B"}]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"stock_items": items}})
    result = data.get_dragon_tiger()
    assert len(result) == 2


def test_get_dragon_tiger_truncate_15(monkeypatch):
    """超过 15 条 → 截断到 15。"""
    items = [{"name": f"S{i}", "net_value": i * 1e8} for i in range(20)]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"stock_items": items}})
    result = data.get_dragon_tiger()
    assert len(result) == 15


# ─── get_limit_up_ladder / get_skyrocket 降级 ───

def test_get_limit_up_ladder_normal(monkeypatch):
    """正常 → 取前 3。"""
    items = [{"boards": {}} for _ in range(5)]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"item": items}})
    assert len(data.get_limit_up_ladder()) == 3


def test_get_limit_up_ladder_none(monkeypatch):
    monkeypatch.setattr(data, "run_cli", lambda cmd: None)
    assert data.get_limit_up_ladder() == []


def test_get_skyrocket_normal(monkeypatch):
    """正常 → 取前 10。"""
    items = [{"name": f"S{i}"} for i in range(15)]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"item": items}})
    assert len(data.get_skyrocket()) == 10


def test_get_skyrocket_none(monkeypatch):
    monkeypatch.setattr(data, "run_cli", lambda cmd: None)
    assert data.get_skyrocket() == []


# ─── get_realtime_price ───

def test_get_realtime_price_normal(monkeypatch):
    """正常 → 返回 {thscode: item} dict。"""
    items = [{"thscode": "600001.SH", "last_price": 10.5}, {"thscode": "600002.SH", "last_price": 20}]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"item": items}})
    result = data.get_realtime_price(["600001.SH", "600002.SH"])
    assert "600001.SH" in result
    assert result["600001.SH"]["last_price"] == 10.5


def test_get_realtime_price_none(monkeypatch):
    monkeypatch.setattr(data, "run_cli", lambda cmd: None)
    assert data.get_realtime_price(["600001.SH"]) == {}


# ─── calc_ma5 ───

def test_calc_ma5_normal():
    """>=5 条 K 线 → 返回 5 日均价。"""
    klines = [{"close_price": 10}, {"close_price": 11}, {"close_price": 12}, {"close_price": 13}, {"close_price": 14}]
    assert data.calc_ma5(klines) == 12.0  # (10+11+12+13+14)/5


def test_calc_ma5_insufficient():
    """<5 条 → None。"""
    assert data.calc_ma5([{"close_price": 10}]) is None


def test_calc_ma5_empty():
    """空列表 → None。"""
    assert data.calc_ma5([]) is None


def test_calc_ma5_more_than_5():
    """>5 条 → 取最后 5 条。"""
    klines = [{"close_price": 1}, {"close_price": 2}, {"close_price": 3}, {"close_price": 4},
              {"close_price": 5}, {"close_price": 6}, {"close_price": 7}]
    assert data.calc_ma5(klines) == 5.0  # (3+4+5+6+7)/5


# ─── scan_group_a_stocks 降级 ───

def test_scan_group_a_stocks_none(monkeypatch):
    """run_cli None → []。"""
    monkeypatch.setattr(data, "run_cli", lambda cmd: None)
    assert data.scan_group_a_stocks() == []


def test_scan_group_a_stocks_filter(monkeypatch):
    """验证 A 组筛选逻辑：净买入>0 + 涨幅-3%~10% + 净买<0.5亿 + 热度>100。"""
    items = [
        # 符合 A 组：涨幅5% + 净买0.3亿 + 热度200 + 净买入正
        {"thscode": "600001.SH", "name": "A组标的", "net_value": 3e7, "change": 0.05,
         "hot_rank": 200, "concept_list": []},
        # 不符合：净买入为负
        {"thscode": "600002.SH", "name": "净买负", "net_value": -1e7, "change": 0.03,
         "hot_rank": 200, "concept_list": []},
        # 不符合：涨幅过大（>10%）
        {"thscode": "600003.SH", "name": "涨幅过大", "net_value": 3e7, "change": 0.15,
         "hot_rank": 200, "concept_list": []},
        # 不符合：净买过大（>=0.5亿）
        {"thscode": "600004.SH", "name": "净买过大", "net_value": 6e7, "change": 0.05,
         "hot_rank": 200, "concept_list": []},
    ]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"stock_items": items}})
    result = data.scan_group_a_stocks()
    assert len(result) == 1
    assert result[0]["code"] == "600001.SH"


def test_scan_group_a_stocks_truncate_5(monkeypatch):
    """超过 5 条 → 截断到 5。"""
    # net_yi = net_value/1e8，需 < 0.5 亿 → net_value < 5e7
    # 用 (8-i)*4e6 → 0.32/0.28/0.24/0.20/0.16/0.12/0.08/0.04 亿，均 < 0.5
    items = [
        {"thscode": f"60000{i}.SH", "name": f"S{i}", "net_value": (8 - i) * 4e6,
         "change": 0.05, "hot_rank": 200, "concept_list": []}
        for i in range(8)
    ]
    monkeypatch.setattr(data, "run_cli", lambda cmd: {"ok": True, "data": {"stock_items": items}})
    result = data.scan_group_a_stocks()
    assert len(result) == 5


# ─── get_watch_list ───

def test_get_watch_list_uses_scan(monkeypatch):
    """WATCH_LIST 为空时调 scan_group_a_stocks。"""
    monkeypatch.setattr(data, "WATCH_LIST", [])
    monkeypatch.setattr(data, "scan_group_a_stocks", lambda: [{"code": "600001.SH"}])
    result = data.get_watch_list()
    assert len(result) == 1


def test_get_watch_list_returns_cached(monkeypatch):
    """WATCH_LIST 非空时直接返回（不调 scan）。"""
    cached = [{"code": "cached.SH"}]
    monkeypatch.setattr(data, "WATCH_LIST", cached)
    monkeypatch.setattr(data, "scan_group_a_stocks", lambda: [])
    assert data.get_watch_list() == cached
