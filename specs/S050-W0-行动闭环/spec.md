# Spec: S050 — W0 行为闭环（票根 + 影子对照 + 独立性基线）

> 状态：已实现（离线全测绿）；dev server 冒烟待用户本地走查
> 作者：Codex 会话  日期：2026-08-11
> 级别：**medium**（跨前后端 >50 行；无新外部数据源、无新 AI 工具、无新财务公式——影子收益复用已验证的 `backtest_lite._calc_next_day_return`，结算公式零改动）
> 流程门：develop 直提 + 勤 commit；验收＝离线全测 + tsc/vitest + dev server 冒烟（对齐 S049 降级先例与 WR-Workflow §12.6"medium 级逐阶段拆 spec"承诺；若用户裁定影子收益属"财务验算"→ 升 large 换 feature 分支，文档结构不变）
> 关联：WR-Workflow §10.2/§12.4-12.5（W0 定义）、DEC-003（D7c）、DEC-004（D8d）、S033（状态机表单）、S034（结算接线）、S038（市价结算）、S049（快照 + 战法 trades 三字段）、S043/S047（次日溢价机制）

## 1. 问题 / 目标

用户自诊"短线凭感觉做"是元短板：行为不可测量时，后续任何新能力（闸门/归因/校准）产出的数据都被感觉单污染。W0 不加新能力，先把行为测出来：

1. **票根**：每笔结算关联系统信号（候选/战法）或显式标"感觉单"；
2. **影子对照**：系统建议单 vs 用户实际单并排算账，含"漏掉候选"的影子收益；
3. **独立性基线**：一致率 + 用户独立判断胜率，≥4 周观察期后凭数据决定 W1+ 建设方向（§10.2 串行纪律）。

## 2. 背景（现状挂载点）

- 结算链路：`workflow_state` settled 流转 → `settlement_recorder.record_settlement` → `winrate_records`（winrate.db，私有）
- 系统建议单：每日快照 JSON（`routers/workflow.py::_save_snapshot`）的 `final_candidates` 诊断卡（S049 C4）
- 用户实际单：`workflow_state` holding/settled 行（S033 表单自填价格/战法）
- 次日收益机制：`backtest_lite._calc_next_day_return`（K 线 close→close，S043/S047 已验证口径）
- 战法命中明细：`strategy_backtest` trades 带 date/code/name（S049 T14）
- `winrate_records` 现列：stock_code/strategy_used/entry_date/exit_date/entry_price/exit_price/return_pct/is_win/gene_score/sti_label/sector——**无信号归因列**（D7c/D8d 欠账）

## 3. 需求清单

