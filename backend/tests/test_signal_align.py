# -*- coding: utf-8 -*-
"""S194 R1 · signal_align 单测——异质信号对齐到 D 日 + 标准化 + 边界 case。

纯函数 align_signals 输入 signal dict 列表 + target_date（D 日），输出标准化 5 字段
dict 列表 {signal_name, value, confidence, timestamp, source}，timestamp 统一锚到 D 日。

输入 signal dict 由各信号源适配器抽取（gap→regime / ofi row→ofi / breakout→score 等），
本函数只做校验 + 填默认 + 时间戳对齐 + 5 字段投影，不耦合具体信号源（YAGNI）。
"""
from __future__ import annotations

from engine.signal_align import align_signals


def _sig(signal_name: str, value, *, confidence=None, timestamp=None, source=None) -> dict:
    """构造测试 signal dict（模拟信号源适配器已抽取的标准化输入）。

    只塞非 None 字段，测「缺字段→填默认」逻辑。
    """
    d: dict = {"signal_name": signal_name, "value": value}
    if confidence is not None:
        d["confidence"] = confidence
    if timestamp is not None:
        d["timestamp"] = timestamp
    if source is not None:
        d["source"] = source
    return d


class TestAlignTimestamps:
    def test_daily_signal_already_on_d(self):
        """日级信号（gap, D 日）timestamp 已是 D 日 → 锚定 D 日。"""
        signals = [_sig("gap", "趋势启动", confidence=0.7, timestamp="2026-09-13")]
        out = align_signals(signals, "2026-09-13")
        assert len(out) == 1
        assert out[0]["timestamp"] == "2026-09-13"
        assert out[0]["signal_name"] == "gap"

    def test_intraday_signal_anchored_to_d(self):
        """盘中信号（OFI, D 日 09:31）timestamp 含时间 → 取日期部分锚到 D 日。"""
        signals = [_sig("ofi", 0.45, confidence=0.45, timestamp="2026-09-13T09:31:00")]
        out = align_signals(signals, "2026-09-13")
        assert out[0]["timestamp"] == "2026-09-13"

    def test_t1_signal_anchored_to_d(self):
        """T-1 信号（breakout 选股, D-1 收盘后算）timestamp=D-1 → 锚到 D 日。"""
        signals = [_sig("breakout", 0.95, confidence=0.95, timestamp="2026-09-12")]
        out = align_signals(signals, "2026-09-13")
        assert out[0]["timestamp"] == "2026-09-13"

    def test_mixed_time_scales_all_anchored_to_d(self):
        """4+ 异质信号（日级/盘中/T-1 混合）全部锚到 D 日——spec A1 验收。"""
        signals = [
            _sig("gap", "趋势启动", confidence=0.7, timestamp="2026-09-13"),           # 日级 D
            _sig("ofi", 0.45, confidence=0.45, timestamp="2026-09-13T09:31:00"),        # 盘中 D
            _sig("breakout", 0.95, confidence=0.95, timestamp="2026-09-12"),            # T-1
            _sig("fund_flow", 48400.0, confidence=0.8, timestamp="2026-09-12"),        # T-1
            _sig("trend_arm", 1.65, confidence=0.3, timestamp="2026-09-12"),            # T-1
        ]
        out = align_signals(signals, "2026-09-13")
        assert len(out) == 5
        assert all(s["timestamp"] == "2026-09-13" for s in out)  # 全锚到 D 日


class TestStandardizeFormat:
    def test_output_has_exactly_5_fields_drops_extras(self):
        """输出严格 5 字段；输入的 extra 字段（如 gap params）被丢弃。"""
        signals = [{
            "signal_name": "gap", "value": "趋势启动", "confidence": 0.7,
            "timestamp": "2026-09-13", "source": "S193",
            "params": {"量比": 3.0, "回补状态": "3日不回补"},  # extra 应丢
        }]
        out = align_signals(signals, "2026-09-13")
        assert set(out[0].keys()) == {"signal_name", "value", "confidence", "timestamp", "source"}

    def test_defaults_filled_when_missing(self):
        """缺 confidence/source/timestamp → 填默认（1.0 / =signal_name / =target_date）。"""
        signals = [_sig("gap", "趋势启动")]  # 只给 signal_name + value
        out = align_signals(signals, "2026-09-13")
        assert out[0]["confidence"] == 1.0
        assert out[0]["source"] == "gap"
        assert out[0]["timestamp"] == "2026-09-13"

    def test_mixed_value_types_preserved(self):
        """异质 value 类型（gap regime 字符串 / ofi float）不强转，保留原值。"""
        signals = [
            _sig("gap", "趋势启动", timestamp="2026-09-13"),      # str
            _sig("ofi", 0.45, timestamp="2026-09-13T09:31:00"),   # float
        ]
        out = align_signals(signals, "2026-09-13")
        assert out[0]["value"] == "趋势启动"
        assert out[1]["value"] == 0.45


class TestEdgeCases:
    def test_skip_signal_without_signal_name(self):
        """缺 signal_name 的信号 → 跳过。"""
        signals = [{"value": "x"}, _sig("gap", "趋势启动", timestamp="2026-09-13")]
        out = align_signals(signals, "2026-09-13")
        assert len(out) == 1

    def test_skip_signal_without_value(self):
        """缺 value 的信号 → 跳过。"""
        signals = [{"signal_name": "gap"}, _sig("ofi", 0.45, timestamp="2026-09-13")]
        out = align_signals(signals, "2026-09-13")
        assert len(out) == 1

    def test_skip_none_value(self):
        """value=None（信号源取数失败，如 northbound post-2024-08 停更）→ 跳过不臆造。"""
        signals = [
            _sig("northbound", None, timestamp="2026-09-13"),
            _sig("gap", "趋势启动", timestamp="2026-09-13"),
        ]
        out = align_signals(signals, "2026-09-13")
        assert len(out) == 1

    def test_empty_signals_returns_empty(self):
        """空信号列表 → 返空。"""
        assert align_signals([], "2026-09-13") == []

    def test_invalid_timestamp_falls_back_to_target(self):
        """timestamp 格式无法解析 → 兜底用 target_date（不炸）。"""
        signals = [_sig("gap", "趋势启动", timestamp="not-a-date")]
        out = align_signals(signals, "2026-09-13")
        assert out[0]["timestamp"] == "2026-09-13"

    def test_input_not_mutated(self):
        """输入 signal dict 不被就地改（immutability 约束）。"""
        original = _sig("gap", "趋势启动", timestamp="2026-09-12")  # T-1
        original_snapshot = dict(original)
        align_signals([original], "2026-09-13")
        assert original == original_snapshot  # 输入不变
