# Spec: S092 — 三视图交易日锚与时段推进

> 状态：设计已闭合（grill-me 15 轮 Q&A + spec grill 6 轮 G1-G6 全部锁定），待实现
> 作者：Codex 会话  日期：2026-08-21
> 级别：**medium**（跨前后端 >50 行；无新外部数据源、无新 AI 工具、无新财务公式——数据层零返工，仅前端容器重组 + 后端新增轻量端点 + 时区 bug 修复）
> 流程门：develop 直提 + 勤 commit；验收＝离线全测 + tsc/vitest + dev server 冒烟（三 Tab 切换 + dateTriplet 端点 + 时区修正 + 任务状态卡片）
> 关联：S048（日期选择器 + 快照）、S087（6-tab pipeline，被替代）、S084（两级 Tab，被替代）、S074（market_phase，被替代）、S090（PremarketSelectionSection 接入，时区 bug 修复）、S063（情绪管线，呈现位置重分配）、S088（暴风雨预测，呈现位置重分配）

## 0. 起因

用户报告"今日选股工作流没数据"。根因二：
1. **时区 bug**：`PremarketSelectionSection.tsx:20` 用 `new Date().toISOString()`（UTC）取今日，北京时间盘前（UTC 前一日 16:00+）取到昨天日期 → 后端拿到错误 date
2. **视角错位**：系统只有"单日视角"，盘前时段想看 T 日复盘时系统认为"当日还没数据"；盘前/盘后/隔夜窗口的数据日关系未建模

用户在 grill-me 访谈中提出三视图需求："每日应该提供 3 个维度视图，t t-1 t+1"，经 15 轮 Q&A 闭合为"单一交易日锚 F + 时段推断三视图"模型。spec 落盘后经 6 轮 grill（G1-G6）修正了 F 推进时机（15:00→17:15）、盘后默认高亮（复盘→前瞻）、盘后过渡窗轮询机制、任务状态卡片等关键设计。

## 1. 问题 / 目标

1. **三视图解耦**：复盘 / 当日 / 前瞻三个独立视图，各自装独立逻辑，不堆叠在同一页
2. **交易日锚 F**：F = 最近已收盘且盘后数据全产出交易日，17:15 推进，消除盘前"没数据"的视角错位
3. **时区 bug 修复**：前端日期计算统一走后端源，不再用 `new Date().toISOString()`
4. **路由收敛**：单一 `/workflow` + 三 Tab，`?view=review|today|forward`
5. **盘后过渡窗**：15:00-17:15 数据渐进产出期间，任务状态卡片让用户可见采集进度

## 2. 背景（现状挂载点）

- 前端路由：`Workflow.tsx`（S087 6-tab / S084 两级 Tab，被本 spec 替代）
- 盘前简报：`PreMarketBriefing.tsx`（主体 = "当日"视图盘前/盘后段；内嵌 `PremarketSelectionSection` = "前瞻"组件，需拆出）
- 盘后复盘：`PostMarketReview.tsx`（= "复盘"视图；内部自管 date + 同款 toISOString bug + 嵌 WeatherDecisionBar，需改受控 date + 移出 WeatherDecisionBar）
- 盘中盯盘：`IntradayMonitor.tsx`（= "当日"视图盘中段，现有独立路由 `/workflow/intraday`；CalendarFactorHint 同款 toISOString bug）
- 盘前选股：`PremarketSelectionSection.tsx` + `usePremarketSelection` hook（= "前瞻"视图，时区 bug 所在）
- 现有其他工作流页面：`coach/alerts/topology/first-board`（保留独立路由，不进三 Tab）
- 后端日期工具：`vr_paths.py`（`last_trading_date` / `is_trading_day` / `prev_trading_date`，A 股节假日表）
- 后端快照：`routers/workflow.py::_save_snapshot` / `_load_snapshot`（S048 机制，复用不改）
- 后端时段判定：`trading_workflow.get_current_stage()`（S074，前端不再依赖，后端调度器保留）
- 后端任务调度：`scheduled_tasks.py` + `routers/scheduled_tasks.py`（`GET /api/scheduled-tasks` 已有 `last_run_at` / `last_run_status`，任务状态卡片复用——但需前端从 `last_run_at`+`cron_expr`+`server_now` 推算"今日完成"状态，见 R18）
- 后端时区：`scheduled_tasks.py` 已用 `BEIJING_TZ`、`trading_workflow.py:25` 有"阶段判定须用北京时区"踩坑记录——dateTriplet 端点沿用
- 盘后 cron 时间表：15:30 基因得分 → 15:35 STI → 15:45 前向结算 → 16:15 首板评分 → 16:30 kline 日更+复盘报告 → 17:00 derived 预采集 → 17:15 漏斗预计算

## 3. 需求清单

### 3.1 核心模型（grill Q1-Q15 + G1-G6 闭合决策）

