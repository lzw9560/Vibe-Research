# S092 实施计划（plan）

> 配套 `spec.md`。流程门 medium：develop 直提；勤 commit、最小功能提交；
> 验收＝离线全测 + tsc/vitest + dev server 冒烟（三 Tab 切换 + dateTriplet + 任务卡片 + 时区修正）。
> 依赖现状：S048 快照机制已合并、S087 6-tab 已实现（被本 spec 替代）、S090 PremarketSelectionSection 已接入。
> UI 原型：`ui-prototype.html` + `design-notes.md`（designer 产出，实现时参照）。

## 阶段划分（按依赖排序）

### S1 · 后端 dateTriplet 端点（地基，无前端依赖）
- `backend/vr_paths.py` 新增 `resolve_date_triplet(date?) -> dict`：
  - 用 `datetime.now(BEIJING_TZ)` 算当前北京时刻（不用 `date.today()`）
  - F 推进逻辑：17:15 后 F=今日交易日，17:15 前 F=上一交易日
  - 复盘独立推进：15:00 后 `review_advanced=true`，review=T；15:00 前 review=F
  - stage 枚举：`pre_market`(00:00-09:29) / `intraday`(09:30-14:59) / `post_transition`(15:00-17:15) / `post_market`(17:15-24:00) / `non_trading`(非交易日)
  - 返回 `{F, review, today, forward, stage, is_trading_day, review_advanced, server_now, next_review_advance_at, next_f_advance_at, non_trading}`
  - `next_review_advance_at`/`next_f_advance_at`：下次 15:00/17:15 的 epoch 时间戳（交易日才算，非交易日跳到下一交易日）
  - `forward` = F 的下一交易日（复用 `last_trading_date(F+1日)`，非日历+1）
- `backend/routers/workflow.py` 新增 `GET /api/workflow/date-triplet?date=` 端点
- 测试：`pytest` 覆盖各时段 F/review/today/forward 推算 + 非交易日 + 手动 date 覆盖 + stage 枚举
- **commit 点**：dateTriplet 端点单测绿

### S2 · 后端 scheduled-tasks 扩展 today_status（与 S1 可并行）
- `backend/routers/scheduled_tasks.py`：`GET /api/scheduled-tasks` 响应扩展 `today_status` 字段
- 后端推算逻辑（R18）：
  - 用 `datetime.now(BEIJING_TZ).date()` 算今日北京日期
  - `last_run_at` 是 naive `datetime.now().isoformat()`（假设服务器本地时区=北京，GR5 标注）
  - `today_status`：`done`(last_run_at 日期==今日 且 status==success) / `error`(==今日 且 failed) / `running`(status==running) / `pending`(last_run_at 日期≠今日)
  - 既有 `last_run_at`/`last_run_status` 字段不变（R10）
- 测试：`pytest` 覆盖 today_status 推算（昨天 success→pending、今天 success→done、今天 failed→error、running→running）
- **commit 点**：scheduled-tasks today_status 单测绿

### S3 · 前端 dateTriplet hook + 双定时器（依赖 S1）
- `frontend/src/lib/api/workflow.ts`：新增 dateTriplet fetch 函数
- `frontend/src/lib/query/workflow.ts`：新增 `useDateTriplet(date?)` hook（页面加载拉一次）
- `frontend/src/lib/useMarketClock.ts`：新增双定时器 hook
  - 用 `next_review_advance_at`/`next_f_advance_at` 减 `Date.now()` 算 setTimeout 延时（服务器时间驱动，零本地时区判断）
  - 15:00 定时器：推进复盘数据日到 T（不推进 F）
  - 17:15 定时器：推进 F + 全量刷新三视图
  - `non_trading=true` 时跳过两个定时器
  - 手动选了 date 后定时器不推进（R14）
  - 15:00-17:15 过渡窗：每 60s 轮询 `GET /api/scheduled-tasks`，17:15 后停止
- 测试：vitest 覆盖 hook 加载/定时器延时计算/手动 date 跳过推进
- **commit 点**：前端 dateTriplet + 定时器 hook 测试绿

### S4 · 前端 TaskStatusCard（依赖 S2）
- `frontend/src/lib/query/scheduledTasks.ts`：新增 `useScheduledTasksStatus` hook（过渡窗 60s 轮询）
- `frontend/src/components/workflow/TaskStatusCard.tsx`：新建组件
  - 公共区常驻，显示盘后 cron 任务列表（8 项，15:30-17:15）
  - 每项：任务名 + 计划时间 + today_status(pending灰/done绿/error红/running蓝脉冲) + 预计完成时间
  - 点击展开详情（复用 `GET /api/scheduled-tasks/{id}`）
  - done 项带"载入"按钮（refetch 对应视图）
  - 非盘后时段折叠为摘要条；非交易日显示"非交易日，无采集任务"
  - 参照 `ui-prototype.html` 设计原型
