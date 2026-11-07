---
type: report
title: 真实数据同步报告
date: 2026-09-07
total: 21
success: 21
partial: 0
failed: 0
---

# 真实数据同步报告

**同步日期**：2026-09-07
**股票总数**：21
**完全成功**（四源齐）：21
**部分成功**（1-3 源）：0
**完全失败**（零源）：0

## 数据源

- `astock.financials(code)` → 财务摘要（同花顺财报）
- `astock.full_valuation(code)` → 完整估值（腾讯行情 + 一致预期 EPS）
- `astock.valuation_percentile(code)` → PE/PB 历史分位（百度股市通 近5年）
- `astock.tencent_quote([code])` → 实时行情（PE/PB/市值）

## 字段映射说明

- `forward_pe` ← `full_valuation.pe_26e`（2026 远期 PE）
- `consensus_eps` ← `full_valuation.eps_26e`（2026 一致预期 EPS 均值）
- `dividend_yield` ← astock 公开门面未暴露，统一标`获取失败`（诚实缺失，非崩溃）
- `market_cap` ← `tencent_quote.mcap_yi`（亿元）格式化为 `X.YY亿` 或 `X.YYT`

## 逐股结果

| 代码 | 财务 | 完整估值 | 估值分位 | 实时行情 | 失败原因 |
|---|---|---|---|---|---|
| 600519 | ✅ | ✅ | ✅ | ✅ | — |
| 000858 | ✅ | ✅ | ✅ | ✅ | — |
| 300750 | ✅ | ✅ | ✅ | ✅ | — |
| 688981 | ✅ | ✅ | ✅ | ✅ | — |
| 002594 | ✅ | ✅ | ✅ | ✅ | — |
| 002156 | ✅ | ✅ | ✅ | ✅ | — |
| 002185 | ✅ | ✅ | ✅ | ✅ | — |
| 002281 | ✅ | ✅ | ✅ | ✅ | — |
| 600522 | ✅ | ✅ | ✅ | ✅ | — |
| 600584 | ✅ | ✅ | ✅ | ✅ | — |
| 601899 | ✅ | ✅ | ✅ | ✅ | — |
| 003040 | ✅ | ✅ | ✅ | ✅ | — |
| 600869 | ✅ | ✅ | ✅ | ✅ | — |
| 002354 | ✅ | ✅ | ✅ | ✅ | — |
| 601086 | ✅ | ✅ | ✅ | ✅ | — |
| 600127 | ✅ | ✅ | ✅ | ✅ | — |
| 688836 | ✅ | ✅ | ✅ | ✅ | — |
| 300058 | ✅ | ✅ | ✅ | ✅ | — |
| 600611 | ✅ | ✅ | ✅ | ✅ | — |
| 605398 | ✅ | ✅ | ✅ | ✅ | — |
| 605580 | ✅ | ✅ | ✅ | ✅ | — |

## vault 更新明细

### 600519
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/600519-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/600519-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/600519.md`)：更新 4 个字段

### 000858
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/000858-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/000858-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/000858.md`)：更新 4 个字段

### 300750
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/300750-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/300750-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/300750.md`)：更新 4 个字段

### 688981
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/688981-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/688981-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/688981.md`)：更新 4 个字段

### 002594
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/002594-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/002594-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/002594.md`)：更新 4 个字段

### 002156
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/002156-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/002156-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/002156.md`)：更新 4 个字段

### 002185
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/002185-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/002185-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/002185.md`)：更新 4 个字段

### 002281
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/002281-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/002281-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/002281.md`)：更新 4 个字段

### 600522
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/600522-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/600522-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/600522.md`)：更新 4 个字段

### 600584
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/600584-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/600584-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/600584.md`)：更新 4 个字段

### 601899
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/601899-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/601899-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/601899.md`)：更新 4 个字段

### 003040
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/003040-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/003040-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/003040.md`)：更新 4 个字段

### 600869
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/600869-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/600869-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/600869.md`)：更新 4 个字段

### 002354
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/002354-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/002354-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/002354.md`)：更新 4 个字段

### 601086
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/601086-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/601086-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/601086.md`)：更新 4 个字段

### 600127
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/600127-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/600127-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/600127.md`)：更新 4 个字段

### 688836
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/688836-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/688836-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/688836.md`)：更新 4 个字段

### 300058
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/300058-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/300058-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/300058.md`)：更新 4 个字段

### 600611
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/600611-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/600611-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/600611.md`)：更新 4 个字段

### 605398
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/605398-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/605398-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/605398.md`)：更新 4 个字段

### 605580
- **metrics** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/metrics/605580-latest.md`)：更新 11 个字段
- **valuations** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/valuations/605580-latest.md`)：更新 12 个字段
- **stock** (`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks/605580.md`)：更新 4 个字段

## 处置建议

- 完全失败的股票（零源）：检查网络/代理，或该股票是否退市/停牌；可后续重跑本脚本单股补拉。
- `dividend_yield` 全部为`获取失败`：astock 公开门面未暴露股息率字段，需走 `astock.dividend_history` 自行计算或新增门面函数（S104 已有 PS/PCF 补全先例）。
- 部分失败的股票：对应源的数据源可能限流/熔断（em_get breaker），重跑通常可恢复。

> 报告由 `scripts/sync_real_data.py` 于 2026-09-07 自动生成。
