# -*- coding: utf-8 -*-
"""S194 R1 · 信号对齐层——把异质信号锚到 D 日统一时间戳，标准化成 5 字段 dict。

纯函数 align_signals：输入各信号源适配器已抽取的 signal dict 列表（每条至少含
{signal_name, value}，可选 confidence/timestamp/source），输出严格 5 字段
{signal_name, value, confidence, timestamp, source}，timestamp 全部锚到 D 日。

时间尺度对齐规则（spec R1）：
- 日级信号（gap, D 日）timestamp 已是 D → 锚到 D；
- 盘中信号（OFI, D 日 HH:MM）取日期部分 → 锚到 D；
- T-1 信号（breakout/fund_flow/trend, D-1 收盘后算）→ 锚到 D（昨日 conditioning 用于今日决策）。

统一锚定 = 所有信号 output timestamp=target_date（D 日）。原始时间戳丢弃（5 字段格式无
source_timestamp 槽；traceability 后续按需再加，YAGNI）。value 类型不统一（gap regime
字符串 / OFI·breakout·资金流 float）——不强转，保留原值，由下游 fusion 层按 signal_name
分派解释。confidence 缺省 1.0，source 缺省 = signal_name。value=None（取数失败，如
northbound post-2024-08 停更）跳过不臆造（§1.2 工程底线「不臆造数据」）。

per-source 适配器（gap→regime / ofi row→ofi / breakout→score / fund_flow→main_net_5d /
trend→strategy_score）在调用方或后续 adapter 模块，本函数只做校验 + 填默认 + 时间戳对齐 +
5 字段投影，不耦合具体信号源（YAGNI + 开闭原则）。
"""
from __future__ import annotations

# 标准化输出字段（严格 5 字段，extra 字段如 gap params 被丢弃）
_STAGED_FIELDS: tuple[str, ...] = ("signal_name", "value", "confidence", "timestamp", "source")


def align_signals(signals: list[dict], target_date: str) -> list[dict]:
    """把异质信号锚到 D 日统一时间戳，标准化成 {signal_name, value, confidence, timestamp, source}。

    Args:
        signals: 各信号源适配器已抽取的 signal dict 列表，每条至少含 {signal_name, value}，
                 可选 confidence/timestamp/source（及 extra 字段如 params，会被丢弃）。
        target_date: D 日（YYYY-MM-DD），所有信号锚到此日。

    Returns:
        标准化 dict 列表，严格 5 字段，timestamp=target_date。缺 signal_name 或 value=None
        的信号跳过（不臆造）。不就地改输入（每条产新 dict）。
    """
    aligned: list[dict] = []
    for s in signals:
        name = s.get("signal_name")
        value = s.get("value")
        if not name or value is None:  # 缺 signal_name 或 value=None → 跳过（不臆造）
            continue
        aligned.append({
            "signal_name": name,
            "value": value,
            "confidence": s.get("confidence", 1.0),
            "timestamp": target_date,  # 统一锚到 D 日（日级/盘中/T-1 全部 target_date）
            "source": s.get("source", name),  # 缺省 = signal_name
        })
    return aligned
