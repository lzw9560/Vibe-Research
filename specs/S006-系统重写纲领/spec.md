# Spec: S006 — 系统重写纲领

> 状态：主体已实现（子项 S007/S008/S009/S010/S011/S013/S014/S015 均已落地）——2026-08-13 归档补录。残余：S012 已废弃（被 S036 替代）、S016 部分实现（基建已搭，IO 回放夹具/回归专项/CI/覆盖率门槛待补）。纲领 spec 本身不再单独签字，以子项各自落地为准。
> 作者：Claude  日期：2026-07-29
> 关联：`../S001`–`../S005`、`../../ARCHITECTURE.md`、`../../CLAUDE.md` §0/§1（含 2026-07-29 边界调整）、`../../docs/CODE_REVIEW_REPORT.md`
> 技术方案详见本 spec §5 + 子 spec（S007–S016）各自 `plan.md`。
> 本 spec 是**纲领**：统一数据契约、收口调度、重写前端数据层与 UI、补测试网。逐子项独立签字落地。

---

## 1. 问题 / 目标

系统在功能扩张中累积结构性可维护性债务：数据层双轨制（裸 dict 与 Pydantic 不衔接）、调度三套重复+线程/async 混用、前端 11 个巨型 page+4 套 fetch 封装+零测试、多个静默功能坏死被 try/except 掩盖（`risk_models.get_kline` 恒返 0.0、`scheduled_tasks` 缺 import）。局部修补已不足以偿还。

**目标**：以可维护性+UI 易用性为驱动，在长分支 `rewrite/main` 上分 9 个子 spec 渐进重写，每切片可独立回切 `develop` 上线；重写后数据层统一 Pydantic 契约、调度单一收口、前端一页一责+组件契约统一、测试网覆盖纯函数 ≥80%。

## 2. 背景

- 数据层：`astock.py`(862) 被 32 文件 import；同概念 4 套形状（`change_pct`/`pct`、`mcap_yi`亿/`mcap`元）；4+ 套缓存/限流并存。
- 调度：`scheduler.py`(103,硬编码窗) 与 `scheduled_tasks.py`(587,CronScheduler 未播种) 重叠；盘后预计算抄三份；SQLite 无 WAL。
- 工作流：`workflow_state_machine.py` 七态定义了从未接线；`realtime`/`post_market_workflow` 全 TODO 桩。
- AI 出口：`chat.TOOLS`/`_exec_tool` 硬编码，`mcp_server` 寄生 `chat._exec_tool` 私有。
- 前端：`lib/api.ts`(1239) 含 60类型/80 endpoint/20 个绕过抽象的裸 fetch；29 页面 267 处手写 loading/setError；router 无懒加载；22 项扁平导航；DailyReview 28 state/10 区块；移动端 22 项横滚 Tab 不可用；echarts 不跟主题；设计文档落地率 ~30%。
- 测试：后端纯计算层好（limitup 70%/sti 75%），原始数据层/调度/状态机 0 覆盖；前端零测试。
- 合规边界：2026-07-29 `CLAUDE.md` §1 调整——允许教育研究性判断，守"不承诺收益/可复现/私有数据隔离/四池聚合不泄露个股"。

## 3. 需求清单

