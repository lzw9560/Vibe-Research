# Spec: S060 — 明日验证条件对账卡

> 状态：草案
> 作者：Codex（外部项目借鉴）  日期：2026-08-11
> 级别：**medium**（跨层 >50 行；无新外部数据源——全部复用现有情绪/板块/行情数据）
> 流程门：develop 直提 + 勤 commit；issue 级 review；简化验收
> 借鉴：simonlin1212/vibe-astock「明日验证条件」（每条判断带今日基准值 + 变动阈值，次日对账）
> 关联：S054（复盘三问/简报呈现哲学）、S055/S056（纪律闭环）、`market._emotion` / `limitup_sti`（数据源）

## 1. 问题 / 目标

盘后判断（"主线延续"/"情绪修复"）目前说完即忘，次日无法客观对账。vibe-astock 的做法：把判断落成**可验证条目**——每条带今日基准值 + "变动超过多少才算数"的阈值，次日用实际数据对账。本 spec 给 VR 加这个客观对账层，闭合"盘后判断 → 次日验证"环节。

## 2. 背景

- 数据全部现成：`market._emotion`（封板率/炸板率/晋级率/连板梯队/涨跌停家数）、STI 分数与阶段、涨停池板块分布、昨日涨停溢价（`backtest_lite._calc_next_day_return` 口径）。
- 呈现哲学沿用 S054：嵌回工作流环节（简报 + 三问页），不新开独立页。

## 3. 需求清单

- [ ] R1 条件模型：`VerificationCondition {date, metric, subject, baseline, threshold_up, threshold_down, actual, status}`；status = pending/met_up/met_down/within/data_missing
- [ ] R2 规则模板生成器（盘后调度产出）：≥5 条固定模板——涨停家数（±20% 阈值）/ 炸板率（±5pct）/ 连板高度（持平或±1 板）/ 主线板块涨停数（-30% 视为断档）/ 昨日涨停今日溢价（正负翻转视为赚钱效应变脸）；阈值进配置可调
- [ ] R3 对账器：T+1 盘后用实际值算 status；缺数据 → data_missing 诚实标注，不猜
- [ ] R4 SQLite 持久化（S037 惯例，.vibe-research/）+ 端点 `GET /api/workflow/verification-card?date=`（返当日生成 + 昨日对账结果）
- [ ] R5 前端：简报市场情绪区下方「昨日验证对账」块（条件/基准/阈值/实际/✓✗ 平局）；三问页展示当晚新生成的条件预览
- [ ] R6 生成方式：**纯规则模板**（客观可测）；AI 出口可读卡片内容作上下文，不作为生成源（AI 生成判断留作后续）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/workflow/verification_card.py`（新） | 模型 + 生成器 + 对账器 + 持久化 |
| `backend/routers/workflow.py` | verification-card 端点 |
| `backend/post_market_workflow.py` / 调度 | 盘后生成 + T+1 对账接线 |
| `frontend/.../PreMarketBriefing.tsx` | 对账块 |
| `frontend/.../PostMarketReview.tsx` | 条件预览 |

## 5. 设计方案

- 对账时点选 T+1 盘后（全天数据完整，无竞价口径歧义）；简报展示的是"昨日条件的对账结果"。
- 模板条件全是市场级聚合指标（零个股名红线友好）；个股层验证不做。
- 备选不选：AI 生成条件（不可测、合规表述风险）；盘中实时对账（口径不稳）。

## 6. 验收标准

- [ ] A1 pytest -m "not live" 全过：生成器模板单测 + 对账三态（met/within/missing）
- [ ] A2 冒烟：mock 两日情绪数据，端点返回生成+对账完整结构
- [ ] A3 tsc + vitest 过；缺数据显示「—」

## 7. 合规与工程底线自查

- [ ] 条件与对账均为客观统计口径，条件句式为「若…则确认…」，无涨跌预测
- [ ] 不臆造：缺数据 status=data_missing
- [ ] 无新外部数据源；私有数据不进 git

## 8. 测试计划

离线：模板/对账单测 + 端点测试 + 前端组件测试。手动：简报对账块走查。

## 9. 风险与回滚

- 阈值不合理导致"全平局"无信息量：阈值可配 + 上线后按命中率调；回滚＝前端块隐藏。
