# Spec: S054 — W0 工作流闭环呈现（盘后三问 + 简报行为卡）

> 状态：已实现（T1-T9 全落地，API 冒烟 + 离线全测绿；UI 走查待用户确认）
> 作者：Codex grill 会话  日期：2026-08-11（Q4–Q7 本会话补裁）
> 级别：**medium**（跨前后端 >50 行；无新外部数据源、无新 AI 工具、无新财务公式——影子收益复用已验证的 `backtest_lite._calc_next_day_return`）
> 流程门：develop 直提 + 勤 commit；issue 级 grill 已在本会话完成（Q1–Q7 裁决见 §2）；验收＝离线全测 + tsc/vitest + dev server 冒烟走查
> 关联：WR-Workflow v1.2 §2/§12.2/§12.4（环节呈现与复盘三问）、S050（数据层：票根/shadow-comparison/迁移 003 + 弱合规放宽 7ccc5d2）、S049（快照 final_candidates 诊断卡）、S036（盘后复盘桩）、S033/S034（状态机结算流转）

## 1. 问题 / 目标

S050 数据层（票根/影子对照）与 WR-Workflow v1.2 的 W0 定义一致，但**呈现层偏离已批准工作流**：

1. §12.2 时刻表明定收盘环节＝「复盘三问（推了什么/中了多少/为什么漏了）→ 填结算票根」，S050 却把影子对照做成独立页（commit 3e39858 明示"与工作流解耦"）；
2. `PostMarketReview.tsx` 至今灰置 `not_implemented` 桩（S036 遗留），票根填写/三问无落点；
3. 简报行为卡先被收起、后被整个移出简报页，盘前决策环节失去行为干预。

本 spec 把 W0 呈现**嵌回工作流环节**，闭合 §2 每日循环的最后一环（盘后结算→复盘→次日干预）。数据层零返工。

## 2. 裁决记录（2026-08-11 grill，Q1–Q3 + 本会话 Q4–Q7 补裁）

| # | 裁决 | 内容 |
|---|---|---|
| Q1 | ✅ 环节化嵌入、独立页降级 | a. 盘后复盘页去桩＝三问+结算入口；b. 简报恢复行为干预卡（展开）；c. /behavior-loop 保留降级为深看入口；d. 时刻表页属 W-C，本次不建 |
| Q2 | ✅ 三问口径 | 当日三问 + 漏的 T+1 补账；新端点 daily-review；不新建批量结算 |
| Q3 | ✅ 呈现形态与合规口径 | 三问页/简报卡只出客观算账+教学点；方向建议只留 BehaviorLoop 行为研判区；优化当前工作流模块，不新开页面 |
| **Q4** | ✅ **嵌回裁决确认**（覆盖本会话早先「独立页不耦合」指令） | 以 S054 嵌回为准：BehaviorLoop 独立页降级为深看链接，行为卡嵌回盘前简报 + 盘后三问页，回到工作流环节内 |
| **Q5** | ✅ **研判嵌入两页**（放宽 R6/Q3） | 简报卡 + 三问页都嵌方向建议（与 S050 弱合规放宽一致）；方向建议不再单一出处＝BehaviorLoop；R6「纯客观」作废 |
| **Q6** | ✅ **昨日漏的取上一交易日**（改 R1 口径） | prev_day_missed 用 `last_trading_date_str` 定位，非「上一快照日」——避免跨周末「快照日≠交易日」歧义；回溯上限仍 5 自然日 |
| **Q7** | ✅ **临时票根不展示**（简化 R1/R2） | 三问页「你买了什么」用占位标签「待判定」——不展示 live 临时票根，结算后才显真票根；daily-review 不返临时票根字段；R2 纯函数抽取降级为可选（结算路径无预览共用需求，重构风险消失） |

## 3. 需求清单

- [ ] R1 后端新端点 `GET /api/winrate/daily-review?date=YYYY-MM-DD`（默认今日），返回：
  - `pushed`：当日快照 `final_candidates`（code/name/gene_score/strategies/完整性标记），无快照则 `no_snapshot=true` 诚实返回
  - `bought`：当日 workflow_state 新建仓（entry_date == date），逐只带 code/name/entry_price + 占位标签「待判定」（**Q7：不返 live 临时票根字段**）
  - `missed`：pushed − bought 的名单（无收益数字，诚实留白）
  - `prev_day_missed`：**上一交易日**（Q6：用 `last_trading_date_str` 定位，非「上一快照日」）的 missed 标的，逐只次日收益（`_calc_next_day_return` 信号日 close→次日 close）+ 汇总（n/avg_return/win_rate）；回溯上限 5 自然日并标注实际日期，超限或无则空态
  - K 线缺失逐只排除并计数（missing_kline）；零外部调用