- [ ] R1 数据契约：建 `backend/models/`（Pydantic v2：Quote/Valuation/Report/News/MarketSnapshot/FundFlow/KLine），冻结字段与单位约定
- [ ] R2 数据层迁移：astock/gstock/market 返回模型；路由挂 `response_model`；修 `get_kline`/datetime/重复定义 bug
- [ ] R3 前后端类型同步：S008 后跑 openapi-codegen 生成 `lib/api/types.ts`，替手写 60 接口
- [ ] R4 工具注册表：`ai/tools/registry.py` 声明式注册，chat/mcp/cli 三出口共走，`SYSTEM_PROMPT` 按新合规边界放宽措辞
- [ ] R5 调度收口：扩展现有 cron 支持 `*/n`/范围（不引入 APScheduler）；lifespan 挂主循环；SQLite 加 WAL+busy_timeout+连接池+去重；修 import/add_run bug；**先补测+修 bug+播种验证再删 scheduler.py**；状态机接线落库
- [ ] R6 工作流边界：realtime/post_market 桩 `NotImplementedError` + UI 标灰（不补功能）
- [ ] R7 前端数据层：统一 `lib/api/client.ts`；TanStack Query hooks 替 267 处手写；router 全量懒加载；apiKey 移后端代理
- [ ] R8 前端 UI 重设计：22 项扁平→5 组导航；首页拆分下沉（28→~8 state）；11 巨型 page 拆分（<400 行）；workflow 三页抽 `<WorkflowStage>` 骨架；三态/表格/筛选统一契约；移动端重做（5 项常驻 Tab）；视觉系统补令牌+echarts 跟主题；暖橙主题保留+加入口
- [ ] R9 AI 对话重做：`useChatStream` hook + 增量渲染（不全量 re-parse）+ 历史持久化 + 全局入口
- [ ] R10 测试网：后端纯函数 ≥80%，IO 用录制回放 contract test；前端 vitest + @testing-library；回归基线录 10 只代表 code 快照
- [ ] R11 配置/基础设施：config 拆分、`infra/{cache,resilience}` 收口 4+套缓存/限流/熔断、cache_response 修 key、路由自动发现

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/astock.py`/`gstock.py`/`market.py`/`risk_models.py` | 🔥重写为模型返回 |
| ➕`backend/models/`、`backend/ai/tools/registry.py`、`backend/infra/{cache,resilience}.py`、`backend/data/sources/*` | ➕新增 |
| `backend/chat.py`/`mcp_server.py`/`cli_runtime.py` | 🔥重写（走 registry） |
| `backend/scheduled_tasks.py`/`workflow_state_machine.py`/`app.py` | 🔥重写 |
| `backend/scheduler.py`/`fallback.py`/`data_provider/` | 🗑️删除/合并（删 scheduler 在 S011 最后） |
| `backend/routers/*.py`（35）+ `config.py` | ✏️统一信封/拆分 |
| `frontend/src/lib/api.ts`/`llm.ts`/`candidates.ts`/`value_funnel.ts`/`watchlist.ts` | 🔥重写/🩹合并 |
| ➕`frontend/src/lib/query/`、`src/test/`、`components/ui/{PageSkeleton,ErrorRetry,FilterBar}` | ➕新增 |
| `frontend/src/router.tsx`/`main.tsx`/`Layout.tsx`/`navigation.ts`/`useDarkMode.ts` | 🔥重写 |
| 11 巨型 page + workflow×3 | 🔥拆分/抽骨架 |
| `STITimelineChart.tsx`/`Badge.tsx`/`Button.tsx`/`index.css` | ✏️令牌化 |
| `frontend/package.json` | 🩹删 zustand 或落地；加 vitest/tanstack-query |
| ➕`backend/tests/contract/baseline/` | ➕回归基线录制夹具 |

## 5. 设计方案

**策略**：渐进式长分支 `rewrite/main`，每子 spec 独立可验证、可回切 develop。**不一次性大爆炸**（评审认定大爆炸与 4 个 CRITICAL 风险矛盾）。

**顺序（修订后）**：
1. S007 契约层：models/ + 回归基线录制夹具 + 契约测试骨架（CRITICAL 前置）
2. S008 后端数据层：迁模型 + response_model + 修 bug
3. S009 codegen：openapi-codegen 替手写 TS（**必排在 S008 后**，解循环依赖）
4. S010 工具注册表 + SYSTEM_PROMPT 新边界
5. S011 调度收口（补测→修 bug→删 scheduler→lifespan→状态机接线）
6. S012 工作流标灰（不补功能）
7. S013 前端数据层（client+TanStack Query+懒加载+apiKey 代理）
8. S014 前端 UI 重设计（§3 R8 全部）
9. S015 配置/基础设施
10. S016 测试网（纯函数 ≥80% + IO 录制回放 + 前端 vitest）
11. 切换：全套测试+live 冒烟通过后合并 main

**取舍**：不引入 APScheduler（扩展现有 cron 几十行即可）；不补 realtime/post 功能（标灰，补实现单独立 spec 涉合规审查）；迁移层按消费者分组有退出条件，不一 `to_dict()` 通吃；暖橙主题保留+加入口（不删）；不搞"重写前后取数比对"口号，改用录制回放基线。

**UI 信息架构**：5 组（市场总览/个股研究/交易工作台/投资管理/系统）；首页拆分下沉；交互统一契约（PageSkeleton/EmptyState/ErrorRetry/DataTable/FilterBar + pctColor）；移动端侧栏隐藏+全屏抽屉+5 项 Tab；视觉补间距/字号令牌+echarts 跟主题。

## 6. 验收标准

- [ ] A1 `backend/models/` 7 模型定义并冻结，前后端类型由 openapi-codegen 同步（无手写漂移）
- [ ] A2 `risk_models` 波动率/回撤/流动性不再恒 0.0（`get_kline`→`kline` 修），单测锁住
- [ ] A3 `scheduled_tasks` cron 匹配+各 TaskExecutor 有单测；`scheduler.py` 已删；无 import/add_run bug
- [ ] A4 SQLite 启用 WAL+busy_timeout；盘后预计算无并发写竞争
- [ ] A5 状态机接入 `PreMarketWorkflow.run()` 并落库；realtime/post 桩标灰
- [ ] A6 chat/mcp/cli 三出口共走 registry；mcp 不调 `chat._exec_tool` 私有
- [ ] A7 前端 `lib/api/client.ts` 单一 `request<T>`；4 套封装与 20 裸 fetch 消除；TanStack Query 覆盖
- [ ] A8 前端 11 巨型 page 均 <400 行；workflow 三页共享骨架
- [ ] A9 导航 5 组可折叠；首页 ≤8 state；移动端 5 项 Tab
- [ ] A10 三态统一（PageSkeleton/EmptyState/ErrorRetry）；echarts 跟主题
- [ ] A11 后端纯函数覆盖率 ≥80%；IO 录制回放 contract test 覆盖 10 只代表 code；前端 vitest 关键 page 有快照
- [ ] A12 全套 `pytest -m "not live"` 过；live 冒烟（:8900 + MCP 5 工具实测 600519/000858）通过
- [ ] A13 涉及市值/估值数据跑 `~/tools/financial_rigor.py`/`report_audit.py` 验算通过

## 7. 合规自查（按 CLAUDE.md §1 弱合规 2026-07-30；私人助理定位）

**仪式类（已降为风险提醒，非硬门槛）**：
- [ ] 研判输出挂轻量风险提醒「历史统计特征，市场有风险」，不强制「不构成投资建议」墙
- [ ] 可给方向性研判/买卖时机/收益预期/操作建议，不承诺确定性保证（用户即决策者，半自动化）
- [ ] 涨停四池/连板股榜可如实呈现个股 code/name（公开榜单）；Emotion 作聚合指标不含个股名属设计选择，非红线
- [ ] `chat.SYSTEM_PROMPT` 可给方向性研判，不承诺确定性收益

**工程底线（保留，保护用户自身的钱与数据）**：
- [ ] 判断可复现/不臆造/不心算（`financial_rigor.py`/`report_audit.py` 验算）
- [ ] 用户私有数据（持仓/研报/key）只存 VR_DATA_DIR，不进 git/不上传/不落 home
- [ ] 新增东财端点走 `em_get()` 限流/熔断/代理探测，不裸调 requests

## 8. 测试计划

- 单测：各子 spec 落地时补，纯函数 ≥80% 行覆盖
- 契约：`tests/contract/baseline/` 录 10 只代表 code（A股+港股+韩股）真实响应，回放比对字段值
- 集成：`pytest -m "not live"` 全量；live 标记冒烟（:8900 + MCP 5 工具）
- 前端：vitest + @testing-library，client 契约 + 关键 page 快照
- 数据验算：市值/估值输出跑 `financial_rigor.py`/`report_audit.py`

## 9. 风险与回滚

- 🔴 astock 32 依赖者：契约冻结+分组迁移+适配层退出条件；每切片可回切 develop
- 🔴 前端零测试：S007/S016 先立基线+vitest 再拆
- 🟠 长分支分叉：develop 仅接 P0 fix，每周 rebase 同步；每切片独立可验证故可中止切回渐进式
- 🟠 合规边界放宽风险：判断卡片挂轻量风险提醒（非强制墙）+ 不承诺确定性收益；SYSTEM_PROMPT diff 审查
- 回滚：任一切片失败可单独回切 develop，不牵连其他切片
