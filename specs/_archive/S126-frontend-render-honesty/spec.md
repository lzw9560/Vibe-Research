# Spec: S126 — S124 前端渲染诚实 + risk-dashboard 透 data_status（MEDIUM 批）

> 状态：已实现(2026-08-31)
> 作者：lzw9560  日期：2026-08-31
> 关联：S124 scan round 2（registry S124 节）~8 MEDIUM 之前端渲染 4 处 + risk-dashboard strip data_status；S123 R4（hit_rate=0 when total_signals=0）后端诚实化配套

## 1. 问题 / 目标

S124 scan 扫出前端渲染层 4-5 处 winrate/hit_rate=0 当 sample=0 渲染"0%胜率"非"数据缺失"（S123 R4 后端 `hit_rate = ... if total_signals else 0.0` 给 0.0，前端不查 sample 字段）+ risk-dashboard/risk_oneday_list 响应不透 data_status（degraded 风险数据当权威呈现）。本 spec 点修闭合 display 层 lie。

## 2. 背景

- S123 R4 `run_backtest_async` 设 `hit_rate = hit_count/total_signals if total_signals else 0.0`——total_signals=0（无信号）时落盘 0.0。前端不查 total_signals→渲染"0% 胜率/命中率"当真实 0%，实际是无数据。
- `formatRate`/`formatPercent`（lib/format.ts:15,24）只格式化，不辨 sample。
- risk.py:81-87（risk_dashboard risk_scores）+ 144-151（high_risk）响应 dict 不含 `data_status`——OneDayRisk.data_status（S111 R4 加）算完不到前端，degraded 风险当权威。

## 3. 需求清单

- [ ] R1 lib/format.ts 加 `formatRateOrMissing(rate, sampleCount)` + `formatHitRateOrMissing(hitRate, signalCount)`：sample=0→"数据缺失"，>0→formatRate/格式化（真 0% 保留）。
- [ ] R2 StatsMetrics.tsx:27 `formatRate(data.win_rate)`→`formatRateOrMissing(data.win_rate, data.total_trades)`。
- [ ] R3 StrategyPage.tsx:88 `bt ? (bt.win_rate*100).toFixed(1)% : "—"`→查 `bt.sample_size>0`，0→"数据缺失"。
- [ ] R4 Backtest.tsx:397 hit_rate→查 `result.total_signals>0`，0→"数据缺失"。
- [ ] R5 TrendChart.tsx:74-75（perDay win_rate）+ 102-104（hit_rate）chart data：sample/signal=0→null（chart 显 gap 非 0% 线）。
- [ ] R6 routers/risk.py:81-87 + 144-151 响应 dict 加 `"data_status": risk_data.data_status`。
- [ ] R7 测试钉死：formatRateOrMissing sample=0→"数据缺失"，>0→格式化；risk_dashboard 响应含 data_status。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/lib/format.ts` | R1 加 helpers |
| `frontend/src/components/winrate/StatsMetrics.tsx` | R2 |
| `frontend/src/pages/strategy/StrategyPage.tsx` | R3 |
| `frontend/src/pages/Backtest.tsx` | R4 |
| `frontend/src/components/charts/TrendChart.tsx` | R5 chart data null on sample=0 |
| `backend/routers/risk.py` | R6 透 data_status |
| `frontend/src/lib/api/types.ts` | BacktestSnapshotRow/WinRateStats 字段确认（total_signals/total_trades）+ RiskScoreRow data_status |
| 测试 | R7 |

## 5. 设计方案

sample=0→"数据缺失"（非 0%）是 S121 同语义（0 永不合法当 sample=0）；真 0%（sample>0 全 miss）保留 0%。chart data 用 null（gap）非"数据缺失"字串（ECharts null=断线）。risk.py 透 data_status 对齐 sentiment_weather.py:1249（S125 R3 emit 模式）。

## 6. 验收标准

- [ ] A1 sample=0 时 winrate/hit_rate 显"数据缺失"非"0%"
- [ ] A2 sample>0 真 0% 保留
- [ ] A3 risk_dashboard/risk_oneday_list 响应含 data_status
- [ ] A4 全量 pytest 0 回归 + tsc 我改文件 0 error

## 7. 合规与工程底线自查

- [x] 不臆造（sample=0 不显 0% 假数据）/ 可复现（纯代码+测试）/ 不涉个股/私有/em_get

## 8. 测试计划

`pytest -m "not live"` + R7 + tsc --noEmit。

## 9. 风险与回滚

风险：BacktestSnapshotRow/StrategyBacktestResult 类型缺 sample/total_signals 字段→tsc 抓→加字段。回滚：各文件独立 revert。