- [ ] R1 **交易日锚 F**：F = 最近已收盘且盘后数据全产出的交易日。交易日 17:15 后 F = 当天；17:15 前（含盘前/盘中/15:00-17:15 过渡窗）F = 上一交易日。非交易日 F 不变。**注：F 推进纯时间驱动（17:15 定时器），即使某 cron 失败 F 照常推进（失败任务卡片标 error + 手动重跑）——"时间驱动 + 失败可见"，不因数据缺失阻塞推进**（M4 闭合）。
- [ ] R2 **F 推进点 = 17:15**：每个交易日 17:15（漏斗预计算跑完），F 推进（T-1→T）。当日/前瞻视图数据日跟随 F。
- [ ] R2a **复盘视图独立推进点 = 15:00**：复盘视图数据日有自己的滚动规则——15:00 收盘后立即推进到 T（已有实时数据：涨停池/情绪/梯队先看），不跟 F（17:15）走。复盘是"已发生的事"，15:00 后部分数据已有，先看无风险。
- [ ] R3 **三视图数据日**（交易日 T，按时段）：

  | 时段 | F | 复盘数据日 | 当日数据日 | 前瞻数据日 | 说明 |
  |---|---|---|---|---|---|
  | 盘前(00:00-09:29) | T-1 | T-1 | T（今早简报，生成中） | T（昨晚选的今日标的池） | 隔夜窗口延续 |
  | 盘中(09:30-14:59) | T-1 | T-1 | T（实时盯盘） | T（标的池观察中） | 盯昨日选的标的今日表现 |
  | 盘后过渡(15:00-17:15) | T-1（不变） | **T**（推进，实时数据先看，cron 产出后补全） | T-1（今早简报快照，不切换） | "待 17:15 产出" | 过渡窗：复盘看 T 日实时，当日/前瞻等 F 推进 |
  | 盘后(17:15-24:00) | T（推进） | T（完整） | T（今早简报快照 + 标注"17:15 后可刷新"） | T+1（今晚选股池，完整） | 正式复盘 T + 选 T+1 |
  | 隔夜(T+1日 00:00-09:29) | T（不变） | T（完整） | T+1（明早简报，生成中） | T+1（完整） | 隔夜窗口延续 |
  | T+1日盘中(09:30-14:59) | T（不变，T+1未收盘） | T（完整） | T+1（实时盯盘） | T+1（完整） | 盯昨晚选的标的今日表现 |
  | T+1日盘后过渡(15:00-17:15) | T（不变） | **T+1**（推进，实时数据先看） | T（今早简报快照，不切换） | "待 17:15 产出" | 循环重来 |

- [ ] R3a **复盘过渡窗（15:00-17:15）渐进填充**：15:00 后复盘视图立即显示 T 日实时可得部分（涨停池/情绪/梯队），未产出区域（基因得分/STI/漏斗等）显示"待 {cron 时间} 产出"占位 + 任务状态卡片标红对应任务。不渐进轮询刷新——用户看到任务卡片变绿后手动刷新，或 17:15 F 推进时自动全量刷新一次。
- [ ] R3b **前瞻过渡窗（15:00-17:15）**：前瞻视图显示"盘后选股采集中（kline 日更 16:30 完成后产出）"+ 任务状态卡片标红 kline 任务待跑。**前瞻实际就绪时机 = 16:30 kline_refresh 任务 success**（breakout 选股只读 `baostock_kline_cache`，不依赖漏斗/derived/STI），但为模型简洁统一在 17:15 F 推进时刷新——17:15 是简化选择而非数据依赖，前瞻 16:30 后可手动"载入"。任务卡片 kline 项变绿后"载入"按钮可触发前瞻视图 refetch。
- [ ] R4 **盘后"当日"降级**：盘后时段"当日"显示 F（=T）今日简报快照（今早盘前采集那份）+ 标注"数据为今早盘前采集口径，盘后最终收盘数据 17:15 后可刷新"。不预生成 F+1 简报（简报依赖实时竞价/分时，盘后无源，不臆造）。17:15 后用户可手动触发 `POST /api/workflow/pre-market/refresh` 更新快照为最终收盘口径。
- [ ] R5 **当日与前瞻数据日同为 F+1 但不耦合**：当日 = PreMarketBriefing 管线（情绪天气→漏斗→候选池），前瞻 = breakout 弱信号选股 + 风控价。两条独立管线、不同产出。
- [ ] R6 **语义标签**：三视图用语义角色标签（复盘/当日/前瞻），不用相对偏移（T-1/T/T+1）。

### 3.2 date picker 语义（M2 补全契约）

