# S049 实施计划（plan）

> 配套 `spec.md` 与 `task.md`。子项 A 已实现（`89768c2`）。本计划覆盖 B/C/D。
> 流程门（用户确认降级 medium）：develop 直提；勤 commit、最小功能提交；验收＝离线全测 + tsc/vitest + dev server 冒烟。

## 阶段划分（按依赖排序）

### S1 · 后端子项 B —— 情绪梯队语义 + market_emotion 重写
- models.py 删个股三率；board_ladder 只返 lianban_stocks + 共享 TTL 缓存 `get_market_emotion_raw`（与 D6 去重共用）
- workflow.py `_fetch_market_emotion` 重写：STI compute（复用同一份 emotion，不重复外调）+ 三率 + ladder + 涨跌停家数
- 测试：live 契约改写、funnel fixture、新增 _fetch_market_emotion 单测
- **commit 点**：candidate_funnel + workflow 相关测试绿

### S2 · 后端子项 D 采集层 —— 全参数 passed dict + 采集去重
- funnel.py 三层 passed dict 扩全参数（D1）
- run_funnel (date,config) TTL 缓存（D6）；`_build_funnel_layers` 命中
- live done 响应带 funnel_layers（D5）
- **commit 点**：candidate_funnel 全量绿

### S3 · 后端 D 状态机 + 战法明细
- WATCHING→CANDIDATE（D9）；strategy_backtest trades 补 date/code/name + 懒加载端点（D8）
- **commit 点**：相关测试绿

### S4 · 后端子项 C —— 诊断时点 + 快照诊断卡
- fetcher 暴露 `_as_of`；diagnose as_of=min(dates)；快照存 diagnosis_cards（C4）
- **commit 点**：相关测试绿

### S5 · 后端全量回归
- `pytest -m "not live"` 全绿（基线：158 passed 为 candidate_funnel+eastmoney 子集；全量另行统计）

### S6 · 前端 B —— types + 简报页
- types.ts 补字段；市场情绪区重写（STI+三率+ladder+涨跌停，缺数据 "--"）；因子段跳 candidate_funnel 卡（D3）；读 briefing.funnel_layers 不发 GET（D4）
- **commit 点**：tsc + vitest 绿

### S7 · 前端 FunnelMatrix
- 新组件：三列矩阵 + 全参数列 + 状态 chips（D2/D7）；PreMarketBriefing 替换 CandidateFunnelEmbed
- **commit 点**：组件测试绿

### S8 · 前端 战法展开 + 抽屉 + 状态卡
- WinRateComparePanel 展开（当日命中建仓 + 回溯明细懒加载）（D8）
- CandidateDetail：date 透传 + 快照卡优先 + 情绪梯队只留 consec_boards + auction_open_pct（C1/C4/B6）
- WorkflowStateCard 取消观察/取消选中（D9）；FunnelLayerCard 紧凑化（D10）
- **commit 点**：tsc + vitest 全绿

### S9 · 验收收口
- dev server（:8900）冒烟：触发 run 一次 → 市场情绪区/矩阵/展开/取消/抽屉全链路
- 勾选 spec A1-A12 + task.md 全 ✅ → 最终 commit

## 依赖关系

- S1→S2 共享 `get_market_emotion_raw`；S1 先落
- S6/S7/S8 依赖对应后端字段契约（S2 passed dict / S3 trades+状态 / S4 diagnosis_cards）
- S5 在 S1-S4 后；S9 在全部后
- 并行会话未提交改动勿动：`backend/seat_profiles.json`、`frontend/src/pages/limitup/GeneScreener.tsx`、`GeneFilterForm.tsx`、`docs/superpowers/plans/`

## 风险与对策

| 风险 | 对策 |
|---|---|
| market._emotion 偶发限流返空 | TTL 缓存 + 重试一次；空则 missing 透明 |
| 矩阵全参数列横向溢出 | overflow-x-auto + 列宽紧凑；移动端横向滚 |
| 回溯明细样本少（DB 已有天数） | 端点带 available_days，前端如实标"样本 N 天" |
| run_funnel 缓存跨 run 串数据 | 缓存键含 config dict 排序 JSON；TTL 5 分钟；done 即清 |
| STI compute 需 _sentiment(date) | 与 emotion 同 try 块，任一失败降级 missing，不影响三率/ladder |
