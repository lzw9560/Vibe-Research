# Spec: S042 — 统一持仓建议引擎（推荐标的 + 自选 + 持仓，三场景）

> 状态：已实现（2026-08-09）——R1-R6：后端 position_advisor_v2 + advisory 路由 + 18 测试 + TestClient 冒烟 200；前端 Advisory.tsx 三场景页 + advisorySummary API + tsc green
> 作者：Codex  日期：2026-08-09
> 关联：`../S040-历史数据回填90天/spec.md`（90 天回测胜率是建议依据）、`backend/recommendation_engine.py`、`backend/strategies/position_advisor.py`、`backend/strategies/strategy_backtest.py`、`backend/portfolio.py`、`backend/routers/watchlist.py`、`frontend/src/components/ui/WinRateComparePanel.tsx`
>
> 级别：**large**（跨层 + 新增建议引擎 + 前端呈现 + 涉及交易信号输出）

## 1. 问题 / 目标

当前系统只有新仓入场建议（`position_advisor`），基于合成 win_rate 公式（`min(confidence*0.8+0.2, 0.95)`）而非真实回测胜率。持仓中的加仓/减仓/清仓建议完全缺失。自选股无建议输出。

**目标**：写一个统一建议引擎 `position_advisor_v2.py`，覆盖三个场景：
1. **推荐标的入场建议**：基于 90 天真实回测 win_rate 替代合成公式，增强现有推荐标的
2. **自选股建议**：查自选 code 当天 gene_score，有信号就基于战法回测给建议，无信号提示"无当日涨停信号"
3. **持仓加仓/减仓/清仓建议**：基于持仓当前浮动盈亏 + 对应战法回测胜率，输出 add/reduce/close/hold

## 2. 背景

- `position_advisor.PositionAdvisor.advise()`：只管新仓入场，输出 `suggested_pct / entry_price_range / stop_loss / take_profit`。win_rate 来自合成公式。
- `strategy_backtest.run_strategy_backtest(lookback_days)`：返回 8 战法 `win_rate / avg_return / sample_size`。90 天回填后（S040）sample_size 足够统计显著。
- `portfolio.get_portfolio()`：返回持仓列表（code / cost / 当前价 / 浮动盈亏 pnl / pnl_pct），行情源 `tencent_quote` 已接通。
- `watchlist_get()`：返回自选 code 列表。
- `recommendation_engine.get_today_recommendations()`：返回今日推荐标的（HIGH/MEDIUM 等级），含 gene_score / factor_breakdown。
- `strategy_optimizer.adjustments()`：已有策略级调整建议（reduce/maintain），但依赖 winrate.db（67 条实际交易记录），样本量不够。本 spec 不用它，直接走 strategy_backtest 回测胜率。
- gene_scores DB 有 code -> 命中战法的映射（`match_strategies` 在 `limitup_strategy.py`）。

## 3. 需求清单

- [ ] R1 新模块 `backend/strategies/position_advisor_v2.py`：统一建议引擎，三个入口方法
- [ ] R2 `advise_recommendations(limit)`: 读今日推荐标的 + `strategy_backtest` 回测胜率，输出入场建议（仓位 / 止损 / 止盈 / 建议理由），win_rate 用真实回测值替代合成公式
- [ ] R3 `advise_watchlist()`: 读自选股列表，逐个查当天 gene_scores，有信号 -> 基于战法回测胜率给入场建议，无信号 -> 标记"无当日涨停信号"
- [ ] R4 `advise_holdings()`: 读 portfolio 持仓列表，逐个查 gene_scores 命中战法 -> 查该战法 90 天回测 win_rate -> 结合当前浮动盈亏状态输出 add/reduce/close/hold 建议
- [ ] R5 新 API `GET /api/advisory/summary`: 返回三场景建议汇总（recommendations + watchlist + holdings）
- [ ] R6 前端新增"建议中心"页面或 Tab：展示三场景建议，每条建议标注 win_rate 来源（90 天回测 / 合成估算）、建议理由、风险提示

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/position_advisor_v2.py`（新） | R1/R2/R3/R4 统一建议引擎 |
| `backend/routers/advisory.py`（新） | R5 API 端点 |
| `frontend/src/pages/Advisory.tsx`（新）或嵌入现有页面 | R6 前端呈现 |
| `frontend/src/lib/api.ts` | R5 新增 `advisorySummary` API 调用 |

## 5. 设计方案

### D1 数据流

```
recommendation_engine.get_today_recommendations()  ──┐
watchlist_get()                                       ├──> position_advisor_v2 ──> advisory summary
portfolio.get_portfolio()                           ──┘        │
                                                              ├── strategy_backtest.run_strategy_backtest(90)  -> 8 战法 win_rate
                                                              ├── limitup_screener.load_gene_scores(date)      -> code -> 战法映射
                                                              └── tencent_quote                                  -> 持仓当前价
