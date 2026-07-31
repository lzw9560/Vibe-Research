# -*- coding: utf-8 -*-
"""S008 数据源包 —— 按数据源拆分 astock 取数逻辑。

每个源模块暴露 ``fetch_raw(...)``（或同名取数函数）返**原始 dict**（单一事实源，
全字段，不丢）。两条投影从 raw 直接派生，不互相往返（数据总线 + 异构接口，无状态纯 dispatch）：

- **legacy 投影**：``astock.<fn>`` 直接返 raw —— 28 个旧消费者不改（全字段，零丢失）。
- **model 投影**：``data.mappers.<src>_from_dict(raw) -> S007 模型`` —— 新消费者（后续轮按 A/B/C 组迁）。

设计详见 ``specs/S008-后端数据层迁移/plan-stage1.md``。
"""
