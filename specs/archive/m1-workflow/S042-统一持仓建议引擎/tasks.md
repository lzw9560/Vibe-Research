# 任务拆分 · S042 统一持仓建议引擎

> 对应：`spec.md`（需求）、`plan.md`（技术方案）
> 依赖：S040 先合并。

---

## 阶段 A · 建议引擎核心（R1/R2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | `position_advisor_v2.py` 骨架：类定义 + `__init__` + 惰性 `strategy_results` 属性 | — | `backend/strategies/position_advisor_v2.py` | import 不报错 | — |
| A2 | `_get_win_rate(strategy_code)` 方法：查 strategy_backtest 结果，有返回测值，无返回成值 + source 标注 | A1 | `backend/strategies/position_advisor_v2.py` | mock 8 战法结果 -> 正确返回 win_rate + source | A2,A9 |
| A3 | `advise_recommendations(limit)` 方法：读今日推荐 -> 查 gene -> 匹配战法 -> 调 v1 PositionAdvisor 算仓位 -> 附加 win_rate | A2 | `backend/strategies/position_advisor_v2.py` | mock 推荐列表 -> 输出含 win_rate_source="backtest_90d" | A2 |

## 阶段 B · 自选 + 持仓建议（R3/R4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | `advise_watchlist()` 方法：读自选 code 列表 -> 查 gene_scores -> 有信号给建议、无信号标 no_signal | A2 | `backend/strategies/position_advisor_v2.py` | mock watchlist 含有/无信号 code -> 正确分类输出 | A3 |
| B2 | `_decide_action(pnl_pct, win_rate, cost)` 方法：按 spec D2 规则表返回 add/reduce/close/hold | — | `backend/strategies/position_advisor_v2.py` | 8 种条件分支单测全覆盖 | A4 |
| B3 | `advise_holdings()` 方法：读 portfolio -> 逐笔查 gene -> 匹配战法 -> 算 win_rate -> 调 _decide_action | B2 | `backend/strategies/position_advisor_v2.py` | mock portfolio + gene -> 正确输出 action | A4,A5 |
| B4 | 止损线判断：pnl_pct < -3% 或触及 stop_loss -> close | B3 | `backend/strategies/position_advisor_v2.py` | mock pnl_pct=-4% -> action="close" | A5 |
| B5 | `summary(limit)` 方法：聚合三场景返回 dict | A3,B1,B3 | `backend/strategies/position_advisor_v2.py` | 调 summary -> 含 recommendations/watchlist/holdings | A1 |

## 阶段 C · API 端点（R5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | `routers/advisory.py` 新建 + `GET /api/advisory/summary` 端点 | B5 | `backend/routers/advisory.py` | curl -> 返回三场景 JSON | A1 |
| C2 | 路由注册到 main app | C1 | `backend/main.py` 或 `backend/app.py` | `/api/advisory/summary` 可达 | A1 |
| C3 | 单测：advisory 端点 mock 全链路 | C1 | `backend/tests/test_advisory.py` | pytest -m "not live" 过 | A7 |

## 阶段 D · 前端（R6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| D1 | `api.ts` 新增 `advisorySummary(limit)` | C1 | `frontend/src/lib/api.ts` | tsc 过 | A8 |
| D2 | `Advisory.tsx` 推荐标的建议表格 | D1 | `frontend/src/pages/Advisory.tsx` | tsc 过；mock 渲染表格 | A8 |
| D3 | 自选股建议表格（含 no_signal 行） | D1 | `frontend/src/pages/Advisory.tsx` | tsc 过 | A3,A8 |
| D4 | 持仓建议表格（含 action / pnl_pct / win_rate_source） | D1 | `frontend/src/pages/Advisory.tsx` | tsc 过 | A4,A8 |
| D5 | 每条建议挂"历史统计特征，市场有风险" | D2,D3,D4 | `frontend/src/pages/Advisory.tsx` | 肉眼确认 disclaimer | A6 |
| D6 | 路由注册 + 导航入口 | D2 | `frontend/src/router.tsx` + nav | 路由可达 | A8 |

## 阶段 E · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| E1 | pytest -m "not live" 全绿 | C3 | — | 全过 | A7 |
| E2 | live 冒烟：`GET /api/advisory/summary` 返回三场景 | C2 | — | curl 确认 | A1 |
| E3 | 前端建议页面三场景渲染 | D6 | — | 肉眼确认 | A8 |
| E4 | 合规自查：grep 无"买入/卖出"指令词；win_rate_source 标注齐全 | — | — | grep 无违规词 | A6,A9 |