- [ ] R7 **date picker 选复盘日 F**：用户手动选日期 → 覆盖锚 F，三视图统一以该 F 推算（复盘=F、当日=F 简报快照、前瞻=F 的下一交易日）。不选时按时段自动算 F。
- [ ] R8 **date picker 不选时**：系统按时段自动算 F（17:15 后 F=今日交易日，17:15 前 F=上一交易日）。
- [ ] R8a **手动模式契约补全**（M2）：
  - **前瞻=F 的下一交易日**（非日历 +1）：周五→周一、节前→节后，复用 `vr_paths.last_trading_date(F+1日)` 逻辑。
  - **过渡窗内手动选"今天"**：复用自动时段语义（当日=T-1 简报快照、前瞻="待产出"），不按 R7 字面给前瞻传 T+1（16:30 前后端会用陈旧 kline 静默算错）。
  - **定时器与手动日期交互**：用户选了 date 后定时器不推进（R14 已述）；清除 date 后恢复自动态，定时器重新激活。
  - **URL 契约**：`?view=` 和 `?date=` 共存（如 `?view=today&date=2026-08-20`），读写在 Workflow 容器统一管理。

### 3.3 后端端点

- [ ] R9 **新增 `GET /api/workflow/date-triplet?date=`**：返回 `{F, review, today, forward, stage, is_trading_day, review_advanced, server_now, next_review_advance_at, next_f_advance_at, non_trading}`。
  - `date` 可选（用户手动选的复盘日）；不传则按时段自动算 F。
  - `stage`：`pre_market` | `intraday` | `post_transition`（15:00-17:15）| `post_market`（17:15 后）| `non_trading`（非交易日）。
  - `is_trading_day`：今日是否 A 股交易日（供前端定时器判断是否推进）。
  - `review_advanced`：复盘是否已独立推进到 T（15:00 后 true，17:15 前供前端区分复盘数据日与 F）。
  - `server_now`：服务器北京时间 ISO（带 +08:00），供前端定时器算 setTimeout 延时（消除时区依赖）。
  - `next_review_advance_at` / `next_f_advance_at`：下次复盘推进 / F 推进的 epoch 时间戳（前端用 `next_*_at - 本地 now` 算延时，不依赖本地时区判断）。
  - `non_trading`：今日非交易日时 true（前端定时器跳过推进）。
  - **时区锚定**：所有时刻判定（stage 推算、is_trading_day）后端用 `datetime.now(BEIJING_TZ)`，不用 `date.today()`（后者依赖服务器本地时区，Docker/云非北京时区会错——`trading_workflow.py:25` 已有踩坑记录）。前端定时器用 `next_*_at - Date.now()` 算 setTimeout 延时，零本地时区判断。
  - 复用 `vr_paths.last_trading_date` / `is_trading_day`，零外部请求。
- [ ] R10 **既有端点不动（GR4 修正）**：`GET /api/workflow/pre-market`、`GET /api/workflow/status`、`GET /api/workflow/pre-market/dates` 保留行为不变。`GET /api/scheduled-tasks` **扩展新增 `today_status` 字段**（既有 `last_run_at`/`last_run_status` 等字段不变），由后端用 `datetime.now(BEIJING_TZ)` 推算"今日完成"状态（R18），语义内聚于任务端点。dateTriplet 端点保持纯日期计算职责，不混入任务状态。

### 3.4 前端改造

- [ ] R11 **新建 Workflow 三 Tab 容器**：单一 `/workflow` 路由，三 Tab（复盘/当日/前瞻），URL query `?view=review|today|forward` 记录当前 Tab + `?date=` 记录手动选的复盘日（两者共存：`?view=today&date=2026-08-20`）。
  - **不大改组件内部数据获取与渲染逻辑**，但三个视图组件统一改为受控 `date` prop（来自 dateTriplet 对应字段），消除组件内部 `new Date().toISOString()` 自管日期：
    - `PostMarketReview`：接受 `date` prop（=dateTriplet.review），**删除内部 date picker（L102-112）+ 同款 toISOString bug（L44）**（H4 修正）。WeatherDecisionBar 当前嵌于此组件（L88-95），按 R21 移出至"当日"Tab——移动属内容重分配，不算"大改数据逻辑"。
    - `PreMarketBriefing`：接受 `date` prop（=dateTriplet.today）。
    - `PremarketSelectionSection`：`date` prop 接口不变，调用方传 dateTriplet.forward。
  - **盘中盯盘入口**（GR3 修正）：`IntradayMonitor.tsx` **保留独立路由 `/workflow/intraday`，不进三 Tab 容器**。"当日"Tab 统一显示 PreMarketBriefing（盘前简报管线），盘中时段在"当日"Tab 内显示盯盘链接卡片（链接到 `/workflow/intraday`），用户点击跳转独立页面盯盘。理由：IntradayMonitor（盯盘）和 PreMarketBriefing（简报）是两种不同逻辑，按时段切换会让"当日"Tab 在盘中/盘后呈现完全不同的界面，违背 Q5 解耦原则；保留独立路由让两个逻辑各管各的，"当日"Tab 内容连贯。IntradayMonitor 的同款 toISOString bug（L93）仍顺手修（R15），但修的是 bug 不是挂载关系。
