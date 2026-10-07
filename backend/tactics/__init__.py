# -*- coding: utf-8 -*-
"""backend.tactics —— 反量化短线战法集成包（S235）。

三战法（反核 / 尾盘突破 / 冰点反抽）+ 反量化拦截网关 + 信号落库 + 实盘记录。

⚠️ 探索性框架，未经 Bootstrap 统计验证：
- 所有阈值来自社区经验或本会话推演，非数据回测（spec §2.3 标注来源）
- 信号即落库（含未成交 + 随机对照），n≥60 才出 verdict
- ≤3% 资金跟踪，单票≤1%

设计见 specs/S235-anti-quant-tactics/spec.md（草案v2，Oracle grill 复审通过）。
"""