- [ ] R2 ~~临时票根纯函数抽取~~ → **降级为可选**（Q7）：三问页不展示 live 临时票根，daily-review 不返临时票根字段，结算路径无预览共用需求；S050 `_infer_signal_attribution` 保持原位，本 spec 不强制抽取。若实施时为代码整洁顺手抽取可做，但不作为验收门
- [ ] R3 `PostMarketReview.tsx` 去桩重写（`/workflow/post-market`，沿用 WorkflowStage 壳）：
  - 日期选择器（默认今日，历史日可查）
  - 三问区三卡：「系统推了什么」/「你买了什么」（**Q7：占位标签「待判定」，不展示 live 票根**；结算后才显真票根）/「漏了什么」（含"明日盘后补账"说明）
  - 昨日漏的结算条：prev_day_missed 逐只 + 汇总
  - 结算入口卡：待结算持仓逐行「去结算」→ 携 code 跳既有状态机流转（S033/S034，含 attention_mode 选择），不新建批量结算
  - 空态诚实：无快照/无建仓/无漏单/无昨日漏单各有文案，不渲染假数据
- [ ] R4 `PreMarketBriefing.tsx` 恢复行为干预卡（**展开不收起**）：三桶算账（follow/feeling/missed：n+胜率+均收益，复用既有 shadow-comparison window=28）+ 一致率 + 教学一句 + n<5 caveat + 风险注记 + 深看链接 → /behavior-loop
- [ ] R5 教学点（D8c 默认开，讲机制不讲动作）：
  - 三问页：「复盘的意义是迭代：每天回答三问，漏斗用你的真实数据校准」/「票根标感觉单不是问责，是量出直觉值不值得留」/「错过的成本是真实数字，不是感觉」
  - 简报卡：「决策前先看自己的行为账单：感觉单与跟随单的差距是校准出来的，不是猜出来的」
  - 文案实现时可微调措辞，语义不变；本次不做教学开关（backlog）
- [ ] R6 ~~合规口径：不出方向建议~~ → **放宽**（Q5）：三问页与简报卡**可出方向建议**（与 S050 弱合规放宽一致）；方向建议复用 R8 派生函数；任一桶 n<5 明示「样本不足，参考价值低」；两页均挂「历史统计特征，市场有风险，研究参考」
- [ ] R7 闭环对照表（验收时逐行核对，见 §6 A6）
- [ ] R8 **研判派生函数复用**（Q5 新增）：将 BehaviorLoop `_deriveAssessmentTips(data: ShadowComparison): string[]` 抽为共享纯函数（`frontend/src/lib/winrate-assessment.ts` 或同侧模块），三处共用：BehaviorLoop / PreMarketBriefing 行为卡 / PostMarketReview 三问页。三问页传入 daily-review 的三桶数据（若 daily-review 不返 shadow 数据则用 shadow-comparison window=28 兜底）；派生逻辑单一事实源，三页呈现一致

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/settlement_recorder.py` | 票根关联抽纯函数（R2），结算路径复用，行为不变 |
| `backend/routers/win_rate.py` | + daily-review 端点（复用 snapshot_store/_bucket/_calc_next_day_return） |
| `frontend/src/lib/api/*` | types + useDailyReview hook |
| `frontend/src/lib/winrate-assessment.ts` | 新增：研判派生纯函数（R8，三处共用） |
| `frontend/src/pages/workflow/PostMarketReview.tsx` | 去桩重写（R3） |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | + 行为干预卡（R4） |
| `frontend/src/pages/BehaviorLoop.tsx` | 研判区改用共享派生函数（R8，行为不变） |
| 导航 / 路由 | **零改动**（不新开页面、不加 tab） |

## 5. 设计取舍

1. **临时票根不展示**（Q7 改）：三问页「你买了什么」用占位标签「待判定」，不展示 live 票根——避免预判误导（用户可能误读为已定论）；正式票根仍在结算时落定（S050 R2 逻辑原位不动）；R2 纯函数抽取降级为可选，结算路径无预览共用需求，重构风险消失。
2. **"昨日漏的"取上一交易日**（Q6 改）：用 `last_trading_date_str` 定位而非「上一快照日」——避免跨周末「快照日≠交易日」歧义（周五快照对周二，中间隔了周一）；回溯上限仍 5 自然日，页面标注实际信号日期；超限或无快照则空态。
3. **不建批量结算**：结算入口跳转既有状态机表单，范围不蔓延；批量结算本身在 S036 注释里就是将来项。
4. **简报卡复用 window=28 端点**：行为干预看的是趋势（近期行为模式），不需要单日粒度；daily-review 只服务盘后页，职责单一。
5. **/behavior-loop 不删不改**：保留为深看入口（简报卡与三问页均放链接），研判区改用 R8 共享派生函数（行为不变，仅抽取复用）；不 revert 他人改动。
6. **研判单一事实源**（R8）：`_deriveAssessmentTips` 抽共享纯函数，三页共用——避免三处各自派生导致建议不一致；派生逻辑改动只改一处。

