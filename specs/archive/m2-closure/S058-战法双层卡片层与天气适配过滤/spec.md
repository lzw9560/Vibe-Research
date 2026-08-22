# Spec: S058 — 战法双层卡片层与天气适配软过滤

> 状态：已实现（T1-T9 全落地，后端 17 passed + 前端 StrategyFilter 8 passed；query_strategy_card AI 工具三出口透明复用）
> 作者：Codex（DSA 借鉴 grill 会话）  日期：2026-08-11
> 级别：**medium**（跨层；新增一个 AI 工具但复用现有 registry，非新 AI 框架）
> 流程门：develop 直提 + 勤 commit；issue 级 review；简化验收
> 关联：`.scratch/dsa-board-borrowing/issues/01`（Q6/Q7 裁决）、`limitup_strategy.py` STRATEGY_REGISTRY、`ai/tools/registry.py`、`routers/sentiment_weather.py`（weather_state）、DSA strategies/*.yaml（内容移植参考）

## 1. 问题 / 目标

Q7 裁决双层方案（c）：结构化注册表 + 自然语言战法卡给 AI 出口解读，**零 YAML 依赖**（VR 现状无 PyYAML，mcp_server 保持零第三方依赖）。Q6 裁决：天气→战法做软过滤（适配度标注，降权不屏蔽）。两事共用 `weather_regimes` 字段，合并一 spec。

## 2. 背景

- `STRATEGY_REGISTRY`（limitup_strategy.py:495）：已有首板挖掘/连板接力/炸板回封/低吸龙头/反包/N字反击等，带量化退出参数；与 DSA 三风格天然对应（首板挖掘≈风格B、连板接力≈风格A、反包≈风格C）。
- AI 出口走 `ai/tools/registry.py` 声明式注册（@register_tool → OpenAI/MCP schema 自动生成），AI 只收工具返回文本，不解析任何文件格式。
- 天气四态：`sentiment_weather._calculate_weather_state` 输出 晴天/阴天/暴风雨/极端反弹/未知（thresholds.py 注释已引用该词汇）。

## 3. 需求清单

- [ ] R1 STRATEGY_REGISTRY 每战法补 `weather_regimes: list[str]`（适配天气列表）+ `aliases: list[str]`；初始映射：连板接力=[晴天]、首板挖掘=[阴天]、反包=[极端反弹]、低吸龙头=[晴天,阴天]、其余按 DSA PRD §3.6 与历史胜率数据校准标注
- [ ] R2 `strategies/cards/<code>.md`（新目录）：每战法一张 Markdown 卡（适用天气/核心逻辑/入场条件/条件单思路/风险点/退出参数），与注册表按 code 一对一；先写现有 6 战法，DSA 19 战法内容移植为后续工单（移内容不移格式，工具名映射 VR 工具、措辞按 §1.1）
- [ ] R3 `ai/tools` 新增 `query_strategy_card(code: str)`：读卡片文件返回文本；code 不存在返 error dict（registry 惯例）；同时暴露别名检索（aliases）
- [ ] R4 天气适配软过滤：漏斗/简报战法命中处计算适配度（适配/不适配/中性：weather_state ∈ regimes → 适配；regimes 非空且不含 → 不适配；未知天气或 regimes 空 → 中性）；不适配命中降权展示（排序后移 + 标注），不屏蔽
- [ ] R5 前端：战法展开区显示适配度标签 + 卡片正文（Markdown 渲染）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/limitup_strategy.py` | 注册表字段 + 适配度函数 |
| `backend/strategies/cards/*.md`（新） | 6 张战法卡 |
| `backend/ai/tools/stock_tools.py` | query_strategy_card 工具 |
| `backend/routers/workflow.py` | 简报战法命中带适配度 |
| `frontend/.../PreMarketBriefing.tsx` 战法区 | 适配度标签 + 卡片渲染 |

## 5. 设计方案

- Markdown 卡片而非 YAML：零新依赖；元数据留注册表（可测试），正文留 md（AI 可读）；按 code 文件名约定绑定。
- AI 不解析 YAML：工具层读文件返文本，三条出口（chat/MCP/cli_runtime）透明复用。
- 软过滤：与 Q3 软 gate 一致，降权不屏蔽；适配度是展示属性，不进基因分。
- 备选不选：YAML 兼容（零依赖原则 + 移植价值在内容不在格式）；屏蔽式硬过滤（软 gate 已决）。

## 6. 验收标准

- [ ] A1 pytest -m "not live" 全过：注册表 schema（每战法有 weather_regimes）、适配度三态逻辑、query_strategy_card 命中/缺失
- [ ] A2 卡片完整性：cards/ 目录与注册表 code 一一对应（CI 断言或测试）
- [ ] A3 tsc + vitest 过；适配度标签渲染正确
- [ ] A4 MCP/chat 双出口调用 query_strategy_card 均返回卡片文本（手动冒烟）

## 7. 合规与工程底线自查

- [ ] 战法卡文案中性（「策略逻辑上」「历史统计特征」），无行动指令；卡片尾挂轻量风险提醒
- [ ] 不臆造：卡片内容来自现有注册表参数 + DSA 公开设计文档，不虚构胜率数字
- [ ] 新工具走 ai/tools/registry 声明式注册，不手写 schema
- [ ] 无新外部数据源

## 8. 测试计划

离线：注册表/适配度/工具单测 + 前端组件测试。手动：chat 页问「连板接力战法」验证工具链路。

## 9. 风险与回滚

- 天气映射标错：映射表可配 + 胜率回填校准（win_rate_tracker signal_ref 已有战法码）；回滚＝regimes 置空（全中性）。