- 测试：vitest 覆盖渲染（8 项任务 + 状态颜色 + 折叠/展开 + 载入按钮）
- **commit 点**：TaskStatusCard 测试绿

### S5 · 前端 Workflow 三 Tab 容器（依赖 S3+S4，核心改造）
- `frontend/src/pages/Workflow.tsx`：重写为三 Tab 容器
  - 顶部公共区：PageHeader + date picker（容器级管控，`?date=` URL query）+ 锚条（显示 F + 时段 + 各视图数据日）+ TaskStatusCard
  - 三 Tab（复盘/当日/前瞻），URL `?view=` 记录当前 Tab
  - 时段自动高亮（R12）：盘前→前瞻、盘中→当日、盘后过渡→复盘、盘后→前瞻
  - 三组件挂载 + 受控 `date` prop 注入：
    - 复盘 Tab → PostMarketReview（date=dateTriplet.review）
    - 当日 Tab → PreMarketBriefing（date=dateTriplet.today）+ WeatherDecisionBar + ShadowComparisonSection + 暴风雨预测 + 盘中盯盘链接卡片
    - 前瞻 Tab → PremarketSelectionSection（date=dateTriplet.forward）
  - 参照 `ui-prototype.html` 设计原型 + `design-notes.md`
- `frontend/src/router.tsx`：`/workflow` 路由 `?view=` + `?date=` 双 query 支持
- 测试：vitest 覆盖三 Tab 切换 + URL query 读写 + 时段高亮 + date prop 注入
- **commit 点**：Workflow 三 Tab 容器测试绿

### S6 · 组件受控 date 改造 + 时区 bug 修复（与 S5 紧密耦合，同阶段或紧随）
- `frontend/src/components/workflow/PremarketSelectionSection.tsx`：
  - L20 `new Date().toISOString().slice(0, 10)` → 从 dateTriplet 取日期（date prop 由 S5 容器传入）
- `frontend/src/pages/workflow/PostMarketReview.tsx`：
  - L44 `new Date().toISOString().slice(0, 10)` → 受控 `date` prop（=dateTriplet.review）
  - 删除内部 date picker（L102-112），日期权威收敛到容器级
  - WeatherDecisionBar 移出至"当日"Tab（L88-95 移除）
  - 过渡窗渐进填充占位（未产出区"待 {cron时间} 产出"）
- `frontend/src/pages/workflow/PreMarketBriefing.tsx`：
  - PremarketSelectionSection 移出至"前瞻"Tab
  - ShadowComparisonSection 留"当日"
  - 改受控 `date` prop（=dateTriplet.today）
- `frontend/src/pages/workflow/IntradayMonitor.tsx`：
  - L93 CalendarFactorHint `new Date().toISOString()` → 从 dateTriplet 取日期
  - 保留独立路由 `/workflow/intraday`，不进三 Tab（GR3）
- `frontend/src/pages/Workflow.test.tsx` 等：既有测试随容器重写更新 mock
- 测试：vitest 覆盖三组件受控 date 渲染 + tsc 绿
- **commit 点**：组件改造 + 时区 bug 修复测试绿

### S7 · 全量回归 + 冒烟
- `pytest -m "not live"` 全量绿
- `vitest run` + `tsc` 全绿
- dev server :8900 冒烟：
  - 三 Tab 切换正常 + URL `?view=`/`?date=` 读写
  - dateTriplet 端点返回正确（各时段 F/review/today/forward）
  - 时区修正后盘前打开前瞻 Tab 日期正确（不再取到昨天 UTC）
  - 任务状态卡片显示 + 过渡窗轮询正常 + today_status 正确（15:00 开局不全绿）
  - 15:00/17:15 定时器推进（手动调时间或等真实收盘）
  - 非交易日打开页面 stage=non_trading
- spec 验收 AC1-AC14 逐项勾选
- 归档

## 并行策略

- S1 和 S2 可并行（后端两个独立端点，无依赖）
- S3 依赖 S1；S4 依赖 S2；S5 依赖 S3+S4
- S6 与 S5 紧密耦合（组件改造 + 容器挂载），同阶段或紧随
- S7 最后

建议执行顺序：S1+S2 并行 → S3+S4 并行 → S5+S6 → S7。

## 串行纪律与边界

- 本 spec 不改数据层（快照/票根/影子收益/daily-review/流转原子性/DiagnosisCard/funnel_cache/SentimentContext/暴风雨预测——全部复用不动）
- 本 spec 不碰 `scheduled_tasks.py` 的 cron 时间表（15:30-17:15 不变，只改前端呈现）
- `last_run_at` 写入时区（naive datetime）不改（GR5 标注，未来云部署另立 spec）
- 全仓其余 8 处 `toISOString().slice(0,10)` 本次范围仅 workflow 域，其余另立
- IntradayMonitor 保留独立路由不进三 Tab（GR3）
- coach/alerts/topology/first-board 保留独立路由不进三 Tab