- [x] R1 winrate.db 迁移 003：`winrate_records` 加 5 列 `signal_source`/`signal_ref`/`edge_family`/`target_holding_period`/`attention_mode`，全可空、向前兼容（旧行 NULL，统计归 legacy 桶）
- [x] R2 结算时自动票根关联：`record_settlement` 按 (code, trade_date) 查当日快照 `final_candidates` 命中 → `funnel_candidate`；未命中但战法回测 trades 命中 → `strategy_hit`（signal_ref=战法码）；皆无 → `feeling`
- [x] R3 `attention_mode` 进结算归因（D8d）：settled 流转表单加 A/B/C 选择（默认 A），经 state 行落库写入记录；`edge_family` 后端推断（funnel→momentum_premium，value 类战法→mean_reversion，其余 ''），本周期不做 UI 选择（现系统只产动量信号，选择框是假交互；W1/W5' 新管道上线时补）
- [x] R4 影子对照端点 `GET /api/winrate/shadow-comparison?window_days=28`：follow/feeling/missed 三桶（n/胜率/均收益）+ 独立性指标 + n<5 桶标"样本不足"+ 无快照日诚实排除计数
- [x] R5 missed 影子收益：`final_candidates` 中未进 holding 的标的，复用 `_calc_next_day_return`（信号日 close→次日 close，UI 明示近似口径，与 S047 证据基线同口径）；K 线缺失排除并计数
- [x] R6 `PreMarketBriefing` 加"行为对照"卡：三桶算账表 + 一致率 + 教学一句话（样本量 caveat，D8c 教学模式默认开）+ 轻量风险提醒
- [x] R7 观察期语义：端点与卡片只出客观算账，**不出方向结论**；≥4 周后的方向决策是人读数据（本 spec 不建自动决策/毕业逻辑）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/migrations/win_rate_tracker/20260811-003_add_signal_attribution.sql` | 新增：5 列 ALTER |
| `backend/win_rate_tracker.py` | 迁移注册 + `WinRateRecord` 扩 5 字段 + add_record 写入 |
| `backend/snapshot_store.py` | 新增：快照读取从 `routers/workflow.py` 抽出共享（避免 settlement→router 循环引用） |
| `backend/settlement_recorder.py` | 票根关联 + edge_family 推断 + attention_mode 透传 |
| `backend/workflow_state_repo.py` | `_ensure_columns` 加 attention_mode |
| `backend/routers/workflow.py` | TransitionRequest 加 attention_mode；快照读取改 import snapshot_store |
| `backend/routers/win_rate.py` | 新增 shadow-comparison 端点 |
| `backend/backtest_lite.py` | 仅复用 `_calc_next_day_return`，零逻辑改动 |
| `frontend/src/lib/api/*` | types + useShadowComparison hook |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | ShadowComparisonSection |
| 结算表单组件（workflow components） | attention_mode A/B/C 选择 |

## 5. 设计方案（关键取舍）

1. **票根在结算时关联，不在买入时**：settled 是唯一价格+状态齐备的锚点；买入时当日快照可能尚未生成。代价：感觉单判定是事后的——判定从严（快照与战法 trades 双双未命中才标），误判容忍，修正端点进 backlog 不做。
2. **missed 影子口径 close-to-close**：不假设用户执行价，与 S047 证据基线同口径可互比；不做竞价开盘口径（auction_open_pct 仅当日有，历史缺口大）。
3. **对照卡放盘前简报而非盘后复盘**：行为干预要发生在决策之前（盘前看到"感觉单胜率 X%"），不是事后。
4. **一致率分母只算已结算单**：follow_n/(follow_n+feeling_n)；未买入的候选不进分母（未被执行的建议不稀释一致率）。
5. **快照读取抽 snapshot_store**：settlement_recorder 直接 import `routers.*` 会循环依赖；抽取后 workflow router 与结算器共用，行为不变（重构任务单独测试门）。

## 6. 验收标准

- [ ] A1 迁移幂等（跑两遍不报错）；legacy 行 5 列 NULL；既有 stats/trends/strategy API 不受影响（NULL → legacy 桶）
  - 注：迁移幂等 + legacy NULL + get_stats NULL 兼容单测绿（5 passed）；既有 API 零改动（NULL 不崩）
- [x] A2 票根关联三分支单测绿：快照命中 / 仅战法命中 / 双miss → feeling
- [x] A3 shadow-comparison fixture 测试：三桶算账正确 + 样本不足标记 + 无快照日排除 + K 线缺失排除
- [x] A4 前端对照卡渲染三桶 + 一致率 + 风险提醒（vitest）；结算表单 attention_mode 可选
- [x] A5 离线全测绿：`pytest -m "not live"`（基线 S049 验收态）+ tsc + vitest
  - 后端 983 passed / 9 deselected；前端 36 files / 257 tests + tsc exit 0
- [x] A6 零新外部调用：shadow-comparison 只读 winrate.db/快照/workflow_state/K 线本地库

## 7. 合规与工程底线自查

- [x] 客观算账无方向结论；对照卡挂「历史统计特征，市场有风险，研究参考」（§12.3 口径）
- [x] 收益计算复用已验证函数，无心算/臆造；近似口径 UI 明示
- [x] winrate.db/workflow_state/快照均为 gitignored 私有数据，不上传不入 git
- [x] 无新增东财端点（本 spec 零新外部调用，em_get 条目不适用）

## 8. 测试计划

- `cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov` 全量
- 新增：迁移幂等 / 票根三分支 / shadow-comparison 算账 / 前端渲染 vitest
- 手动：dev server 实盘结算一笔 → 查票根列；简报页对照卡走查

## 9. 风险与回滚

- 快照缺失日（未采集）→ 该日 missed 桶不计算，`no_suggestion_days` 计数诚实返回
- K 线缺口 → 该标的排除 missed 统计，`missing_kline` 计数
- 战法 trades 回查性能：结算低频（每笔平仓一次），全量回测调用可接受；若实测慢再缓存
- 回滚：迁移只加列；端点/组件独立新增，revert commit 即可；attention_mode NULL 不影响既有结算

## 10. 明确不做（本 spec 外）

- 明日验证条件（D7d#4）→ W1 影子轨 spec
- 毕业判定/独立性自动决策（§12.4）→ ≥4 周数据后人工决策
- 票根修正端点、edge_family UI 选择 → backlog
- 推送通知 → W-C 二期
