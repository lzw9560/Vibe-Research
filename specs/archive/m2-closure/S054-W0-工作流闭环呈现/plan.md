# S054 Plan — W0 工作流闭环呈现

> 级别 medium；develop 直提；阶段顺序 S1→S4，门 G1–G5 见 task.md。
> 串行纪律：后端端点未绿不碰页面；页面未绿不碰简报卡（两页改动分离，降低与并行会话冲突面）。
> 裁决版本：Q4–Q7 补裁后（见 spec §2）；R2 降级、临时票根不展示、昨日漏的取上一交易日、研判两页嵌入 + R8 派生函数复用。

---

## 阶段划分

### S1 后端 daily-review 端点（T1→T2）

- daily-review 端点只读：snapshot_store（final_candidates）、workflow_state（建仓/持仓）、K 线（_calc_next_day_return）
- **Q7 简化**：bought 不返临时票根字段（占位「待判定」由前端渲染）；后端不算 live 票根 → 无需调 `_infer_signal_attribution`
- **Q6 改口径**：prev_day_missed 取上一交易日（`last_trading_date_str`），非「上一快照日」；回溯上限 5 自然日
- R2 降级为可选：`_infer_signal_attribution` 保持原位不动，结算路径零改动
- 门 G1：T1/T2 单测绿 + 零外部调用自查（grep 无 em_get/requests/httpx 新增）

### S2 前端研判派生函数抽取（T3）

- R8 新增：把 BehaviorLoop `_deriveAssessmentTips(data: ShadowComparison): string[]` 抽为共享纯函数
- 位置：`frontend/src/lib/winrate-assessment.ts`（新建）
- BehaviorLoop 改 import 共享函数（行为不变，既有测试为回归门）
- 门 G2：派生函数单测绿 + BehaviorLoop 既有测试绿 + tsc 绿

### S3 盘后复盘页去桩 + 简报行为卡（T4→T5）

- 依赖 S1（端点）+ S2（派生函数）。先写 hook+types，再重写 PostMarketReview.tsx
- 「去结算」跳转目标：状态机页面既有流转入口（携 code 参数）；不新建表单、不建批量结算
- 注意 S036 遗留：`frontend/src/lib/query/limitup.ts` 里有灰置的 usePostMarketReview 桩 hook——本次用新的 useDailyReview，桩 hook 保留原样不删
- **Q5**：两页都嵌研判（调 R8 派生函数）；三问页传入 daily-review 的三桶数据（或用 shadow-comparison window=28 兜底）
- **Q7**：三问页「你买了什么」用占位标签「待判定」，不展示 live 票根
- 门 G3：PostMarketReview + PreMarketBriefing vitest 绿 + tsc 绿

### S4 合规自查 + 全量回归 + 冒烟（T6→T7）

- G4 口径 grep：方向建议经 R8 派生函数统一产出（不臆造）；风险注记两处齐备；n<5 caveat 在位
- G4 全量：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov` + `cd frontend && npx tsc --noEmit && npx vitest run`，与基线（后端 999 passed / 前端 38 files 279 tests）对比只增不减
- G5 dev server :8900 冒烟（勿杀勿重启后端 --reload 自热加载）：盘后页三问渲染（今日/历史日期/空态）+ 简报卡渲染 + 「去结算」跳转链路 + /behavior-loop 深看链接可达

---

## 风险与对策

| 风险 | 对策 |
|---|---|
| PreMarketBriefing 被并行会话再改 | S3 开工前 git log 确认；只增量加卡，不重排既有区块 |
| ~~attribute_signal 抽取改变结算行为~~ → **风险消除**（Q7） | R2 降级为可选，结算路径零改动 |
| R8 派生函数抽取改变 BehaviorLoop 既有行为 | T3 内 BehaviorLoop.test.tsx 为回归门，红了即回滚 |
| prev_day 回溯超 5 个自然日仍无快照 | 返回 null + 页面空态文案「近期无推举记录可补账」 |
| 教学点文案被写成方向结论 | G4 grep 门 + spec §4 文案表为准（可微调措辞不得移义） |

## 提交节奏（AGENTS.md 勤 commit）

1. `feat(S054): daily-review 端点——盘后三问数据底座（上一交易日口径，不返临时票根）`（G1）
2. `refactor(S054): 研判派生函数抽取——BehaviorLoop/简报/三问三处共用`（G2）
3. `feat(S054): 盘后复盘页去桩——三问+昨日漏的补账+结算入口+研判`（G3）
4. `feat(S054): 简报行为干预卡恢复——三桶算账展开+研判+深看链接`（G3）
5. `docs(S054): 验收——闭环对照表全绿，G4/G5 通过`