- [ ] R12 **时段自动高亮当前角色 Tab**：盘前默认高亮"前瞻"、盘中"当日"、盘后（17:15 后）"前瞻"（核心动作=选 T+1）、盘后过渡（15:00-17:15）"复盘"（盯今日采集进度）。但不强制锁定，用户可切看其他视图。
- [ ] R13 **dateTriplet hook**：新增 `useDateTriplet(date?)`，调 `GET /api/workflow/date-triplet`，返回三元组。页面加载时拉一次。
- [ ] R14 **双定时器（服务器时间驱动）+ 过渡窗轮询**：
  - **定时器机制**：前端用 dateTriplet 返回的 `next_review_advance_at` / `next_f_advance_at`（epoch）减去 `Date.now()` 算 setTimeout 延时，到点触发推进。**不依赖本地时钟判断北京时间**（消除 H1 时区 bug——非北京时区用户本地 15:00 ≠ 北京 15:00）。`non_trading=true` 时跳过两个定时器。
  - **15:00 定时器**（`next_review_advance_at`）：到点若交易日则本地推进复盘视图数据日到 T（R2a），不推进 F。
  - **17:15 定时器**（`next_f_advance_at`）：到点若交易日则本地推进 F + 全量刷新三视图（R2）。**F 推进纯时间驱动**：即使某 cron 任务失败 F 照常推进，失败任务在卡片标 error + 支持手动重跑（`POST /api/scheduled-tasks/{id}/run`）——"时间驱动 + 失败可见"而非"数据驱动推进"。
  - **15:00-17:15 过渡窗轮询**：每 60s 轮询 `GET /api/scheduled-tasks` 检测任务今日完成状态变化（R16 定义），任务状态卡片更新。17:15 后停止轮询。
  - **与手动日期的交互**：用户手动选了 date（覆盖 F）后，定时器不推进（避免覆盖手动选择）；用户清除 date（URL 无 `?date=`）后恢复自动态，定时器重新激活。
- [ ] R15 **时区 bug 修复**：`PremarketSelectionSection.tsx:20` 的 `new Date().toISOString().slice(0, 10)` 替换为从 `dateTriplet` 获取的日期。组件接口（`date` prop）不变，调用方（三 Tab 容器）负责计算传入。**同款 bug 顺手修**：`PostMarketReview.tsx:44`、`IntradayMonitor.tsx:93`（CalendarFactorHint 的 `new Date().toISOString()`）一并改为从 dateTriplet 取日期。全仓其余 8 处 `toISOString().slice(0,10)` 本次范围仅 workflow 域，其余另立。

### 3.5 任务状态卡片（G1-G2 闭合）

- [ ] R16 **任务状态卡片**：三视图之外的公共区（顶部常驻，与 date picker 同行），复用 `GET /api/scheduled-tasks` 端点。显示盘后 cron 任务列表（15:30 基因得分 → 17:15 漏斗预计算），每项含任务名 + 计划时间 + `last_run_at` + 今日完成状态 + 预计完成时间。
- [ ] R17 **任务详情**：点击任务项展开详情（复用 `GET /api/scheduled-tasks/{id}`），显示任务上次执行日志/错误信息。
- [ ] R18 **"今日完成"状态后端推算（GR1 修正）**：后端 `last_run_status` 实际只有 `success`/`failed`/`running`/`null` 四种，且 `last_run_at` 存的是 `datetime.now().isoformat()`——**naive datetime 无时区**（scheduled_tasks.py:51/287）。前端拿 naive `last_run_at` 跟 `server_now`（北京 +08:00）比日期会因时区/格式不一致出错。
  - **后端推算**：`GET /api/scheduled-tasks` 端点扩展返回 `today_status` 字段（R10），后端用 `datetime.now(BEIJING_TZ)` 算"今日北京日期"，与 `last_run_at`（naive，假设服务器本地时区=北京）比日期：
    - `done` ≡ `last_run_at` 日期 == 今日北京日期 且 `last_run_status == success`
    - `error` ≡ `last_run_at` 日期 == 今日北京日期 且 `last_run_status == failed`
    - `running` ≡ `last_run_status == running`
    - `pending` ≡ `last_run_at` 日期 ≠ 今日北京日期（今天任务还没跑，不管昨天的 `last_run_status` 是什么）——**GR2 闭合：H2"全绿误判"在此自然消解——15:00-15:30 今天任务没跑时 `last_run_at` 日期=昨天 → 正确标 pending，15:30 后第一个任务跑完 `last_run_at` 日期=今天 → 正确标 done。**
  - **前端只渲染** `today_status` 枚举，不解析 `last_run_at` naive 字符串、不做时区推算——时区问题在服务端解决（服务端知道自己跑在哪个时区），前端零时区假设。
  - 过渡窗轮询检测 `last_run_at` 变化（新执行记录出现）时更新对应项状态。任务变 `done` 时卡片标绿 + 任务项带"载入"按钮（refetch 对应视图，避免半成品闪烁但降低用户找刷新入口成本）。
  - **非交易日**：所有盘后 cron 任务不跑，卡片显示"非交易日，无采集任务"。

