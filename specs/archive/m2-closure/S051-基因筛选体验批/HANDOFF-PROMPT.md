# S051 实施交接提示词（交给新会话 Claude）

你接手 Vibe-Research 仓库（/Users/lizhiwei/project/code/stock/Vibe-Research）的 S051 实施（基因筛选体验批：阈值复位 + sanity 警告 + 分段切换 + 动态文案 + 零样本注记）。全程用中文与用户沟通。

## 任务
按同目录 `plan.md` 的阶段顺序（S1→S6）与 `task.md` 的原子任务 T1–T12 执行，每完成一项勾选 task.md 对应复选框。plan.md 的 D1–D5 是用户 grill 后锁定的决策，勿翻案。

## 开工必读
1. `specs/S051-基因筛选体验批/plan.md`——决策 D1–D5 + 现状事实（所有数字 2026-08-11 核实）
2. 同目录 `task.md`——原子任务与 commit 门
3. 根目录 `AGENTS.md`——分级工作流与提交纪律

## 现状
- git 在 develop。开工先 `git status` + `git log --oneline -5`：有并行会话在跑（S050 行为闭环扩展，BehaviorLoop 相关已陆续提交）
- **绝不 revert 他人改动**；GeneScreener.tsx/GeneFilterForm.tsx 若仍有他人未提交改动，在其之上继续（其方向与 D3 一致：默认分对齐后端阈值，但未解决空列表问题，你的分段逻辑会取代它）
- dev server :8900 在跑（uvicorn --reload + vite），勿杀；后端改代码自动热加载

## 关键代码事实（已核实，不必重复排查）
- 持久化参数 `backend/data/limitup_params.json` 现为 qualify=65/high=80（要复位 50/60）；复位必须走 `POST /api/limitup/screener/params`（routers/limitup/screener.py），该端点同步 ls 模块级变量+落盘，勿手改文件
- 今日 gene_scores（.vibe-research/gene_scores.db）99 行，max=64.39，qualify=3/high_gene=1——标志本就按 50/60 口径算的，复位后**无需触发重算**；150 日全局最高分 70.63（sanity 警告测试素材：high=80 必触发）
- `GET /api/limitup/screener` 返回**全量** gene_scores（service.py:204 get_screener_result，按 total_score 降序）+ qualified/high_gene 子列表——空列表纯是前端客户端硬筛造成，后端不用动
- 基因筛选页：`frontend/src/pages/limitup/GeneScreener.tsx`（doSearch 现按 minScore/maxScore 客户端过滤）+ `components/GeneFilterForm.tsx`（minScore 初值跟 getGeneParams）+ `components/GeneResultTable.tsx`（列表行渲染）
- 打板策略页：`frontend/src/pages/LimitUpStrategy.tsx`——两张摘要卡写死「SCORE ≥ 60（合格线）」「SCORE ≥ 75（高基因线）」，改动态
- 战法面板：`frontend/src/components/ui/WinRateComparePanel.tsx`（sample_size=0 现显示裸 "—"）；数据源 `useStrategyBacktest(60)`（lib/query/strategy.ts）→ `backend/routers/strategy.py:64 GET /api/strategy/backtest`（响应构建处加 note 透出）；STRATEGY_REGISTRY 在 `backend/limitup_strategy.py`（break_reseal:521 / reverse_package:545 / n_shape_counterattack:557）
- 零样本根因（写 note 用）：炸板后溢价因子近 60 日 2899 行全 0/NULL（数据管道疑 bug，S053 查因中）；N字反击条件结构矛盾（频次>30 与 zt_count≤10 互斥）
- 测试样板：后端 `backend/tests/test_limitup.py`；前端 vitest 参照 `frontend/src/components/ui/WinRateComparePanel.test.tsx`
- 测试命令：后端 `cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`；前端 `cd frontend && npx tsc --noEmit && npx vitest run`

## 硬约束
- AGENTS.md medium 流程门：develop 直提、勤 commit、最小功能提交（wip: 可）、绝不 revert 他人改动
- 合规底线：不臆造数据；零新外部调用（不得新增 em_get/网络请求）；页面保持「客观数据，非推荐」语义，不出现方向结论词
- note 文案是临时诚实标注（S053 查因后可能修订），代码注释注明
- 测试先行：每阶段相关测试绿后才 commit（G1–G5 门）

## 范围外（勿扩张）
- 炸板后溢价因子数据管道修复（S053 单独立项）、N字反击条件重定义（backlog）、基因权重/算法调整、其他页面改版

## 完成定义
- task.md T1–T12 全勾
- pytest + tsc + vitest 全绿
- :8900 冒烟：基因筛选页默认 3 只合格标的；"全部"模式 99 行带分（不合格置灰+标记）；打板策略卡片显示 ≥50/≥60；战法面板三条零样本注记
- 最终 commit `feat(S051): ...`

执行顺序 S1→S6，阶段门与风险见 plan.md。