```

### D2 建议规则（持仓场景 R4）

持仓加仓/减仓/清仓判断逻辑：

| 条件 | 建议 |
|---|---|
| 浮动盈利 > 5% 且战法 win_rate >= 60% | **hold**（趋势好，持有） |
| 浮动盈利 > 5% 且战法 win_rate < 40% | **reduce**（锁定部分利润） |
| 浮动亏损 > 3% 且战法 win_rate >= 50% | **hold**（回测胜率支撑，不止损） |
| 浮动亏损 > 3% 且战法 win_rate < 40% | **close**（回测胜率差 + 亏损，止损） |
| 浮动亏损 > 止损线 | **close**（到达止损价无条件止损） |
| 浮动盈亏在 [-3%, 5%] 且 win_rate >= 50% | **hold**（信号不明，观察） |
| 浮动盈亏在 [-3%, 5%] 且 win_rate < 40% | **reduce**（信号偏弱，减仓降风险） |
| win_rate 在 40-50% 之间 | **hold**（胜率中等，观察为主） |

止损线 = `position_advisor` 给出的 `stop_loss` 价（如果持仓有对应入场建议记录）或成本价 × 0.97（默认 -3%）。

### D3 建议口吻合规

所有建议用教育研究式口吻——"历史统计特征显示该战法 90 天回测胜率 62%，当前浮动盈利 8%，建议持有"，不输出"买入/卖出"指令。前端挂"历史统计特征，市场有风险，不构成投资建议"。

### D4 win_rate 来源标注

每条建议标注 `win_rate_source: "backtest_90d"`（真实回测）或 `"synthetic"`（合成公式，战法无回测数据时 fallback）。透明可审计。

### D5 自选股无信号处理

自选 code 当天不在涨停池 -> gene_scores 查不到 -> 不走战法匹配 -> 输出 `{code, status: "no_signal", message: "该标的当日无涨停信号"}`。不强行给建议。

### D6 不改现有 position_advisor

`position_advisor`（v1）保持不动——它在推荐链路中被调用，改动风险高。v2 是新模块，新 API 端点，新前端页面。v1 验证 v2 建议更准后再考虑替换。

## 6. 验收标准

- [ ] A1 `GET /api/advisory/summary` 返回三场景建议 JSON
- [ ] A2 推荐标的建议 win_rate 标注 `backtest_90d`（非合成公式）
- [ ] A3 自选股无当天涨停信号时返回 `status: "no_signal"`
- [ ] A4 持仓建议正确匹配战法 + 输出 add/reduce/close/hold
- [ ] A5 持仓浮动亏损 > 止损线 -> 输出 close 建议
- [ ] A6 每条建议挂"历史统计特征，市场有风险"提示
- [ ] A7 `pytest -m "not live"` 全过（mock tencent_quote / strategy_backtest）
- [ ] A8 前端建议页面渲染三场景建议
- [ ] A9 建议理由包含 win_rate 数值和来源标注

## 7. 合规与工程底线自查

- [ ] 建议属教育研究式口吻，不输出"买入/卖出"指令（合规 §1.1）
- [ ] win_rate 来自客观回测统计，不臆造
- [ ] 持仓数据（portfolio.json）不上传、不进 git
- [ ] 前端挂"历史统计特征，市场有风险，不构成投资建议"
- [ ] win_rate_source 标注来源，透明可审计

## 8. 测试计划

- pytest -m "not live"：mock strategy_backtest 返回值 + mock tencent_quote + mock gene_scores，验证建议逻辑各分支
- 手动调 `GET /api/advisory/summary`：确认三场景输出
- 前端打开建议页面：确认渲染
- 边界测试：持仓无对应战法 / 自选无信号 / 推荐标的无回测数据

## 9. 风险与回滚

- **建议准确性**：B 方案与因子验证并行——建议基于未完全验证的回测胜率。win_rate_source 标注让用户知道建议依据的可信度。因子验证（S043）事后校验。
- **持仓不同步**：用户实际交易不一定同步到系统——advise_holdings 只能在已有持仓数据基础上工作，无持仓返回空列表。
- **回滚**：v2 是新模块 + 新端点 + 新页面，删除即回滚。v1 position_advisor 不受影响。
