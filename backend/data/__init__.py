# -*- coding: utf-8 -*-
"""S008 后端数据层包。

分组：
- ``transport`` — em_get 限流/熔断/代理探测收口（抽自 astock.em_get）。
- ``sources``   — 按数据源（tencent/eastmoney/akshare/mootdx/sina）拆分 astock 取数。
- ``mappers``   — raw dict → S007 Pydantic 模型投影（异构接口「新」侧）。
                legacy 消费者直接吃 sources 的 raw（全字段，不走往返）。

本包只做映射与传输层；取数逻辑（五源分级/腾讯底座/东财走 em_get）不改，
只改返回类型与文件组织。详见 ``specs/S008-后端数据层迁移/plan.md``。
"""