### 3.6 历史组件呈现位置重分配

- [ ] R19 **S050 行为对照卡**（ShadowComparisonSection）：移入"当日"Tab（盘前决策语境）。
- [ ] R20 **S054 盘后三问页**（PostMarketReview 三问）：归入"复盘"Tab。
- [ ] R21 **S063 WeatherDecisionBar**：归入"当日"Tab 顶部。
- [ ] R22 **S088 暴风雨预测**：归入"当日"Tab 决策语境区块。
- [ ] R23 **S084 选股池/战法两级 Tab**：被三视图 Tab 取代。选股池内容移入"当日"Tab 子区域，战法内容分散到"当日"（盘前战法匹配）和"复盘"（战法胜率统计）。`SelectionPipeline` / `FunnelLayers` 等组件复用。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/vr_paths.py` | 新增：`resolve_date_triplet(date?) -> dict`（复用 `last_trading_date` / `is_trading_day`，含 `review_advanced` 判定 15:00 分割 + `server_now` 北京时间 + `next_*_at` epoch + `non_trading`） |
| `backend/routers/workflow.py` | 新增：`GET /api/workflow/date-triplet` 端点（调 `vr_paths.resolve_date_triplet`） |
| `frontend/src/lib/query/workflow.ts` | 新增：`useDateTriplet(date?)` hook |
| `frontend/src/lib/api/workflow.ts` | 新增：dateTriplet fetch 函数（hook 之下的请求层） |
| `frontend/src/lib/useMarketClock.ts` | 新增：双定时器 hook（用 `next_review_advance_at`/`next_f_advance_at` 算 setTimeout 延时 + 15:00-17:15 过渡窗 60s 轮询 + `non_trading` 跳过） |
| `frontend/src/lib/query/scheduledTasks.ts` | 新增/复用：`useScheduledTasksStatus` hook（调 `GET /api/scheduled-tasks`，过渡窗 60s 轮询 + 前端从 `last_run_at`+`cron_expr`+`server_now` 推算"今日完成"状态） |
| `frontend/src/components/workflow/TaskStatusCard.tsx` | 新增：任务状态卡片组件（公共区常驻，点击展开详情，任务项带"载入"按钮） |
| `frontend/src/pages/Workflow.tsx` | 重写：三 Tab 容器 + 任务状态卡片公共区 + date picker 容器级管控 + `?view=`/`?date=` URL 双 query 管理，替代 S087 6-tab / S084 两级 Tab |
| `frontend/src/components/workflow/PremarketSelectionSection.tsx` | 修复：`new Date().toISOString()` → 从 dateTriplet 取日期（L20） |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | 拆分：`PremarketSelectionSection` 移出至"前瞻"Tab；`ShadowComparisonSection` 留"当日"；改受控 `date` prop |
| `frontend/src/pages/workflow/PostMarketReview.tsx` | 改受控 `date` prop（=dateTriplet.review）+ **删除内部 date picker（L102-112）+ 修 toISOString bug（L44）**；WeatherDecisionBar 移出至"当日"Tab（L88-95）；过渡窗渐进填充占位 |
| `frontend/src/pages/workflow/IntradayMonitor.tsx` | 修 CalendarFactorHint toISOString bug（L93）→ 从 dateTriplet 取日期；**保留独立路由，不进三 Tab**（GR3），"当日"Tab 内加链接卡片跳转 |
| `frontend/src/router.tsx` | `/workflow` 路由 query `?view=` + `?date=` 双参数支持；`/workflow/intraday` 路由保留（兼容深链） |
| `frontend/src/pages/Workflow.test.tsx` 等 | **既有测试随容器重写必破**：更新 mock 适配三 Tab + dateTriplet + 任务状态卡片 |

**去留未提组件**：`PipelineProgressBar`（S087 六阶段产物）内嵌于三个视图组件，S087 被替代后若无人引用则随 Workflow 重写自然移除，不单独列出。

## 5. 设计方案（关键取舍）

1. **单一交易日锚 F + 时段推断，而非三个独立日期锚**：三视图的语义关系随时段自然流转，用单一锚 + 时段让系统自动推断三个角色，避免用户手动维护三个漂移的日期。——grill Q1 闭合。

2. **F 推进点 = 17:15（盘后数据全产出后），而非 15:00**：盘后 cron 数据 15:30-17:15 渐进产出，15:00 推进会导致当日/前瞻视图显示半成品。17:15 推进确保 F 推进时数据完整。但复盘视图独立推进——15:00 即推进到 T（已有实时涨停池/情绪数据先看，未产出部分占位），因复盘是"已发生的事"先看无风险。——grill G1/G3/G4 闭合，修正原 Q2/Q4 的 15:00 推进。

3. **语义角色标签（复盘/当日/前瞻），而非相对偏移（T-1/T/T+1）**：语义角色固定，底层数据日随 F 滚动，标签不漂移。——grill Q3 闭合。

4. **3 视图而非 2 视图**：用户明确要求"逻辑解耦，不耦合，更清晰"。——grill Q5/Q6 闭合。

5. **连续周期 + 双推进点（15:00 复盘 + 17:15 F），而非多段时段切分**：盘后(T)就是盘前(T+1)，是同一段隔夜窗口从相邻两天视角看。15:00 复盘推进让用户收盘后立即看 T 日实时数据，17:15 F 推进让当日/前瞻拿到完整数据后切换。——grill Q8 + G1 闭合。

6. **盘后默认高亮"前瞻"Tab（核心动作=选 T+1），而非"复盘"**：盘后用户核心动作是选 T+1 标的，复盘是辅助验证。默认高亮指向核心动作。——grill G5 闭合，修正原 Q12。

7. **dateTriplet 计算放后端**：F 的计算依赖 A 股交易日历，后端已有全套基础设施。——grill Q12 闭合。

8. **新建 Workflow 三 Tab 容器挂载现有组件，不重写组件数据获取与渲染逻辑**：三个组件（PostMarketReview / PreMarketBriefing / PremarketSelectionSection）内部数据获取与渲染逻辑各自成熟，重写风险高收益低。但组件的**日期权威需统一收敛**——三个组件原有 `new Date().toISOString()` 自管日期（同款时区 bug），统一改为接受 dateTriplet 对应字段的受控 `date` prop，PostMarketReview 额外删除内部 date picker（H4）。这属"改 date prop 注入方式"，不属"重写数据逻辑"。IntradayMonitor **保留独立路由不进三 Tab**（GR3 推翻 Oracle H3 的挂载建议——两个不同逻辑按时段切换会让"当日"Tab 内容跳变，违背 Q5 解耦原则）。——grill Q14 闭合 + Oracle H4 修正 + GR3 修正。

9. **任务状态卡片公共区常驻，复用 `GET /api/scheduled-tasks` 端点**：盘后数据采集任务横跨复盘/前瞻两个视图，任务状态不是某个视图私有信息，放公共区让用户在任何 Tab 都能看到"数据正在成型"。复用已有 `GET /api/scheduled-tasks` 端点（零新端点），但"今日完成"状态需前端从 `last_run_at`+`cron_expr`+`server_now` 推算（R18）——后端 `last_run_status` 无每日重置语义，直接用会过渡窗开局全绿误判（Oracle H2）。——grill G2 闭合。

10. **过渡窗（15:00-17:15）60s 轮询任务状态，其余时段零轮询**：只在"数据正在成型"的 2 小时窗口轮询任务状态（同一份数据顺便驱动视图刷新），其余时段零轮询。轮询成本：`GET /api/scheduled-tasks` 是 SQLite 本地读，60s × 2h = 120 次请求，负载可忽略。双定时器（15:00 复盘 + 17:15 F）用 `next_*_at - Date.now()` 算 setTimeout 延时，服务器时间驱动，不依赖本地时区判断北京时间（Oracle H1）。——grill G6 闭合 + Oracle H1 修正。

## 6. 验收标准

- [ ] AC1 **三 Tab 切换**：`/workflow` 页面三个 Tab（复盘/当日/前瞻），URL `?view=` 记录当前 Tab，刷新不丢 Tab 状态。
- [ ] AC2 **dateTriplet 端点**：`GET /api/workflow/date-triplet` 返回 `{F, review, today, forward, stage, is_trading_day, review_advanced, server_now, next_review_advance_at, next_f_advance_at, non_trading}`，零外部请求（纯 `vr_paths` 计算 + `datetime.now(BEIJING_TZ)`）。
- [ ] AC3 **盘前 F=T-1**：交易日盘前（北京时区 <15:00）打开页面，F=上一交易日，复盘显示昨日完整数据，前瞻显示昨晚选股池，当日显示今早简报（实时生成中）。
- [ ] AC4 **盘后过渡窗（15:00-17:15）**：F 仍=T-1，但复盘视图数据日=T（15:00 定时器推进），显示 T 日实时涨停池/情绪 + 未产出区"待 {cron时间} 产出"占位；当日=T-1 简报快照；前瞻显示"待 17:15 产出"（实际 16:30 kline 就绪后可手动"载入"）；任务状态卡片可见 cron 进度。
- [ ] AC5 **17:15 F 推进**：用户从 17:10 开着页面到 17:20，17:15 定时器推进 F（T-1→T），三视图全量刷新——复盘=T 完整、当日=T 简报快照、前瞻=T+1 选股池。
- [ ] AC6 **15:00 复盘独立推进**：用户从 14:50 开着页面到 15:10，15:00 定时器推进复盘数据日到 T（F 不变），复盘视图显示 T 日实时数据 + 未产出占位。
- [ ] AC7 **过渡窗轮询 + 今日完成状态**：15:00-17:15 窗口每 60s 轮询 `GET /api/scheduled-tasks`，前端从 `last_run_at`+`cron_expr`+`server_now` 推算"今日完成"状态（done/error/running/pending），任务变 done 时卡片标绿 + 任务项带"载入"按钮（refetch 对应视图）；17:15 后停止轮询。过渡窗开局（15:00）所有任务正确显示 pending（不因昨日 `last_run_status=success` 误判全绿）。
- [ ] AC8 **时区 bug 修复**：`PremarketSelectionSection`（L20）、`PostMarketReview`（L44）、`IntradayMonitor`（L93）不再用 `new Date().toISOString()`，日期来自 `dateTriplet`。北京时间盘前打开前瞻 Tab，日期正确。定时器用 `next_*_at - Date.now()` 算延时，非北京时区用户定时器正确触发（不在本地 15:00 误触发）。
- [ ] AC9 **date picker 手动回看**：选历史日期 F'，三视图统一以 F' 推算（前瞻=F' 的下一交易日，非日历+1）。
- [ ] AC10 **时段自动高亮**：盘前高亮"前瞻"、盘中"当日"、盘后过渡（15:00-17:15）"复盘"、盘后（17:15 后）"前瞻"，用户可手动切。非交易日不高亮（或高亮"复盘"显示最近交易日数据）。
- [ ] AC11 **任务状态卡片**：公共区常驻，显示盘后 cron 任务列表 + 今日完成状态 + 预计完成时间，点击展开详情。
- [ ] AC12 **离线全测绿**：`pytest` + `vitest` + `tsc` 全绿。既有 `Workflow.test.tsx` 等测试随容器重写更新 mock 适配。
- [ ] AC13 **dev server 冒烟**：三 Tab 切换正常、dateTriplet 端点返回正确、时区修正后盘前打开日期正确、任务状态卡片显示 + 过渡窗轮询正常 + 今日完成状态正确（15:00 开局不全绿）。
- [ ] AC14 **非交易日边界**：周六/节假日打开页面，`stage=non_trading`，F=最近交易日，定时器不触发推进，三视图显示 F 数据，任务状态卡片显示"非交易日，无采集任务"。长假后首日盘前 F=长假前最后交易日。

## 7. spec 逻辑冲突审查（AGENTS.md 强制）

本 spec 动笔前已检索历史 spec，偏差点 14 条，详见下表。**关键结论：数据层零返工**——S048 快照、S050 票根/影子收益、S054 daily-review、S068 流转原子性、S084 DiagnosisCard、S087 funnel_cache、S063 SentimentContext、S088 暴风雨预测——所有数据层均不受三视图影响，只改前端呈现位置和容器结构。

| # | 历史 spec | 原设计 | 本 spec 决策 | 冲突类型 | 处置 |
|---|---|---|---|---|---|
| 1 | S087 6-tab pipeline | 6-tab：T-1/语境/盘前/盘中/盘后/战法 | 3-tab：复盘/当日/前瞻 | 替代 | **替换**：S087 组件复用至三视图对应 Tab |
| 2 | S048/S036 三阶段 | 盘前/盘中/盘后三阶段卡 | 三视图 Tab | 替代 | **替换**：阶段卡→三视图 Tab，快照机制复用 |
| 3 | S074 market_phase | `get_current_stage()` 时段判定 | F 锚点 + 17:15 推进 + 复盘 15:00 独立推进 | 替代 | **替换**：`get_current_stage()` 保留给调度器，前端不再依赖 |
| 4 | S048 快照日期模型 | 快照以 `data_date` 为键 | F→review/today/forward 映射层 | 兼容 | **共存**：快照机制不动，上层加转换层 |
| 5 | S054 盘后三问页 | PostMarketReview 三问 | 三问归"复盘"Tab，盘后"当日"=简报快照 | 替代 | **替换**：数据层零返工，呈现位置重分配 |
| 6 | S048 date picker | 选历史快照日 | 选复盘日 F | 兼容 | **共存**：UI 复用，语义从"历史日"改"复盘日" |
| 7 | 无 | 无统一日期端点 | 新增 `GET /date-triplet` | 补充 | **共存**：新端点，不破坏既有 |
| 8 | S090 PremarketSelectionSection | `new Date().toISOString()` | 从 dateTriplet 取日期 | 补充 | **替换**：修复时区 bug |
| 9 | S084 两级 Tab | 选股池/战法两级 Tab | 三视图 Tab | 替代 | **替换**：选股池/战法内容移入三视图对应 Tab |
| 10 | S087 funnel_cache | run_funnel 落缓存表 | 三视图复用缓存（键不改） | 兼容 | **共存**：缓存键不改——现有以 date 为键的缓存在手动回看 F' 时本来就查 F'，改键不解决任何已陈述问题且违反 YAGNI |
| 11 | S068/S026 轮询 | POST refresh + 5s 轮询采集状态 | 17:15 定时器 + 过渡窗 60s 轮询任务状态（非采集状态） | 替代 | **替换**：采集逻辑复用，触发机制改定时器；过渡窗轮询的是 scheduled-tasks 端点（非 pre-market refresh），轮询成本 SQLite 本地读 120 次/2h 可忽略 |
| 12 | S088 暴风雨预测 | 接入"语境"Tab | 归"当日"Tab 决策语境 | 兼容 | **共存**：重新分配呈现位置 |
| 13 | S063 情绪管线 | PreMarketBriefing 顶部 WeatherDecisionBar | WeatherDecisionBar 归"当日"Tab | 兼容 | **共存**：数据层不动，呈现位置重分配 |
| 14 | S090 PremarketSelectionSection 日期 | `date` prop + UTC fallback | `date` prop 不变，调用方传 dateTriplet 值 | 兼容 | **共存**：接口不变，调用方计算逻辑变 |

**G1-G6 grill 修正对照**（spec 初版 → 终版）：
- G1：F 推进 15:00→17:15（当日/前瞻），复盘独立 15:00 推进 + 渐进填充
- G2：任务状态卡片公共区常驻（复用 scheduled-tasks 端点）
- G3：前瞻过渡窗"待 17:15 产出" + 任务卡片标红
- G4：盘后"当日"=今早简报快照 + "17:15 后可刷新"标注
- G5：盘后默认高亮 复盘→前瞻（核心动作=选 T+1）
- G6：过渡窗 15:00-17:15 每 60s 轮询任务状态，17:15 后停

## 8. 合规自查（AGENTS.md §工程底线）

- [x] 不臆造数据：盘后过渡窗复盘显示 T 日实时可得部分 + 未产出区占位"待 {cron时间} 产出"，不假数据；盘后"当日"=今早简报快照（已落盘真实数据）+ 标注，不预生成 F+1 简报（无源不臆造）；任务状态卡片的"今日完成"状态由前端从 `last_run_at`+`cron_expr`+`server_now` 推算（诚实标注，不臆造 done）
- [x] 私有数据隔离：dateTriplet 端点仅返日期三元组 + 时刻元数据，不涉及个股/持仓私有数据；任务状态卡片复用 scheduled-tasks 端点（已有端点，不新增数据暴露面）
- [x] em_get 防封：本 spec 不新增外部数据请求，dateTriplet 纯 `vr_paths` 本地计算 + `datetime.now(BEIJING_TZ)`；任务状态卡片复用已有 scheduled-tasks 端点（SQLite 本地读，无外部请求）；过渡窗轮询 60s × 2h = 120 次 SQLite 本地读，负载可忽略（Oracle L2）
- [x] 可复现：dateTriplet 给定相同 (date, 北京 now) 返回相同结果，纯函数；定时器用 `next_*_at - Date.now()` 算延时，服务器时间驱动可复现
- [x] 时区盲点标注（GR5）：R18 后端推算假设服务器本地时区=北京（`last_run_at` 存的是 naive `datetime.now()`，无时区后缀）。当前本地自托管服务器在北京时区，假设成立。未来云部署到非北京时区时需另立 spec 把 `last_run_at` 写入改为 `datetime.now(BEIJING_TZ)`——当前盘后 cron 不跨午夜（15:30-17:15 北京=07:30-09:15 UTC，同一天不跨午夜），碰巧安全，但不是可靠设计。
- [x] 涉及数据输出/AI 提示词/交易信号：本 spec 不涉及数据输出变更、不改 AI 提示词、不改交易信号——仅改前端呈现容器 + 日期计算 + 任务状态展示
- [x] 盘后 refresh 端点验证（Oracle M6）：R4 依赖 `POST /api/workflow/pre-market/refresh` 盘后把当日快照刷新为收盘口径。该端点原设计是盘前采集（依赖竞价/分时实时源），盘后调用是否产出"最终收盘口径"需在 AC13 冒烟中验证——若盘后 refresh 不能产出收盘口径（如竞价数据盘后不可得），R4 的"17:15 后可刷新"需降级为"17:15 后快照不变，用户看复盘 Tab 的完整收盘数据"
