# S054 原子任务清单（依赖与阶段门见 plan.md）

> 裁决版本：Q4–Q7 补裁后。R2 降级、临时票根不展示、昨日漏的取上一交易日、研判两页嵌入 + R8 派生函数复用。
> 基线：后端 999 passed / 前端 38 files 279 tests（S052 验收后）。

## S1 后端 daily-review 端点

- [ ] T1 `backend/routers/win_rate.py` 新增 `GET /api/winrate/daily-review?date=YYYY-MM-DD`（默认今日）：
  - `pushed`：当日快照 `final_candidates` 原样透传（code/name/gene_score/strategies/完整性标记）；无快照则 `no_snapshot=true`
  - `bought`：workflow_state 中 `entry_date == date` 的行，逐只带 code/name/entry_price/strategy + **占位标签「待判定」**（Q7：不返 live 临时票根字段，后端不算 `_infer_signal_attribution`）
  - `missed`：pushed − bought 的 code 名单（无收益，留白）
  - `prev_day_missed`：**上一交易日**（Q6：用 `last_trading_date_str` 定位，非「上一快照日」）的 missed 标的，逐只 `_calc_next_day_return`（信号日 close→次日 close）+ 汇总（n/avg_return/win_rate）；回溯上限 5 自然日，标注实际信号日期；超限或无则空态
  - K 线缺失逐只排除并计数 `missing_kline`；零外部调用
  - 单测：三问三分支 + 无快照日 + 上一交易日回溯（含超 5 日空态）+ K 线缺失排除 + bought 占位标签
  - commit 门：端点 fixture 测试绿 + 零外呼自查（grep 无 em_get/requests/httpx 新增）

## S2 前端研判派生函数抽取（R8）

- [ ] T2 新增 `frontend/src/lib/winrate-assessment.ts`：`deriveAssessmentTips(data: ShadowComparison): string[]` 纯函数
  - 从 BehaviorLoop `_deriveAssessmentTips` 原样抽取（follow vs feeling 胜率对比 / 一致率 / missed 影子质量 / 样本不足压低权重 / 全空兜底）
  - 纯函数单测：follow 高于 feeling / feeling 反超 / 两者接近 / 一致率高/低 / missed 胜率高/低 / 样本不足 / 全空
  - commit 门：派生函数单测绿 + tsc 绿

- [ ] T3 `BehaviorLoop.tsx` 改用共享派生函数：删本地 `_deriveAssessmentTips`，import `deriveAssessmentTips`
  - 行为不变（既有 BehaviorLoop.test.tsx 为回归门）
  - commit 门：BehaviorLoop 既有测试全绿 + tsc 绿

## S3 盘后复盘页去桩 + 简报行为卡

- [ ] T4 `frontend/src/lib/api/`：DailyReview 类型 + useDailyReview hook（useQuery 模式，参照 useShadowComparison）
  - commit 门：tsc 过

- [ ] T5 `PostMarketReview.tsx` 去桩重写（`/workflow/post-market`，沿用 WorkflowStage 壳）：
  - 日期选择器（默认今日，历史日可查）
  - 三问区三卡：
    - 「系统推了什么」：pushed 列表（code/name/gene_score/strategies）
    - 「你买了什么」：bought 逐只（code/name/entry_price）+ **占位标签「待判定」**（Q7：不展示 live 票根；结算后才显真票根）
    - 「漏了什么」：missed 名单 + "明日盘后补账"说明
  - 昨日漏的结算条：prev_day_missed 逐只 + 汇总（n/win_rate/avg_return）；标注实际信号日期（上一交易日 ≠ 自然昨日时注明）
  - 结算入口卡：待结算持仓逐行「去结算」→ 携 code 跳既有状态机流转（S033/S034，含 attention_mode）
  - **研判**（Q5）：调 `deriveAssessmentTips`（三问页也嵌方向建议）；传入 shadow-comparison window=28 数据
  - 教学点 3 句（文案见 spec R5）；空态四类（无快照/无建仓/无漏单/无昨日漏单）；风险注记
  - vitest：三问渲染 / 占位「待判定」/ 空态四类 / 结算入口链接 / 教学点 / 研判
  - commit 门：PostMarketReview vitest 绿 + tsc 绿

- [ ] T6 `PreMarketBriefing.tsx` 加回行为干预卡（**展开不收起**）：
  - 数据复用 `GET /api/winrate/shadow-comparison?window_days=28`（既有端点，既有 useShadowComparison hook）
  - 三桶算账（follow/feeling/missed：n+胜率+均收益）+ 一致率 + 教学一句 + n<5 caveat + 风险注记 + 「深看」链接 → /behavior-loop
  - **研判**（Q5）：调 `deriveAssessmentTips`（简报卡也嵌方向建议）
  - vitest：渲染 / 样本不足 / 空数据 / 链接 / 研判
  - commit 门：PreMarketBriefing vitest 绿 + tsc 绿

## S4 全测与合规自查

- [x] T7 离线全测：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov` 全绿；`cd frontend && npx tsc --noEmit && npx vitest run` 全绿
- [x] T8 合规自查：方向建议经 R8 派生函数统一产出（不臆造）；风险注记与样本 caveat 在位；grep 无硬编码方向词
  - commit 门：T7+T8 过后 `docs(S054): 验收` commit

## S5 冒烟与归档

- [ ] T9 dev server :8900 冒烟（勿杀勿重启，uvicorn --reload 热加载）：
  - `/workflow/post-market`：三问卡 + 占位「待判定」+ 结算入口可跳转 + 空态正确 + 研判呈现
  - `/workflow/pre-market`：行为干预卡展开渲染 + 研判 + 深看链接可达
  - `/behavior-loop`：不受影响（改用共享派生函数，行为不变）
  - 用户走查通过后 spec.md 状态改"已实现"，commit `docs(S054): 验收`

## 门汇总

| 门 | 内容 | 位置 |
|---|---|---|
| G1 | T1 端点 fixture 测试绿 + 零外呼自查 | S1 末 |
| G2 | T2 派生函数单测 + T3 BehaviorLoop 回归绿 + tsc | S2 末 |
| G3 | T4/T5/T6 vitest + tsc 全绿 | S3 末 |
| G4 | 离线全测绿 + 合规自查 | S4 末 |
| G5 | 冒烟 + 用户走查 + 归档 commit | S5 末 |
