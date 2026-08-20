# Spec: S087 — 工作流 tab 按 pipeline 步骤重设计

> 状态：草案
> 作者：lzw9560　日期：2026-08-20
> 关联：S084（选股池战法解耦，两级 tab）/ S086（涨停战法 dispatch_match 统一）/ S063（SentimentContext pipeline 头部）/ S004（candidate_funnel R1/R2/R3）
>
> grill 记录：经 grilling skill 多轮审查（7 项决策 + 3 agent 战法分叉点分析 workflow），用户全部认可。

## 1. 问题 / 目标

当前 `Workflow.tsx`（934 行）用两级 tab（战法/选股池）+ 降级状态机视图，不按 pipeline 步骤组织；选股池 tab 调 `run_funnel("all")` 全市场漏斗慢（实测 8.9 分钟），前端 useQuery 超时返空 → 降级文案"选股池数据未取得"。

**目标：重设计为 5-tab pipeline（T-1/语境/盘前/盘中/盘后），每 tab 按交易闭环步骤组织内容；选股池缓存优先消解慢端点；战法/选股池两级 tab 融入盘前 tab。**

## 2. 背景

- 现状：`Workflow.tsx` 有 `PipelineProgressBar`（t1/ctx/pre/intraday/post 五段，已有）+ 两级 tab（战法/选股池，S084）+ legacy 状态机视图（盘前/盘中/盘后 StageCard）+ 战法卡片网格（10 张）。
- S086 已统一战法分发为 `dispatch_match`（12 战法，含 dragon_head 无条件放行、storm_reversal fbt 匹配）。
- S084 R1-only 改造后 funnel R2/R3 **不过滤**（`r2_kept=list(r1_kept)`，采集统一 `build_indicator_set`，`final = R1 涨停 ∪ 自选`）。战法因子 narrowing 落在 `dispatch_match`，不在 funnel 采集层。
- 战法分叉点（3-agent 分析）：**分叉主轴=匹配阶段**（源 fork），下游入场/仓位/卖出/结算=派生 fork；R1/R3/盘中监控**不分叉**（统一涨停池 / 统一八项标准 / 炸板=市场事件）；R2 因子 narrowing + 匹配 + 入场 + 仓位 + 卖出 + 结算**按战法分叉**。
- `run_funnel` 慢根因：全市场涨停股 × K线/IndicatorSet 采集，无结果落库，前端每次打开实跑。

## 3. 需求清单