## 6. 验收标准

- [ ] A1 daily-review fixture 测试：三问三分支 + 无快照日 + 上一交易日回溯（含超 5 日空态）+ K 线缺失排除 + bought 占位「待判定」（不返临时票根）
- [ ] A2 ~~R2 重构回归~~ → **降级**（Q7）：结算路径零改动，S050 既有三分支单测保持绿（无重构即无回归风险）
- [ ] A3 PostMarketReview vitest：三问区/结算入口链接/空态/教学点/占位「待判定」标签
- [ ] A4 PreMarketBriefing vitest：行为卡三桶+一致率+caveat+风险注记+深看链接+研判（R8 派生）
- [ ] A5 离线全测绿：`pytest -m "not live" --no-cov`（基线 999 passed）+ tsc + vitest（基线 38 files/279 tests）
- [ ] A6 闭环对照表逐行达标：

| 环节 | 载体 | 达标判据 |
|---|---|---|
| 盘后预计算 | 定时任务（STI/weather/回测快照） | 已有（S052 缺口补跑后闭环） |
| 盘前简报 | PreMarketBriefing + 行为干预卡 | 本 spec R4 |
| 竞价确认 | /limitup/auction | 已有 |
| 盘中盯盘 | IntradayMonitor + 炸板预警 | 已有 |
| 盘后结算三问 | PostMarketReview 去桩 | 本 spec R1/R3 |
| 周末反馈 tear sheet | W5/N5 | 未来阶段（本 spec 注明，不算缺口） |
| 观察期收敛决策 | ≥4 周凭对照数据人工决策 | 已有（S050 R7） |

## 7. 合规与工程底线自查

- [ ] ~~客观算账无方向词~~ → **放宽**（Q5）：三问页与简报卡可出方向建议（与 S050 弱合规放宽一致，§12.3 口径）；方向建议经 R8 派生函数统一产出，不臆造；两页挂风险注记
- [ ] 收益口径复用已验证 `_calc_next_day_return`，零心算零臆造；近似口径 UI 明示
- [ ] winrate.db/workflow_state/快照均 gitignored 私有数据；测试一律临时库 fixture
- [ ] 零新增东财端点（daily-review 只读本地库）

## 8. 测试计划

- 后端：daily-review 端点 fixture 测试（三问三分支 + 上一交易日回溯 + K 线缺失 + 占位标签）；`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`
- 前端：PostMarketReview/PreMarketBriefing vitest + R8 派生函数单测 + tsc；`cd frontend && npx tsc --noEmit && npx vitest run`
- 手动：:8900 冒烟——盘后页三问（含空态）+「去结算」跳转 + 简报行为卡走查（用户验收）

## 9. 风险与回滚

- 快照缺失日 → no_snapshot 诚实返回，三问区空态文案，不渲染假数据
- K 线缺口 → 该标的排除 prev_day_missed 统计并计数
- ~~R2 重构触碰结算路径~~ → **风险消除**（Q7：R2 降级为可选，结算路径零改动）
- R8 派生函数抽取改变 BehaviorLoop 既有行为 → 既有 BehaviorLoop.test.tsx 为回归门，红了即回滚该 commit
- 回滚：端点/组件独立新增，revert commit 即可；零迁移零 schema 改动

## 10. 明确不做（本 spec 外）

- 时刻表页 / 当前环节高亮 → W-C 阶段
- 批量结算、票根修正端点、教学点开关 → backlog
- 周末 tear sheet → W5/N5
- BehaviorLoop 页本身任何改动（含导航定位文案）→ 不动
