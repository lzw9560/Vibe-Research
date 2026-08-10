# S050 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。每任务=最小可验证改动；按 stage 分组，stage 末 commit。
> 测试基线：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`（S049 验收后全绿起点）。
> 纪律：不碰并行会话未提交改动（seat_profiles.json / GeneScreener.tsx / GeneFilterForm.tsx / docs/superpowers/plans/）。

## S1 DB 层（迁移 + Record 扩列）

- [ ] T1 新增 `backend/migrations/win_rate_tracker/20260811-003_add_signal_attribution.sql`：
  `ALTER TABLE winrate_records ADD COLUMN` ×5（signal_source TEXT / signal_ref TEXT / edge_family TEXT / target_holding_period TEXT / attention_mode TEXT）
  - 验证：SQL 可被 MigrationManager 执行两遍不报错（幂等由 manager 版本表保证）
- [ ] T2 `backend/win_rate_tracker.py`：migrations 列表注册 003 + `WinRateRecord` dataclass 扩 5 字段（Optional 默认 None/''）+ `add_record` INSERT 扩列
  - 验证：新增 `backend/tests/test_s050_migration.py`——旧库升级后 legacy 行 5 列 NULL；新记录写入回读一致；get_stats 不崩（NULL 兼容）
- [ ] G1 commit 门：win_rate_tracker + 新迁移测试绿（`pytest backend/tests/test_s050_migration.py -m "not live"`）

## S2 结算票根（后端核心）

- [ ] T3 新增 `backend/snapshot_store.py`：`load_snapshot(date)` / `list_snapshot_dates()`（逻辑自 `routers/workflow.py` 平移，原处改 import，行为零变化）
  - 验证：既有 workflow 快照相关测试全绿（纯重构）
- [ ] T4 `backend/settlement_recorder.py::record_settlement` 票根关联：
  - snapshot_store.load_snapshot(trade_date) 的 final_candidates 含 code → signal_source='funnel_candidate'，signal_ref='funnel:final'
  - 否则 `strategies/strategy_backtest.py` trades 含 (trade_date, code)（用户填的 strategy 对应回测）→ 'strategy_hit'，signal_ref=战法码
  - 皆无 → 'feeling'；任何查找异常 → 兜底 'feeling' + logger.debug（不阻塞结算）
  - edge_family 推断：funnel_candidate→'momentum_premium'；strategy 属 value 类→'mean_reversion'；其余 ''
  - target_holding_period 推断：funnel/动量战法→'T+1'；value 类→'20-60d'；其余 ''
  - 验证：新增 `backend/tests/test_s050_ticket_stub.py`——三分支 + edge_family/holding_period 推断 + 异常兜底（mock snapshot/trades）
- [ ] T5 attention_mode 透传链：
  - `backend/workflow_state_repo.py::_ensure_columns` 加 ("attention_mode", "TEXT")
  - `backend/routers/workflow.py` TransitionRequest（或既有流转请求模型）加 attention_mode 可选字段 → transition 落 state 行
  - record_settlement 从 state 行读 attention_mode 写入 WinRateRecord（缺省 'A'）
  - 验证：transition→settled 透传单测；旧请求不带字段默认 'A' 不报错
- [ ] G2 commit 门：settlement_recorder + workflow 相关测试全绿（含 test_s034/s038 回归）

## S3 影子对照端点

- [ ] T6 `backend/routers/win_rate.py` 新增 `GET /api/winrate/shadow-comparison?window_days=28`：
  - follow 桶：winrate_records signal_source ∈ (funnel_candidate, strategy_hit)，窗口按 entry_date
  - feeling 桶：signal_source='feeling'；legacy（NULL）单列不计入两桶
  - missed 桶：窗口内每个有快照日，final_candidates codes − 当日 workflow_state holding/settled codes → 逐只 `backtest_lite._calc_next_day_return`（None 计入 missing_kline 排除）
  - independence：agreement_rate = follow_n/(follow_n+feeling_n)（分母 0 → null）；feeling_win_rate
  - 诚实标记：任一桶 n<5 → sufficient=false；无快照交易日计数 no_suggestion_days
  - 验证：新增 `backend/tests/test_s050_shadow_comparison.py`——fixture 造三桶数据算账准确 + K 线缺失排除 + 无快照日排除 + n<5 标记
- [ ] G3 commit 门：win_rate router 全部测试绿

## S4 前端对照卡 + 表单字段

- [ ] T7 `frontend/src/lib/api/`：ShadowComparison 类型 + useShadowComparison hook（window_days 参数，沿用现有 useQuery 模式）
  - 验证：tsc 过
- [ ] T8 `frontend/src/pages/workflow/PreMarketBriefing.tsx` 新增 ShadowComparisonSection（置于战法胜率对比区下方，可折叠）：
  - 三桶表（n/胜率/均收益）+ missed 影子口径说明（"信号日收盘→次日收盘，近似"）+ 一致率 + sufficient=false 显示"样本不足，仅观察"+ 教学一句话 + 「历史统计特征，市场有风险，研究参考」
  - 验证：vitest 渲染测试——三桶数值呈现 / 样本不足文案 / 无数据时空态
- [ ] T9 结算表单 attention_mode：settled 流转表单（workflow 组件内 entry/exit 价格表单同处）加 A/B/C 单选，默认 A，随流转请求提交
  - 验证：vitest 或 tsc + dev server 手动走查
- [ ] G4 commit 门：tsc + vitest 全绿

## S5 全量回归 + 冒烟验收

- [ ] T10 `pytest -m "not live"` 全量绿（对比 S049 基线无回归）；`cd frontend && npx tsc --noEmit && npx vitest run`
- [ ] T11 dev server :8900 冒烟：盘前简报页对照卡渲染；真实结算一笔 → winrate_records 票根列正确（signal_source/edge_family/attention_mode）
- [ ] T12 spec.md/task.md 勾选验收状态 + 收尾 commit（docs(S050): 验收）
- [ ] G5 验收门：spec §6 A1-A6 全勾
