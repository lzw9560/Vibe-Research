# S051 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。每任务=最小可验证改动；按 stage 分组，stage 末 commit。
> 测试基线：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`；前端 `npx tsc --noEmit && npx vitest run`。
> 纪律：开工前 `git status`；并行会话文件（BehaviorLoop/行为闭环相关、seat_profiles.json）勿动；
> GeneScreener.tsx/GeneFilterForm.tsx 若有他人未提交改动，在其之上继续或等待，绝不 revert。

## S1 参数复位（D1）

- [x] T1 阈值复位 50/60：调 `POST /api/limitup/screener/params`（body: gene_qualify_threshold=50, gene_high_threshold=60, lookback_days=252）——该端点同时更新 ls 模块级变量 + 持久化 `backend/data/limitup_params.json`（勿手改文件绕过端点，否则运行中后端模块变量不同步）
  - 验证：GET 同端点返回 50/60；文件内容已更新；今日 DB qualify/high 标志本就是 50/60 口径算的（3 合格/1 高基因），**无需触发重算**
- [x] G1 commit 门：params 端点既有测试绿 + 文件 diff 只有两个数字

## S2 阈值 sanity 警告（D2）

- [x] T2 `backend/routers/limitup/screener.py::save_limitup_screener_params`：保存前查 gene_scores 近 30 日 max(total_score)；gene_high_threshold > max → warnings 加「高基因阈值 X 高于近30日最高分 Y，high_gene 将恒为空」；qualify 同理。响应体加可选 `warnings: list[str]`（向后兼容）
  - 验证：新增单测——high=80 返回 warning；high=55 无 warning；warnings 不影响保存成功
- [x] T3 前端 GeneFilterForm：recompute 响应带 warnings 时以警告样式显示在 recomputeMsg 区（沿用现有提示位）
  - 验证：vitest 渲染 warning 文案
- [x] G2 commit 门：后端单测 + 前端测试绿

## S3 基因筛选页分段切换（D3）

- [x] T4 `GeneScreener.tsx`：加 viewMode ∈ {qualified, all, custom}，默认 qualified；doSearch 始终拉全量 gene_scores（删除按 minScore/maxScore 的客户端硬筛），qualified 模式按 `g.qualify` 过滤，all 模式全量，custom 模式走 minScore/maxScore；三种模式均按 total_score 降序
  - 注意：并行会话未提交改动把首次检索改为"getGeneParams 返回后按 qualify 阈值触发"——本任务以 qualify 标志过滤取代该逻辑，保留其"不硬编码阈值"的意图
- [x] T5 `GeneFilterForm.tsx`：分段控件 [合格 | 全部 | 自定义分数段]（参照项目内 SegmentedControl/TabBar 既有范式）；min/max 输入仅 custom 模式生效；「筛选」按钮触发 onSearch 携 viewMode
- [x] T6 `GeneResultTable.tsx`：不合格行视觉降级（得分置灰 + 「未合格」小标签），qualify/high_gene 徽章保留；空态文案区分「今日无合格标的」vs「无数据」
  - 验证：vitest 三模式渲染——qualified 只出 qualify=true 行 / all 出全量且不合格行有标记 / custom 按分数区间
- [x] G3 commit 门：前端测试 + tsc 绿

## S4 打板策略页摘要卡动态文案（D4）

- [x] T7 `LimitUpStrategy.tsx`：加载时 GET /api/limitup/screener/params，摘要卡文案改「SCORE ≥ {qualify}（合格线）」「SCORE ≥ {high}（高基因线）」；请求失败降级为不显示具体数字（只留"合格线/高基因线"字样），不写死 60/75
  - 验证：vitest mock params 返回 50/60 → 文案随之变
- [x] G4 commit 门：前端测试绿

## S5 战法面板零样本诚实注记（D5）

- [x] T8 `backend/limitup_strategy.py` STRATEGY_REGISTRY：break_reseal/reverse_package 加 note「60日无信号：炸板后溢价因子疑似缺供（S053 查因中）」；n_shape_counterattack 加 note「60日无信号：条件定义待重定义」；`routers/strategy.py::strategy_backtest` 响应每项透出 note（无则空串）
- [x] T9 `WinRateComparePanel.tsx`：sample_size=0 行在战法名下小字显示 note；`StrategyBacktestItem` 类型加 note?: string
  - 验证：后端响应测试 + vitest 渲染 note
- [x] G5 commit 门：相关测试绿

## S6 全量回归 + 冒烟

- [x] T10 pytest 全量 + tsc + vitest 全绿（对比开工基线无回归）
- [x] T11 dev server :8900 冒烟（用户走查）：基因筛选页默认合格标的（2026-08-12 实际 2 只：600721 百花医药 58.81 / 605179 一鸣食品 52.35，spec 写"3 只"基于 8-11 的 99 行数据，今日 58 行数据量不同非 bug）；切"全部"出 58 行带分；打板策略卡片 50/60；面板三条注记（break_reseal/reverse_package/n_shape_counterattack）
- [x] T12 task.md 勾选 + 收尾 commit（feat(S051): ...）
