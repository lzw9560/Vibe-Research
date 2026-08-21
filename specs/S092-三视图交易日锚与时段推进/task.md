# S092 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。每任务=最小可验证改动；按 stage 分组，stage 末 commit。
> 测试基线：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`（S091 后全绿起点）。
> 前端测试：`cd frontend && npx tsc --noEmit && npx vitest run`
> 纪律：不碰并行会话未提交改动；勤 commit、最小功能提交（wip: 前缀可）。
> UI 原型参照：`specs/S092-三视图交易日锚与时段推进/ui-prototype.html` + `design-notes.md`。

## S1 后端 dateTriplet 端点（与 S2 可并行）

- [ ] T1 `backend/vr_paths.py` 新增 `BEIJING_TZ` 常量 + `resolve_date_triplet(date?)` 函数：
  - 用 `datetime.now(BEIJING_TZ)` 算当前北京时刻（不用 `date.today()`）
  - F 推进逻辑：17:15 后 F=今日交易日，17:15 前 F=上一交易日（复用 `last_trading_date`）
  - `review`：15:00 后=T（`review_advanced=true`），15:00 前=F
  - `today`：盘前/盘中=F+1 实时语义（端点只返日期，实时性由消费方决定）；盘后=F
  - `forward`：F 的下一交易日（复用 `last_trading_date(F+1日)`，非日历+1）
  - `stage` 枚举：`pre_market`(00:00-09:29) / `intraday`(09:30-14:59) / `post_transition`(15:00-17:15) / `post_market`(17:15-24:00) / `non_trading`(非交易日)
  - `server_now`：`datetime.now(BEIJING_TZ).isoformat()`（带 +08:00）
  - `next_review_advance_at`/`next_f_advance_at`：下次 15:00/17:15 的 epoch 时间戳（非交易日跳到下一交易日）
  - `non_trading`：今日非交易日时 true
  - 手动 date 传入时：F=date, review=date, today=date, forward=下一交易日(date)，stage 仍按时段算但 F 不自动推进
  - 验证：新增 `backend/tests/test_s092_date_triplet.py`——各时段 F/review/today/forward 推算 + 非交易日 + 手动 date 覆盖 + stage 枚举 + review_advanced 判定
- [ ] T2 `backend/routers/workflow.py` 新增 `GET /api/workflow/date-triplet` 端点（调 `vr_paths.resolve_date_triplet`，Query date 可选）
  - 验证：端点单测——mock 各时段返回值正确
- [ ] G1 commit 门：dateTriplet 端点 + vr_paths 单测绿（`pytest backend/tests/test_s092_date_triplet.py -m "not live"`）

## S2 后端 scheduled-tasks 扩展 today_status（与 S1 可并行）

- [ ] T3 `backend/routers/scheduled_tasks.py`：`GET /api/scheduled-tasks` 响应每项扩展 `today_status` 字段
  - 后端推算逻辑（R18）：用 `datetime.now(BEIJING_TZ).date()` 算今日北京日期
  - `today_status` 枚举：`done`(last_run_at 日期==今日 且 status==success) / `error`(==今日 且 failed) / `running`(status==running) / `pending`(last_run_at 日期≠今日)
  - `last_run_at` 是 naive `datetime.now().isoformat()`（假设服务器本地时区=北京，GR5 标注）
  - 既有 `last_run_at`/`last_run_status` 字段不变（R10）
  - 验证：新增 `backend/tests/test_s092_today_status.py`——昨天 success→pending、今天 success→done、今天 failed→error、running→running、null→pending
- [ ] G2 commit 门：scheduled-tasks today_status 单测绿（`pytest backend/tests/test_s092_today_status.py -m "not live"`）

## S3 前端 dateTriplet hook + 双定时器（依赖 S1）

- [ ] T4 `frontend/src/lib/api/workflow.ts`：新增 dateTriplet fetch 函数 + TypeScript 类型（DateTripletResponse）
  - 验证：tsc 过
- [ ] T5 `frontend/src/lib/query/workflow.ts`：新增 `useDateTriplet(date?)` hook（useQuery，页面加载拉一次，staleTime Infinity——时段推进由定时器触发 refetch）
  - 验证：vitest 覆盖 hook 加载 + date 参数变化
- [ ] T6 `frontend/src/lib/useMarketClock.ts`：新增双定时器 hook
  - 用 `next_review_advance_at`/`next_f_advance_at` 减 `Date.now()` 算 setTimeout 延时（服务器时间驱动，零本地时区判断）
  - 15:00 定时器（`next_review_advance_at`）：到点若交易日则推进复盘数据日到 T（回调通知消费方）
  - 17:15 定时器（`next_f_advance_at`）：到点若交易日则推进 F + 触发 dateTriplet refetch（回调通知消费方）
  - `non_trading=true` 时跳过两个定时器
  - 手动选了 date 后定时器不推进（R14）
  - 15:00-17:15 过渡窗：每 60s 轮询 scheduled-tasks（由 S4 的 hook 消费），17:15 后停止
  - 验证：vitest 覆盖延时计算 + non_trading 跳过 + 手动 date 跳过 + 过渡窗轮询启停
- [ ] G3 commit 门：前端 dateTriplet + 定时器 hook 测试绿（`vitest run` + `tsc --noEmit`）

## S4 前端 TaskStatusCard（依赖 S2）

- [ ] T7 `frontend/src/lib/query/scheduledTasks.ts`：新增 `useScheduledTasksStatus` hook
  - 调 `GET /api/scheduled-tasks`，过渡窗（15:00-17:15）60s 轮询，其余时段不轮询
  - 返回任务列表含 `today_status` 字段
  - 验证：vitest 覆盖轮询启停（过渡窗内轮询、过渡窗外不轮询）
- [ ] T8 `frontend/src/components/workflow/TaskStatusCard.tsx`：新建组件
  - 公共区常驻，显示盘后 cron 任务列表（8 项，15:30-17:15）：基因得分/STI/前向结算/R1溢价/首板评分/kline日更/derived预采集/漏斗预计算
  - 每项：任务名 + 计划时间 + today_status 颜色（pending灰/done绿/error红/running蓝脉冲）+ 预计完成时间
  - 点击任务项展开详情（复用 `GET /api/scheduled-tasks/{id}`）
  - done 项带"载入"按钮（回调 refetch 对应视图）
  - 非盘后时段折叠为摘要条（"盘后采集 15:30 开始"）
  - 非交易日显示"非交易日，无采集任务"
  - 参照 `ui-prototype.html` 设计原型
  - 验证：vitest 覆盖渲染（8 项任务 + 状态颜色 + 折叠/展开 + 载入按钮 + 非交易日态）
- [ ] G4 commit 门：TaskStatusCard 测试绿（`vitest run`）

## S5 前端 Workflow 三 Tab 容器（依赖 S3+S4，核心改造）

- [ ] T9 `frontend/src/pages/Workflow.tsx`：重写为三 Tab 容器
  - 顶部公共区：PageHeader + date picker（容器级管控，`?date=` URL query）+ 锚条（显示 F + 时段 + 各视图数据日）+ TaskStatusCard
  - 锚条文案示例："锚定交易日：F=2026-08-21 | 时段：盘后过渡 | 复盘=T(08-21) | 当日=T-1(08-20) | 前瞻=T+1(08-22)待产出"
  - 锚条过渡窗用琥珀色"数据采集中"，盘后(17:15后)用绿色"数据就绪"
  - 三 Tab（复盘/当日/前瞻），URL `?view=` 记录当前 Tab
  - 时段自动高亮（R12）：盘前→前瞻、盘中→当日、盘后过渡→复盘、盘后→前瞻
  - 三组件挂载 + 受控 `date` prop 注入：复盘→PostMarketReview(date=review)、当日→PreMarketBriefing(date=today)、前瞻→PremarketSelectionSection(date=forward)
  - `?view=` 和 `?date=` 双 query 共存（如 `?view=today&date=2026-08-20`）
  - 参照 `ui-prototype.html` 设计原型 + `design-notes.md`
  - 验证：vitest 覆盖三 Tab 切换 + URL query 读写 + 时段高亮 + date prop 注入
- [ ] T10 `frontend/src/router.tsx`：`/workflow` 路由 `?view=` + `?date=` 双 query 支持
  - 验证：tsc 过
- [ ] G5 commit 门：Workflow 三 Tab 容器测试绿（`vitest run` + `tsc --noEmit`）

## S6 组件受控 date 改造 + 时区 bug 修复（与 S5 紧密耦合）

- [ ] T11 `frontend/src/components/workflow/PremarketSelectionSection.tsx`：L20 `new Date().toISOString().slice(0, 10)` → 删除 fallback，`date` prop 由 S5 容器传入（dateTriplet.forward）
  - 验证：vitest 覆盖受控 date 渲染
- [ ] T12 `frontend/src/pages/workflow/PostMarketReview.tsx`：
  - L44 `new Date().toISOString().slice(0, 10)` → 受控 `date` prop（=dateTriplet.review）
  - 删除内部 date picker（L102-112），日期权威收敛到容器级
  - WeatherDecisionBar 移出至"当日"Tab（L88-95 删除 import + JSX）
  - 过渡窗渐进填充占位：未产出区域显示"待 {cron时间} 产出"（接收 `review_advanced` + `stage` prop 判断是否过渡窗）
  - 验证：vitest 覆盖受控 date 渲染 + 过渡窗占位 + WeatherDecisionBar 已移出
- [ ] T13 `frontend/src/pages/workflow/PreMarketBriefing.tsx`：
  - `PremarketSelectionSection` 移出至"前瞻"Tab（删除内嵌 JSX）
  - `ShadowComparisonSection` 留"当日"
  - 改受控 `date` prop（=dateTriplet.today）
  - 盘后时段标注"数据为今早盘前采集口径，17:15 后可刷新"
  - 盘中时段显示盯盘链接卡片（跳转 `/workflow/intraday`）
  - 验证：vitest 覆盖 PremarketSelectionSection 已移出 + 受控 date + 盯盘链接卡片
- [ ] T14 `frontend/src/pages/workflow/IntradayMonitor.tsx`：L93 CalendarFactorHint `new Date().toISOString()` → 从 dateTriplet 取日期（保留独立路由，不进三 Tab，GR3）
  - 验证：tsc 过
- [ ] T15 `frontend/src/pages/Workflow.test.tsx` 等：既有测试随容器重写更新 mock（适配三 Tab + dateTriplet + TaskStatusCard）
  - 验证：`vitest run` 全绿
- [ ] G6 commit 门：组件改造 + 时区 bug 修复测试绿（`vitest run` + `tsc --noEmit`）

## S7 全量回归 + 冒烟验收

- [x] T16 `pytest -m "not live"` 全量绿（对比 S091 基线无回归）
  - 后端 2140 passed / 12 failed（既有问题：routers.candidates circular import，S092 前已存在，非本 spec 引入）
- [x] T17 `cd frontend && npx tsc --noEmit && npx vitest run` 全绿
  - tsc exit 0；vitest 53 文件 404 passed（含 S092 新增 24+10+7=41 测试）
- [ ] T18 dev server :8900 冒烟（逐项验证 AC1-AC14）：
  - AC1 三 Tab 切换 + URL `?view=` 读写
  - AC2 dateTriplet 端点返回正确（各时段 F/review/today/forward/server_now/next_*_at）
  - AC3 盘前 F=T-1（复盘昨日、前瞻昨晚选股池、当日今早简报生成中）
  - AC4 盘后过渡窗（15:00-17:15）：复盘=T 实时+占位、当日=T-1 快照、前瞻="待产出"、任务卡片可见进度
  - AC5 17:15 F 推进（三视图全量刷新）
  - AC6 15:00 复盘独立推进
  - AC7 过渡窗轮询 + today_status 正确（15:00 开局不全绿）
  - AC8 时区 bug 修复（PremarketSelectionSection/PostMarketReview/IntradayMonitor 不再用 toISOString，定时器用 epoch 算延时）
  - AC9 date picker 手动回看（三视图统一以 F' 推算）
  - AC10 时段自动高亮
  - AC11 任务状态卡片（公共区常驻 + 点击展开 + 载入按钮）
  - AC12 离线全测绿
  - AC13 dev server 冒烟（三 Tab + dateTriplet + 时区修正 + 任务卡片 + 过渡窗轮询）
  - AC14 非交易日边界（stage=non_trading + 定时器不推进 + 任务卡片"非交易日"）
  - 注：离线全测绿（AC12 ✓）；dev server 冒烟待用户本地走查
- [x] T19 spec.md/task.md 勾选验收状态 + 收尾 commit（docs(S092): 验收）
- [~] G7 验收门：AC12 离线全测绿 ✓；AC1-AC11/AC13-AC14 待 dev server 冒烟走查

## 依赖图

```
S1(T1→T2) ──┐
            ├──→ S3(T4→T5→T6) ──┐
S2(T3) ─────┘                   ├──→ S5(T9→T10) ──→ S6(T11→T12→T13→T14→T15) ──→ S7(T16→T17→T18→T19)
                          S4(T7→T8) ──┘
```

并行策略：S1+S2 并行 → S3+S4 并行 → S5 → S6 → S7。

## 串行纪律与边界

- 本 spec 不改数据层（快照/票根/影子收益/daily-review/流转原子性/DiagnosisCard/funnel_cache/SentimentContext/暴风雨预测——全部复用不动）
- 本 spec 不碰 `scheduled_tasks.py` 的 cron 时间表（15:30-17:15 不变，只改前端呈现）
- `last_run_at` 写入时区（naive datetime）不改（GR5 标注，未来云部署另立 spec）
- 全仓其余 8 处 `toISOString().slice(0,10)` 本次范围仅 workflow 域，其余另立
- IntradayMonitor 保留独立路由不进三 Tab（GR3）
- coach/alerts/topology/first-board 保留独立路由不进三 Tab
