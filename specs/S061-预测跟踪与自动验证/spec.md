# Spec: S061 — 预测跟踪与自动验证（预测账本）

> 状态：已实现（2026-08-12，commit 5c15126；pytest 1087 passed / tsc 绿 / vitest 309 passed）
> 作者：Codex（外部项目借鉴）  日期：2026-08-11
> 级别：**medium**（跨层；无新外部数据源——验证用现有 K 线/行情）
> 流程门：develop 直提 + 勤 commit；issue 级 review；简化验收
> 借鉴：wwyharry/DeepPulse「预测跟踪：保存预测并自动验证结果，从对错中持续学习」
> 关联：S050（win_rate_tracker 信号归因 5 列）、S054（三问"中了多少"）、`candidate_funnel` / `strategies`（预测来源）

## 1. 问题 / 目标

`win_rate_tracker` 只跟踪**已执行交易**的胜率；系统每天产出的大量判断（漏斗候选、战法命中）未被系统化验证——哪个信号源值得听，没有客观账本。本 spec 建「预测账本」：信号自动入账为预测 → 到期自动验证 → 按来源统计命中率。

## 2. 背景

- 预测来源（一期）：①漏斗 final 候选自动入账（预测=次日溢价>0）②战法命中入账（预测=按战法 max_hold_days 的止盈/止损结果）③用户手工录入；AI 研判解析为结构化预测留二期。
- 验证基础设施现成：`backtest_lite._calc_next_day_return`（次日收益）、腾讯 K 线（多日持有验证）。
- 与 win_rate_tracker 的关系：账本记**判断**（含未执行的），win_rate 记**交易**；账本命中率按 `signal_source/signal_ref` 聚合，与归因列共用词汇。

## 3. 需求清单

- [ ] R1 预测模型：`Prediction {id, date, source(funnel/strategy/manual), signal_ref, code, claim, baseline_price, horizon, status(pending/win/lose/expired/data_missing), actual_return}`
- [ ] R2 入账器：盘后调度扫当日漏斗 final + 战法命中，幂等入账（唯一键 date+source+code）
- [ ] R3 验证调度：到期日按 horizon 算实际收益（T+1 用次日 close；多日用持有期 close），写 status；K 线缺失 → data_missing
- [ ] R4 统计端点 `GET /api/predictions/ledger?days=30&source=`：账本列表 + 按 source/signal_ref 命中率汇总
- [ ] R5 手工录入端点（POST）+ 前端：胜率页加「预测账本」Tab（列表 + 命中率分组）；三问页"中了多少"引用当日预测命中率
- [ ] R6 保留期：账本保留 180 天（可配），超期归档不删除

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/prediction_ledger.py`（新） | 模型 + 入账 + 验证 + 统计 |
| `backend/routers/win_rate.py` 或新 router | ledger 端点 |
| `backend/scheduled_tasks.py` | 入账/验证任务注册 |
| `frontend/.../WinRate*` | 预测账本 Tab |
| `frontend/.../PostMarketReview.tsx` | "中了多少"引用命中率 |

## 5. 设计方案

- 一期不做 AI 研判解析（LLM 输出结构化不稳定，先跑通客观信号闭环）。
- 预测是客观记录不是推荐：账本只回答"系统上次说的对不对"。
- 备选不选：扩展 win_rate_tracker 表（交易与判断语义混在同一张表会污染胜率统计）。

## 6. 验收标准

- [ ] A1 pytest -m "not live" 全过：入账幂等、验证三态、命中率聚合
- [ ] A2 冒烟：合成两日数据跑通 入账→验证→统计 全链
- [ ] A3 tsc + vitest 过；Tab 缺值显「—」

## 7. 合规与工程底线自查

- [ ] 账本属历史统计呈现，挂轻量风险提醒；不出现「跟单」暗示
- [ ] 不臆造：K 线缺失 → data_missing，不补收益
- [ ] 无新外部数据源；账本（含手工录入）存 .vibe-research/ 不进 git

## 8. 测试计划

离线：入账/验证/统计单测 + 端点测试。手动：Tab 走查 + 手工录入闭环。

## 9. 风险与回滚

- 命中率样本少时误导：汇总带样本数 n，n<10 前端标注「样本不足」；回滚＝Tab 隐藏。
