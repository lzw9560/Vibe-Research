# S051 实施计划（plan）——基因筛选体验批

> 级别 medium：develop 直提，勤 commit、最小功能提交。
> 来源：2026-08-11 grill 会话 5 点反馈之 #1/#3(面板)/#4（Q2/Q3/Q5 裁决）。
> 验收＝离线全测 + tsc/vitest + dev server :8900 冒烟（用户走查）。

## 已核实事实（实施时不必重查）

- `backend/data/limitup_params.json` 现为 qualify=65/high=80；近 150 日全局最高分 70.63，
  ≥80 共 0 行，≥65 仅 10/150 天 → 默认视图 93% 日子空列表（用户反馈 #4 根因）。
- DB `gene_scores` 现存 qualify/high 标志按 qualify≥50/high≥60 算（今日合格 3 只：
  603221 爱丽家居 64.39 / 600721 百花医药 55.05 / 002552 宝鼎科技 50.72）→ 复位 50/60 无需立即重算。
- router pydantic 默认已是 50/60（`routers/limitup/screener.py` LimitUpParamsBody）。
- 前端 `GeneScreener.tsx`/`GeneFilterForm.tsx` 在交接时**可能有并行会话（S050 行为闭环）的
  未提交改动**（方向：minScore 对齐后端参数）。先 `git status` 确认；有则在其之上开工，绝不 revert。
- `LimitUpStrategy.tsx` 摘要卡写死「SCORE ≥ 60（合格线）」「SCORE ≥ 75（高基因线）」——与任何口径都不一致的死文案。
- 「战法胜率对比」60 日窗口数据已在（useStrategyBacktest(60)）；零样本 3 战法：
  break_reseal/reverse_package（炸板后溢价因子 60 日全 0，根因归 S053）、
  n_shape_counterattack（条件自相矛盾：涨停频次>30 ∧ zt_count_250d≤10，挂起待重定义）。

## 阶段划分（按依赖排序）

### S1 · 阈值复位 50/60（运行时+持久化一次到位）
- 调 `POST /api/limitup/screener/params` 写回 {qualify:50, high:60, lookback:252}
  （该端点同时更新模块级变量与文件，勿手改 JSON——运行中进程的模块值也要同步）。
- 校验：`GET /api/limitup/screener/params` 返回 50/60；今日 qualify 计数不变（标志本就 50/60 口径）。
- **commit 点**：参数复位说明（commit message 记 grill 裁决 Q2=C）。

### S2 · 阈值保存 sanity 警告
- `POST /api/limitup/screener/params`：保存前查 gene_scores 近 30 日 MAX(total_score)；
  gene_high_threshold > 该值 → 响应加 `warning`（"近30日最高分 X，此阈值下高基因恒为空"）；
  qualify 同理。仍保存，不阻断。
- 前端 GeneFilterForm「保存并重算」回显 warning。
- 测试：阈值越界返 warning + 正常保存不受影响。
- **commit 点**：router 测试绿。

### S3 · 基因筛选页分段视图（Q3 裁决）
- `GeneFilterForm`/`GeneScreener`：结果区加分段 `[合格 | 全部 | 自定义分数段]`，默认「合格」。
  - 合格：按后端 `qualify` 标志过滤（不再用分数区间硬筛）。
  - 全部：全量按分降序；未合格行得分置灰 + 「未合格」标记（Q：不满足也要展现得分）。
  - 自定义：保留现有 minScore/maxScore 输入。
- 摘要行 扫描N/合格M/高基因K 随分段不变（始终全量统计）。
- 并行会话的 minScore 对齐逻辑被分段控制取代——保留其 getGeneParams 初始化骨架。
- 测试：vitest 三态渲染 + 默认合格 + 全部视图含未合格行。
- **commit 点**：前端测试绿。

### S4 · 打板策略页摘要卡文案动态化
- `LimitUpStrategy.tsx`：两卡阈值文案改读 `GET /api/limitup/screener/params`（useQuery），
  删写死 60/75。清单本身（全量得分展示）不动。
- **commit 点**：tsc/vitest 绿。

### S5 · 战法胜率面板零样本诚实标注（Q5 裁决第 3 档）
- `STRATEGY_REGISTRY`（limitup_strategy.py）三条目加 `note` 字段：
  break_reseal/reverse_package → "60日无信号·疑似炸板后溢价因子缺供（S053 排查中）"；
  n_shape_counterattack → "条件待重定义（需K线形态识别）"。
- `/api/strategy/backtest` 透出 note；WinRateComparePanel 零样本行显示 note 替代裸 "—"。
- 测试：note 透出 + 面板渲染。
- **commit 点**：相关测试绿。

### S6 · 回归 + 冒烟
- `cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov` 全绿。
- `cd frontend && npx tsc --noEmit && npx vitest run` 绿。
- :8900 走查：基因筛选默认 3 只合格；切全部见 99 只带分；打板页卡文案 50/60；面板零样本有标注。

## 边界

- 不动并行会话文件：`BehaviorLoop.tsx`、winrate 组件、`docs/superpowers/plans/`。
- 不做：炸板后溢价数据管道修复（S053）、N字反击重定义（backlog）、快照回填（S052）。