- [ ] R1：5-tab 按 pipeline——T-1 / 语境 / 盘前 / 盘中 / 盘后，`PipelineProgressBar` 的 current 驱动默认 tab（按后端 `stageKey` 自动定位当前阶段）
- [ ] R2：T-1 tab = 数据就绪检查（薄状态卡）——gene_scores 新鲜度 / STI T-1 行 / 天气 state / derived 分时是否采集
- [ ] R3：语境 tab = SentimentContext 决策语境卡（薄）——天气 / 熔断软标注（建议降仓）/ allowed_styles / weather_recommended / 市场 4 率
- [ ] R4：盘前 tab = 闭环 ①选股 → ②战法匹配 → ③仓位建议
- [ ] R5：①选股步 = 统一涨停池 R1/R2/R3 采集 + final（复用 `FunnelLayers`+`SelectionPipeline`，不重写）；**不按战法分叉采集**
- [ ] R6：②战法匹配步 = 双视图——默认 票×战法命中 matrix（每只 final 候选展示命中哪几条战法）/ 可切 按战法分列（12 战法各命中列表）
- [ ] R7：③仓位步 = PositionAdvisor + P2 仓位闸/龙虎榜风控；参数按战法（12 套 stop/take/max_hold），比例统一（confidence/win_rate→%）
- [ ] R8：盘中 tab = 统一监控（①实时监控 → ②炸板预警 → ③动态调仓），**不按战法分叉**（炸板=市场事件）；持仓行内标战法 max_hold；盯盘教练保留
- [ ] R9：盘后 tab = ①结算 → ②LLM 复盘 → ③胜率更新，按战法聚合（结算 horizon=max_hold_days，backtest by_strat 聚合 win_rate）；拓扑展示入口保留
- [ ] R10：选股池 bug 治理 = `run_funnel` 结果落本地缓存表（盘后/盘前定时跑写库），前端 tab 读缓存秒开；"重新跑"按钮单独触发实跑（缓存拿不到才请求的兜底）
- [ ] R11：战法/选股池两级 tab 融入盘前 tab 的①②步（不再独立 tab）；legacy 状态机视图降级为盘前 tab 内折叠"状态机入口"卡（不删能力）
- [ ] R12：留非涨停选股 + 非涨停战法站位（`run_non_limitup_funnel` 独立来源，market_scan 战法主路径仍从涨停池取候选——架构接缝已知，tab 设计时非涨停池作独立站位，不与涨停池 dispatch_match 混淆）
- [ ] R13：5 tab 各带 `AskAiButton` 并携带**该 tab 的当前页面上下文**（T-1=数据就绪状态、语境=SentimentContext、盘前=候选/命中/仓位、盘中=持仓/预警、盘后=结算/胜率）；新增页面也补 AskAiButton + 上下文（约定成规）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/pages/Workflow.tsx` | 重写：5-tab pipeline 结构（替代两级 tab + legacy 视图），按 grill mockup |
| `frontend/src/components/workflow/`（新建） | T1Tab/ContextTab/PreMarketTab/IntradayTab/PostMarketTab 子组件 |
| `frontend/src/components/workflow/PipelineProgressBar.tsx` | 复用，current 驱动默认 tab（可能扩展可点击跳 tab） |
| `frontend/src/components/workflow/StrategyMatchMatrix.tsx`（新建） | 票×战法命中 matrix 视图 + 按战法分列切换 |
| `frontend/src/lib/query.ts` | 选股池 query 改缓存优先（读缓存端点，fallback 实跑） |
| `backend/routers/candidates.py` | 加 GET 读缓存端点（返回最近 run_funnel 结果）+ 保留 POST 实跑 |
| `backend/candidate_funnel/funnel_cache.py`（新建） | run_funnel 结果落本地表（date → FunnelResult），定时写 + 读 |
| `backend/scheduled_tasks.py` | 盘后/盘前定时跑 run_funnel 写缓存（如新增 task type） |

## 5. 设计方案

5-tab pipeline 结构（grill 确认）：

```
[T-1] [语境] [盘前] [盘中] [盘后]   PipelineProgressBar: t1→ctx→[pre]→intraday→post
```

- **T-1 tab**：数据就绪检查（gene_scores/STI/天气/derived 新鲜度，薄状态卡）
- **语境 tab**：SentimentContext（天气/熔断软标注/allowed_styles/4率，薄卡）
- **盘前 tab**：①选股（统一涨停池+R2/R3采集+final，缓存优先）→ ②战法匹配（双视图：票×战法 matrix 默认 / 按战法分列可切）→ ③仓位（PositionAdvisor+P2）
- **盘中 tab**：统一监控（炸板预警/盯盘教练，不分叉）+ 持仓行内标 max_hold
- **盘后 tab**：结算→LLM复盘→胜率（按战法聚合）+ 拓扑入口

**取舍**：
- 粒度选 5（非 3）：T-1/语境 真独立 tab（非只进度段）——显式化"跑选股前输入就绪+语境"前置步骤。
- 战法/选股池融入盘前（非独立 tab）：它们是盘前内容维度，不是时间轴。
- 匹配步双视图（c，非 a/b）：票×战法 matrix 是 pipeline 产出视角（默认），按战法分列保留原战法分流入口思路。
- 缓存落库（非分步端点/纯前端超时）：run_funnel 结果落表，盘后定时跑，前端读缓存秒开，实跑按钮兜底。
- 盘中不分叉（非按战法）：炸板=市场事件，全市场统一规则（`bomb_alert_rules` 签名不含战法）。

## 6. 验收标准

- [ ] A1：5 tab 渲染（T-1/语境/盘前/盘中/盘后），默认 tab 跟 `stageKey` 自动定位
- [ ] A2：盘前 tab 三步（选股/匹配/仓位）闭环骨架呈现
- [ ] A3：选股步缓存优先——读缓存端点秒开，"重新跑"按钮触发实跑；不再"选股池数据未取得"降级（缓存有数据时）
- [ ] A4：战法匹配步双视图可切（票×战法 matrix 默认 + 按战法分列）
- [ ] A5：盘中 tab 统一监控（不分叉），持仓行内标 max_hold
- [ ] A6：盘后 tab 按战法聚合（结算/复盘/胜率）
- [ ] A7：保留项在——盯盘教练（盘中）、拓扑展示（盘后入口）、legacy 状态机（盘前折叠卡）
- [ ] A8：后端 run_funnel 结果落库表 + 读缓存端点 + 实跑按钮兜底
- [ ] A9：前端 build 通过 + 关键页面路由可访问
- [ ] A10：既有后端端点 0 回归（S086 改动不受前端重设计影响）
- [ ] A11：5 tab 各有 AskAiButton 携带该 tab 上下文；新增页面带 AskAiButton + 上下文

## 7. 合规与工程底线自查

- [ ] 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1 弱合规）；前端挂轻量风险提醒
- [ ] 判断可复现：战法命中/仓位参数来自后端 dispatch_match + 注册表（已验算），前端只呈现不臆造
- [ ] 涨停四池/连板股榜个股属公开榜单客观事实（可呈现 code/name）
- [ ] 用户私有数据（持仓/key）未进 git、未上传（前端只读后端 API）
- [ ] run_funnel 缓存表存本地 `.vibe-research/`（VR_DATA_DIR），不进 git；新增端点无东财直连（走既有 em_get）

## 8. 测试计划

- 前端：`npm run build` 通过 + 浏览器手动验收 5 tab 切换 + 双视图 + 缓存优先
- 后端：`pytest backend/tests/ -m "not live"` 全绿（funnel 缓存表 + 读端点单测）
- 回归：S086 战法端点 + workflow 端点 0 回归

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 前端 Workflow.tsx 大重写 | 中 | 分组件拆（5 tab 子组件），保留 legacy 折叠卡不删能力 |
| run_funnel 缓存表 schema | 低 | 纯落库，无数据迁移；表不存在时 fallback 实跑 |
| 并发编辑器（Workflow.tsx 有预存改动） | 中 | 动前 git pull 确认基线；显式 git add 不打包他人改动 |
| 非涨停池站位与涨停池 dispatch_match 混淆 | 低 | R12 已标注架构接缝，tab 设计时非涨停池独立站位 |

回滚：前端 git revert（纯前端 + 1 后端缓存表，无数据迁移）。

## 10. 迭代决策（grill 第二轮，2026-08-20，用户浏览器验收后 13 条反馈）

第一版实现后用户实际验收，迭代 13 项（R14-R25）：

- **R14（战法 tab）**：加第 6 tab"战法"——战绩（forward_test lift/winrate + prediction_ledger 验证 + strategy_backtest by_strat 聚合）+ 改参数（注册表 stop/take/max_hold + S081 阈值 config）。原战法卡片网格恢复为独立 tab（第一版误删，⑫⑬ 修正）。
- **R15（tab 顶部）**：6-tab 导航移到页面最顶（PageHeader 上方）；盘前三步①选股/②匹配/③仓位可折叠 + 线性流动箭头（→）。
- **R16（涨停池缓存+改名）**：选股步改名"涨停池" + 读近多日缓存（不只当日）。
- **R17（漏斗可收缩）**：FunnelLayers 各层可折叠/展开。
- **R18（R2/R3 UI 标注）**：R2/R3 标"采集层"（不过滤，标注标的数不变原因 = S084 下放战法层）。
- **R19（板块轮动）**：放语境 tab，接 `/api/strategy/funnel/sector-rotation`（有数据；`/api/sector/rotation` 空是错端点弃用）。
- **R20（删非涨停池卡）**：盘前 tab 非涨停池站位卡删除（⑩ 站位→占位错字消除，不放别处）。
- **R21（终选因子详情）**：final_candidates 列表缩略 + 点击展开因子详情（表格放不下时）。
- **R22（strategy_score 标注）**：战法匹配括号数字标"策略分"（非 confidence）。
- **R23（仓位内嵌）**：盘前③仓位步内嵌 PositionAdvisor + P2 字段（不跳转 /advisory）。
- **R24（盘中监控命中标的）**：盘中 tab 默认展示所有战法命中标的的监控（不只持仓）。
- **R25（每日结算）**：用现有 forward_test_daily + prediction_ledger + forward_test_t1_settle，不扩候选×战法矩阵。

## 11. 实现记录

第一版（commit d7a47ad）落地：5-tab + funnel_cache + candidates 端点 + T1Tab/ContextTab/StrategyMatchMatrix + Workflow.tsx 重写 + B5 缓存优先 + 单测。第二版（迭代 R14-R25）待实现：6-tab（+战法 tab）+ 上述 UI 调整。
