# Spec: S062 — 战法卡内容填充：反包/龙头实盘参数

> 状态：草案
> 作者：Codex（外部项目借鉴）  日期：2026-08-11
> 级别：**small-medium**（注册表参数 + 2 张卡片 + 测试；单后端层为主）
> 流程门：develop 直提；commit message 记摘要
> 借鉴：quantjuzi/fanbao_strategy（反包：回测 50.9% / 实盘 47.62% 胜率，参数经 357 笔实盘验证）、DSA dragon_head.yaml + attrib2004/a-share-dragon-strategy（龙头识别标准）
> 关联：S058（战法双层卡片层，本 spec 是其内容填充）、S053（break_reseal/reverse_package 60 日无信号查因）

## 1. 问题 / 目标

S058 建卡片层骨架，本 spec 填第一批高质量内容：用外部项目**经回测+实盘验证**的参数充实反包战法，并新增龙头战法条目。顺带回应 S053 线索——reverse_package 60 日无信号，对比 fanbao_strategy 的筛选条件（成交额>15 亿等）排查是否 VR 现条件过严。

## 2. 背景

- fanbao_strategy 公开参数：T-2/T-3 涨停（加分）/ T-1 未涨停（断板调整）/ T-1 成交额>15 亿 / 均线多头 M7/M14>1.0 / 实体涨跌幅>-3%（加分）；执行=次日竞价或开盘买入，严格 T+1 卖出纪律。公开绩效：实盘 357 笔胜率 47.62%（2025.10 起），回测 629 笔胜率 50.9%、均笔 +1.07%（2026.04-06 全 A 5509 股）。
- VR `STRATEGY_REGISTRY` 现有 reverse_package（条件较粗：前日跌停/大阴线+今日放量+游资席位）；无 dragon_head 条目（low_absorption 是回调低吸型，非打板龙头型）。
- DSA dragon_head.yaml 识别标准：板块领涨地位 / 换手>5% / 量比>1.5 / 相对强度跑赢板块 2%+ / 板块级催化。

## 3. 需求清单

- [ ] R1 `STRATEGY_REGISTRY.reverse_package` 参数精化：entry_condition 吸收 fanbao 五条件（保留 VR 游资席位条件为加分项）、`max_hold_days=1`（严格 T+1 纪律）、止损-3%/止盈+6% 复核标注来源
- [ ] R2 `strategies/cards/reverse_package.md`：完整逻辑 + 条件 + 执行 + 退出纪律 + 风险点 + **来源与样本期**（fanbao_strategy 回测/实盘数字原文引用，标注其样本区间）
- [ ] R3 新增 `dragon_head` 注册表条目（入场=板块启动期龙头确认，非追高；条件：板块领涨 + 相对强度 + 换手/量比 + 催化）+ `cards/dragon_head.md`；weather_regimes=[晴天,阴天]（与 S058 衔接）
- [ ] R4 S053 排查产出：用 fanbao 条件对照 VR 现条件，在 commit message 或卡片注释中记录 reverse_package 无信号的可能原因（条件过严/数据缺供）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/limitup_strategy.py` | reverse_package 参数 + dragon_head 新条目 |
| `backend/strategies/cards/reverse_package.md`（新） | 卡片 |
| `backend/strategies/cards/dragon_head.md`（新） | 卡片 |

## 5. 设计方案

- 外部参数只作**卡片内容与注册表阈值参考**，不直接改漏斗过滤逻辑（避免未回测参数进选股主链）。
- 绩效数字原文引用 + 标样本期 + 挂「历史统计不保证未来」，不二次加工。
- 依赖：若 S058 未先落地，卡片目录与 query_strategy_card 工具按 S058 设计先行创建最小版（目录 + 读取函数），S058 实施时合流。

## 6. 验收标准

- [ ] A1 pytest：注册表 schema 测试含 dragon_head；reverse_package 参数断言
- [ ] A2 卡片存在且含来源/样本期段落（测试断言关键字）
- [ ] A3 S053 对照结论有文字记录

## 7. 合规与工程底线自查

- [ ] 卡片措辞中性（「策略逻辑上」「历史统计特征」），外部胜率数字标注来源与样本期，不暗示可复制收益
- [ ] 不臆造：引用数字与源项目原文一致
- [ ] 无新外部数据源

## 8. 测试计划

离线：注册表/卡片单测。手动：chat 出口问「反包战法」验证卡片可读。

## 9. 风险与回滚

- 外部参数不适用 VR 数据口径：参数标注来源，回滚＝恢复原 entry_condition 文本。
