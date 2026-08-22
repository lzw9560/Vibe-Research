# S093 实施计划（plan）

> 配套 `spec.md`。流程门 large：feature 分支 `feature/S093-内容重组与飞书通知`；完整 grill 已闭合（Oracle 4 轮 + grill 自查 1 轮）；playwright 验收。
> 依赖现状：S092 已合并（dateTriplet + today_status + TaskStatusCard + useMarketClock + 三 Tab 容器均在 develop）。
> 审查状态：spec 经 Oracle 4 轮审查全部闭合，关键词反向扫描零残留，可进 plan。

## 阶段划分（按依赖排序）

### S1 · 后端 stage 修订（地基，无前端依赖）
- `backend/vr_paths.py`：resolve_date_triplet stage 边界修订
  - pre_market: now < 09:00（含隔夜）
  - pre_open: 09:00 ≤ now < 09:30（新增）
  - intraday: 09:30 ≤ now < 15:30（延长 30 分钟）
  - post_transition: 15:30 ≤ now < 17:15（推迟 30 分钟）
  - post_market: now ≥ 17:15
  - 定时器推进点 15:00→15:30（`_next_advance_epoch(15,30)` + L173 `_time(15,0)`→`_time(15,30)`）
  - today 条件加 pre_open（L183 `stage in ("pre_market", "pre_open", "intraday")`）
- `backend/config/__init__.py`：INTRADAY_SAMPLE_INTERVALS 末窗 `("14:30", "15:00", 5)`→`("14:30", "15:30", 5)`
- `backend/routers/intraday_sentiment.py`：采样器注释 09:25-15:00→09:25-15:30 + 快照扩字段透传 zb_count/ladder
- `backend/tests/test_s092_date_triplet.py`：~20 处断言旧边界适配
- 测试：`pytest tests/test_s092_date_triplet.py tests/test_s093_stage.py`（新建）
- **commit 点**：stage 修订测试绿

### S2 · 后端飞书通知 + 规则引擎（与 S1 可并行，写域不冲突）
- `backend/risk/bomb_alert_rules.py`：加 C7(涨停)/C8(情绪恶化:天气降1档)/C9(连板断裂) + 删北向 + 修涨跌比口径(zt_count/zb_count)
- `backend/risk/bomb_alert_dispatcher.py`：规则触发时接 NotificationService.send() 推飞书
- `backend/scheduled_tasks.py`：candidate_funnel_precompute success 后调 NotificationService.send() 发富内容卡片 + 扩返候选统计 + 新 task type daily_ai_summary（R12 stub）
- `backend/routers/workflow.py`：快照路径补透传 final_candidates（L576-595 区域，一行）+ live-done 路径补
- `backend/strategies/premarket_selection.py`：breakout name 空值修复（从 gene_scores 补名）
- `backend/config.py` + `backend/config/__init__.py`：删除 VR_FEISHU_WEBHOOK 读取逻辑 + feishu_notifier.py 标 deprecated
- `backend/tests/test_s093_bomb_alert_ext.py`（新建）+ `backend/tests/test_s093_notification.py`（新建）
- **commit 点**：通知 + 规则引擎测试绿

### S3 · 前端前瞻 Tab 重构（依赖 S1+S2）
- `frontend/src/components/workflow/CandidateFunnelEmbed.tsx`：从 PreMarketBriefing 私有函数抽为可复用组件
- `frontend/src/lib/query/useCrossValidation.ts`：新建共享交集 hook
- `frontend/src/components/workflow/CrossValidationBadge.tsx`：新建交叉验证徽章组件
- `frontend/src/pages/Workflow.tsx`：前瞻 Tab 重构——补漏斗(date=F)+战法匹配(date=F)+交叉验证徽章+辅助折叠区(天气/P2/advisory/T1/语境)；删战法战绩折叠区(移/strategy)；stage→Tab 高亮加 pre_open；stageLabel 加 pre_open
- `frontend/src/pages/workflow/PreMarketBriefing.tsx`：选股决策内容迁出（~70% 迁前瞻/复盘/战法页）
- **commit 点**：前瞻 Tab 重构测试绿

### S4 · 前端当日 Tab 重构（依赖 S3）
- `frontend/src/components/workflow/WatchlistBoard.tsx`：新建——前瞻结论标的看板（三组分组+交集+实时价格）
- `frontend/src/pages/workflow/PreMarketBriefing.tsx`：改为盯盘执行台（WatchlistBoard+持仓chips+市场情绪+盯盘入口全天可见）
- `frontend/src/pages/workflow/PostMarketReview.tsx`：加行为对照卡（ShadowComparisonSection）
- **commit 点**：当日 Tab 重构测试绿

### S5 · 前端战法独立页 + 路由（依赖 S3）
- `frontend/src/pages/StrategyPage.tsx`：新建——/strategy 独立路由页（战法战绩+前向测试+阈值配置入口），registry/backtest query 从 Workflow.tsx 迁入
- `frontend/src/router.tsx`：加 /strategy 路由
- `frontend/src/pages/Workflow.tsx`：公共区加战法入口 EntryCard（锚条下方常驻）
- **commit 点**：战法独立页测试绿

### S6 · 全量回归 + 冒烟
- `pytest -m "not live"` 全量绿
- `vitest run` + `tsc --noEmit` 全绿
- dev server 冒烟（三 Tab 内容 + stage 修订 + 飞书通知发送 + AC1-AC11）
- spec 验收 + 归档 + MILESTONES 更新 + 文档同步

## 并行策略

- S1 和 S2 可并行（后端两个独立写域：S1 写 vr_paths/config/intraday_sentiment/test_s092，S2 写 bomb_alert/scheduled_tasks/workflow/premarket_selection/config/新测试）
- S3 依赖 S1（stage 枚举）+ S2（final_candidates 透传）
- S4 依赖 S3（组件迁出）
- S5 依赖 S3（战法战绩从 Workflow.tsx 迁出）

建议执行顺序：S1+S2 并行 → S3 → S4+S5 并行 → S6。

## 串行纪律与边界

- 本 spec 不改数据层（快照/票根/影子收益/daily-review/流转原子性——全部复用不动）
- 本 spec 不新建通知模块（复用 NotificationService + config.feishu_webhook_url）
- 本 spec 不新建规则引擎（复用 bomb_alert 体系扩展 C7-C9）
- AI 盘后总结只落 stub（generate_daily_summary + daily_ai_summary task type + 存储位），S094 完整实现
- 北向规则已删（2024-08-19 停更，无真实数据源）
- feishu_notifier.py 标 deprecated 不删（无调用方，不再被新代码引用）
