# S093 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。每任务=最小可验证改动；按 stage 分组，stage 末 commit。
> 测试基线：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`（2152 passed 起点）。
> 前端测试：`cd frontend && npx tsc --noEmit && npx vitest run`（404 passed 起点）。
> feature 分支：`feature/S093-内容重组与飞书通知`（off develop）。

## S1 后端 stage 修订（与 S2 可并行）

- [x] T1 `backend/vr_paths.py`：resolve_date_triplet stage 边界修订
  - pre_market: now < 09:00；pre_open: 09:00-09:30（新增）；intraday: 09:30-15:30；post_transition: 15:30-17:15；post_market: ≥17:15
  - 定时器推进点 15:00→15:30（`_next_advance_epoch(15,30)` + L173 `_time(15,0)`→`_time(15,30)`）
  - today 条件加 pre_open（L183 `stage in ("pre_market", "pre_open", "intraday")`）
  - 验证：新建 `test_s093_stage.py`——pre_open 新分支 + intraday 15:30 边界 + post_transition 15:30 边界 + 定时器 15:30
- [x] T2 `backend/tests/test_s092_date_triplet.py`：~20 处断言旧边界适配（09:30→09:00/15:00→15:30）
  - 验证：`pytest tests/test_s092_date_triplet.py -m "not live"` 全绿
- [x] T3 `backend/config/__init__.py`：INTRADAY_SAMPLE_INTERVALS 末窗 `("14:30", "15:00", 5)`→`("14:30", "15:30", 5)`
- [x] T4 `backend/routers/intraday_sentiment.py`：采样器注释 09:25-15:00→09:25-15:30 + 快照扩字段透传 zb_count/ladder
  - 验证：`pytest tests/test_s093_stage.py -m "not live"` 快照字段断言
- [x] G1 commit 门：stage 修订测试绿

## S2 后端飞书通知 + 规则引擎（与 S1 可并行）

- [x] T5 `backend/risk/bomb_alert_rules.py`：加 C7(涨停/INFO)/C8(情绪恶化:天气降1档/MEDIUM)/C9(连板断裂/MEDIUM) + 修涨跌比口径(zt_count/zb_count，不用 ad_ratio)
  - C8 触发条件：天气从晴→阴或阴→暴风雨降 1 档（极端反弹/未知不触发）
  - C9 触发条件：最高板>3 且无 2 板接力
  - 验证：新建 `test_s093_bomb_alert_ext.py`——C7/C8/C9 触发 + 不触发
- [x] T6 `backend/risk/bomb_alert_dispatcher.py`：规则触发时接 NotificationService.send() 推飞书卡片
  - 验证：mock NotificationService.send()，断言被调
- [x] T7 `backend/scheduled_tasks.py`：candidate_funnel_precompute success 后调 NotificationService.send() 发富内容卡片 + 扩返候选统计 + 新 task type daily_ai_summary（R12 stub，cron 15:30）
  - 富内容：F 日期 + final_candidates 数 + 双重确认数 + top5 标的
  - daily_ai_summary stub：`generate_daily_summary(date) -> str` 返空串 + 存储位 `.vibe-research/daily_summaries/{date}.txt`
  - 验证：新建 `test_s093_notification.py`——通知触发 + 内容断言 + daily_ai_summary stub
- [x] T8 `backend/routers/workflow.py`：快照路径补透传 `snap.get("final_candidates")`（L576-595 区域）+ live-done 路径 `_cache.update` 补
  - 验证：`pytest tests/test_workflow_snapshot.py -m "not live"` 快照 final_candidates 断言
- [x] T9 `backend/strategies/premarket_selection.py`：breakout name 空值修复（从 gene_scores 表补名）
  - 验证：`select_premarket_candidates('2026-08-21', min_score=0.9)` 返回的 candidates name 非空
- [x] T10 `backend/config.py` + `backend/config/__init__.py`：删除 VR_FEISHU_WEBHOOK 读取逻辑 + feishu_notifier.py 标 deprecated（不删文件）
  - 验证：grep `VR_FEISHU_WEBHOOK` 无新引用
- [x] G2 commit 门：通知 + 规则引擎测试绿

## S3 前端前瞻 Tab 重构（依赖 S1+S2）

- [x] T11 `frontend/src/components/workflow/CandidateFunnelEmbed.tsx`：从 PreMarketBriefing 私有函数抽为可复用组件
  - 验证：tsc 过
- [x] T12 `frontend/src/lib/query/useCrossValidation.ts`：新建共享交集 hook `useCrossValidationGroups(F, forward)` 返回 dual/funnelOnly/breakoutOnly 三组
  - 验证：tsc 过
- [x] T13 `frontend/src/components/workflow/CrossValidationBadge.tsx`：新建交叉验证徽章组件（双重确认绿/仅漏斗灰/仅breakout灰）
  - 验证：vitest 渲染测试
- [x] T14 `frontend/src/pages/Workflow.tsx`：前瞻 Tab 重构
  - 补：CandidateFunnelEmbed(date=F) + StrategyMatchMatrix(date=F) + PremarketSelectionSection(date=forward) + CrossValidationBadge
  - 辅助折叠区：WeatherDecisionBar + P2RiskPanel + advisory + T1Tab + ContextTab
  - 删：战法战绩折叠区（移 /strategy）
  - stage→Tab 高亮加 pre_open + stageLabel 加 pre_open
  - 验证：vitest 覆盖前瞻 Tab 渲染 + stage 高亮 + pre_open
- [x] T15 `frontend/src/pages/workflow/PreMarketBriefing.tsx`：选股决策内容迁出（~70% 迁前瞻/复盘/战法页）
  - 迁出：CandidateFunnelEmbed/StrategyMatchMatrix/WeatherDecisionBar/P2RiskPanel/T1Tab/ContextTab/WinRateCompareSection
  - 保留：盯盘入口卡片（改全天可见）+ 持仓 chips
  - 验证：tsc 过 + 既有测试适配
- [x] G3 commit 门：前瞻 Tab 重构测试绿

## S4 前端当日 Tab 重构（依赖 S3）

- [x] T16 `frontend/src/components/workflow/WatchlistBoard.tsx`：新建——前瞻结论标的看板（三组分组+交集+实时价格）
  - 三组：双重确认(漏斗∩breakout) / 仅漏斗 / 仅breakout
  - 每只票：实时价格/涨跌幅/封板状态/持仓状态（tencent_quote 轮询 pre_open+intraday 时段）
  - 点击跳 IntradayMonitor 个股详情
  - 验证：vitest 渲染测试
- [x] T17 `frontend/src/pages/workflow/PreMarketBriefing.tsx`：改为盯盘执行台
  - WatchlistBoard + 持仓 chips（useWorkflowStates）+ 市场情绪实时指标（intraday_sentiment）+ 盯盘入口全天可见（删 isIntraday 门控）
  - 验证：vitest 覆盖盯盘看板渲染 + 盯盘入口全天可见
- [x] T18 `frontend/src/pages/workflow/PostMarketReview.tsx`：加行为对照卡（ShadowComparisonSection）
  - 验证：vitest 渲染测试
- [x] G4 commit 门：当日 Tab 重构测试绿

## S5 前端战法独立页 + 路由（与 S4 可并行）

- [x] T19 `frontend/src/pages/StrategyPage.tsx`：新建——/strategy 独立路由页
  - 战法战绩表（registry+backtest query 从 Workflow.tsx 迁入）+ 前向测试入口 + 阈值配置入口
  - 验证：tsc 过
- [x] T20 `frontend/src/router.tsx`：加 /strategy 路由
  - 验证：tsc 过
- [x] T21 `frontend/src/pages/Workflow.tsx`：公共区加战法入口 EntryCard（锚条下方常驻）
  - 验证：vitest 渲染测试
- [x] G5 commit 门：战法独立页测试绿

## S6 全量回归 + 冒烟验收

- [x] T22 `pytest -m "not live"` 全量绿
- [x] T23 `vitest run` + `tsc --noEmit` 全绿
- [x] T24 dev server 冒烟（AC1-AC11）：
  - AC1 stage 枚举正确
  - AC2 前瞻 Tab pipeline 完整
  - AC3 当日 Tab = 盯盘执行台
  - AC4 战法战绩移出 → /strategy
  - AC5 行为对照卡在复盘
  - AC6 盯盘入口全天可见
  - AC7 飞书通知推送
  - AC8 C1-C6+C7/C8/C9 规则触发
  - AC9 交叉验证徽章
  - AC10 离线全测绿
  - AC11 dev server 冒烟
- [x] T25 spec.md/task.md 勾选验收 + 归档 + MILESTONES 更新 + 文档同步（`docs(S093): 验收 + 归档`）
- [x] G6 验收门：AC1-AC11 全过

## 依赖图

```
S1(T1→T2→T3→T4) ──┐
                  ├──→ S3(T11→T12→T13→T14→T15) ──┐──→ S4(T16→T17→T18) ──┐
S2(T5→T6→T7→T8→T9→T10) ──┘                        │                     ├──→ S6(T22→T23→T24→T25)
                                                  S5(T19→T20→T21) ──────┘
```

并行策略：S1+S2 并行 → S3 → S4+S5 并行 → S6。
