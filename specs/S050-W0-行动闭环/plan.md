# S050 实施计划（plan）

> 配套 `spec.md` 与 `task.md`。流程门 medium：develop 直提；勤 commit、最小功能提交；
> 验收＝离线全测 + tsc/vitest + dev server 冒烟（用户走查）。
> 依赖现状：S049 已合并（快照 funnel_layers + 战法 trades 三字段在 develop）。

## 阶段划分（按依赖排序）

### S1 · DB 层——迁移 003 + Record 扩字段
- 新建 `20260811-003_add_signal_attribution.sql`（winrate_records 加 5 列，全可空）
- `win_rate_tracker.py`：注册迁移 + `WinRateRecord` 扩 5 个 Optional 字段 + `add_record` INSERT 扩列
- 测试：迁移幂等（连跑两次）+ 旧行 NULL + 新记录写入回读
- **commit 点**：win_rate_tracker 相关测试绿

### S2 · 结算票根关联
- 抽 `backend/snapshot_store.py`：`load_snapshot(date)` / `list_snapshot_dates()` 从 `routers/workflow.py` 平移（原处改 import，行为不变；避免 settlement_recorder → routers 反向依赖）
- `settlement_recorder.record_settlement`：票根三分支（快照 final_candidates 命中 → funnel_candidate；战法 trades 命中 → strategy_hit；皆无 → feeling）+ edge_family 推断 + signal_ref 落来源引用
- `workflow_state_repo._ensure_columns` 加 `attention_mode`；`routers/workflow.py` TransitionRequest 加可选 `attention_mode`（默认 A）→ 落 state 行 → 结算透传 winrate_records
- 测试：票根三分支单测（mock 快照/trades）+ attention_mode 透传
- **commit 点**：结算/状态机相关测试绿

### S3 · 影子对照端点
- `routers/win_rate.py` 新增 `GET /api/winrate/shadow-comparison?window_days=28`：
  - follow 桶（signal_source ∈ funnel_candidate/strategy_hit）/ feeling 桶：winrate_records 聚合 n/胜率/均收益
  - missed 桶：窗口内各快照日 final_candidates − 当日 holding codes → `_calc_next_day_return` 影子收益（None 排除计数 missing_kline）
  - independence：agreement_rate = follow_n/(follow_n+feeling_n)、feeling_win_rate
  - 诚实性：桶 n<5 → sufficient=false；窗口日无快照 → no_suggestion_days 计数；只读本地私有库零外呼
- 测试：fixture 三桶算账 + 无快照日排除 + K 线缺失排除 + 样本不足标记
- **commit 点**：win_rate router 测试绿

### S4 · 前端对照卡 + 表单字段
- `frontend/src/lib/api/`：`ShadowComparison` 类型 + `useShadowComparison` hook
- `PreMarketBriefing.tsx` 加 `ShadowComparisonSection`（折叠，置战法胜率对比区下方）：三桶表 + 一致率 + 样本不足标记 + 教学一句话 + 「历史统计特征，市场有风险」
- 结算表单（holding/settled 流转）加 attention_mode A/B/C 选择，默认 A
- 测试：vitest 渲染（三桶 + 样本不足文案）+ tsc 绿
- **commit 点**：前端测试绿

### S5 · 全量回归 + 冒烟
- `pytest -m "not live"` 全量绿（基线：S049 验收后全绿）
- vitest run + tsc
- dev server :8900 简报页对照卡冒烟 + 一笔真实结算验票根列（用户走查）
- spec/task 勾选验收，归档

## 串行纪律与边界

- W0 观察期 ≥4 周是**数据积累期**，不是开发期：本 spec 交付后进入观察，期间不启动 W1/W-C 开发（§10.2 串行纪律）；观察期内的 bugfix 按 small/medium 直提。
- 不做清单（spec §10 已载）：票根人工修正端点、edge_family UI 选择、毕业逻辑、次日验证条件（D7d#4，W1）、推送。
