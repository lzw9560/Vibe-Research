# Spec: S108 — 新浪三表孤儿管道全链接线（底座补缺）

> 状态：已实现(2026-08-30)
> 作者：lzw9560  日期：2026-08-30
> 级别：large（整条孤儿管道上线 + 扩 model + 新调度器/merge 函数/端点）
> 分支：`feature/S108-sina-financials`（off develop，squash-merge）
> 关联：grill「坚实数据底座」第 3 层孤儿接线 / S106（cross_validate 范式可复用）

## 1. 问题 / 目标

新浪三表孤儿管道**整条断开**（3 Explore agent + 实测确认）：
- `fetch_raw`（lrb/fzb/llb 三表）→ 孤儿（仅 astock 死别名）
- `sina_financials_from_rows` mapper → 孤儿（零生产调用）
- `FinancialPeriod`（33 字段）→ 孤儿（仅 mapper 内部构造）
- `detect_anomalies`（5 信号排雷）→ 孤儿（funnel.py 连 import 都没）

单测齐但零生产调用 = 底座一整块躺着。quality 第 2/3/7 条因 ths 摘要缺 capex/利息/历史股本退化。

**目标**（批 B 重量全做）：
1. 新增三表合并调度器 `fetch_merged_periods`（调 fetch_raw×3 → merge raw → mapper 产完整 FinancialPeriod）
2. 新增 `merge_three_statements`（按 period 对齐合并 raw，FinancialPeriod frozen 喂前合并）
3. 接 `detect_anomalies`：funnel L4 finals（≤3 只）+ 按需端点
4. 扩 `FinancialPeriod.share_capital` + `_SINA_ALIASES` 加"实收资本(或股本)"（解锁指标7）
5. quality 第 2/3/7 条接新浪回退
6. **限定调用面**：anomaly 只 L4 finals + 按需端点，不进 L2 全量（请求风暴防线）

## 2. 背景

- `fetch_raw`（`sina_financial.py:74`）：单表 period rows，一次一表。`fetch_merged_periods` 调 3 次合并。
- `sina_financials_from_rows`（`mappers.py:475`）：report_type 仅文档，传哪表只填那部分字段（FinancialPeriod frozen）→ 合并须喂 mapper 前合并 raw。
- `FinancialPeriod`（`financials.py:29`）：33 字段，实测 fzb 有"实收资本(或股本)"（茅台 12.5 亿）但别名表没映射 → S108 加 share_capital。
- `detect_anomalies`（`anomaly.py:163`）：吃 `list[FinancialPeriod]`，5 信号各需 curr+prior 两期。
- `funnel.run_value_funnel`：L1→L2(quality)→L3→L4(finals top_n_l4=3)。L4 finals 是 anomaly 安全调用点（≤3 只，3 表×3 只=9 请求可控）。

## 3. 需求清单

- [x] R1 `sina_financial.fetch_merged_periods(code, num=8)` 调度器（调 fetch_raw×3 → merge → mapper）
- [x] R2 `mappers.merge_three_statements(lrb/fzb/llb_rows)` 按 period 对齐合并 raw
- [x] R3 `FinancialPeriod.share_capital` + `_SINA_ALIASES["share_capital"]=["实收资本(或股本)","实收资本","股本"]`
- [x] R4 `funnel.py` L4 finals 接 detect_anomalies（≤3 只，结果入 `ValueFunnelResult.l4_anomalies`）
- [x] R5 端点 `GET /api/value-funnel/{code}/anomaly`
- [x] R6 quality 第2条 FCF 接新浪 capex（真 FCF=OCF−capex）+ 第3条利息接新浪 financial_expense/total_profit
- [x] R7 quality 第7条股本膨胀用新浪 share_capital 序列
- [x] R8 限定调用面：anomaly 只 L4 finals + 按需端点（funnel L2 段不调 fetch_merged_periods，源码结构保证）
- [x] R9 删 astock.py:94 死别名 `sina_financial_report`

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/sina_financial.py` | 新增 `fetch_merged_periods`（单表失败降级空 rows） |
| `backend/data/mappers.py` | 新增 `merge_three_statements`；`_SINA_ALIASES` 加 share_capital |
| `backend/models/financials.py` | `FinancialPeriod` 加 `share_capital` |
| `backend/value_funnel/models.py` | `ValueFunnelResult` 加 `l4_anomalies: dict[str, AnomalyAssessment]` |
| `backend/value_funnel/funnel.py` | L4 finals 调 detect_anomalies（≤3 只，故障不阻断） |
| `backend/value_funnel/quality.py` | 第2/3/7 条加 code 参数 + 新浪回退（失败降级 ths） |
| `backend/routers/value_funnel.py` | 新增 `GET /api/value-funnel/{code}/anomaly` |
| `backend/astock.py` | 删死别名 `sina_financial_report` |
| `backend/value_funnel/tests/test_quality.py` | autouse fixture mock 新浪返空（保既有 ths 口径断言） |
| `backend/tests/test_s108_sina_financials.py` | 新增 13 用例 |

## 5. 设计方案

### 5.1 三表合并调度器（sina_financial.py）

`fetch_merged_periods(code, num=8)`：调 fetch_raw(lrb/fzb/llb) ×3 → `merge_three_statements` 按 period 对齐 → `sina_financials_from_rows` 产完整 FinancialPeriod。单表失败降级空 rows 不阻断。

### 5.2 merge_three_statements（mappers.py）

按"报告期"对齐三表 raw rows，同 period dict.update 合并（含_同比），倒序返回。period 不一致（lrb季报 vs fzb年报）保留独有期。

### 5.3 L4 finals + 端点（funnel.py + routers/value_funnel.py）

funnel L4 finals（≤3 只）调 `fetch_merged_periods` → `detect_anomalies`，结果入 `result.l4_anomalies[code]`。**不进 L2**（源码结构保证：L2 段不含 fetch_merged_periods 调用）。
端点 `/api/value-funnel/{code}/anomaly` 单只按需触发。

### 5.4 quality 第2/3/7 回退（quality.py）

第2条：新浪 OCF−capex 绝对额算真 FCF，失败降级 ths 每股代理。第3条：新浪 total_profit/financial_expense，失败降级 ths。第7条：新浪 share_capital 序列算膨胀率，失败降级 missing。

## 6. 验收标准

- [x] A1 `fetch_merged_periods("600519")` 返 5 期完整 FinancialPeriod（三表齐 + share_capital=12.5亿）
- [x] A2 `merge_three_statements` 按 period 对齐 + period 不一致保留 + 倒序
- [x] A3 `detect_anomalies(完整periods)` 返 5 信号（茅台实测触发 sig3 利润质量）
- [x] A4 `/api/value-funnel/600519/anomaly` 200 返 5 信号 + period_count=8
- [x] A5 funnel L4 finals 含 l4_anomalies（≤3 只触发）
- [x] A6 quality 第2条真 FCF（新浪 OCF−capex）+ 第3条新浪稳定利息 + 第7条股本膨胀可算
- [x] A7 L2 全量不调新浪（funnel L2 段源码不含 fetch_merged_periods，测试 grep 验证）
- [x] A8 新浪失败降级：fetch_merged_periods 单表失败→空 rows / 全失败→[] / quality 回退 ths

## 7. 合规与工程底线自查

- [x] 不臆造：新浪失败/数据不足标 inapplicable/missing，诚实缺失
- [x] §44 口径：anomaly 排雷信号非 winrate/r/verdict，不出结论只标异常
- [x] 私有数据隔离：无新增落盘
- [x] 请求风暴防线：anomaly 限 L4 finals(≤3) + 按需端点，L2 不调
- [x] em_get 防封：新浪 urllib 非 em_get

## 8. 测试计划

- **单测** 13 用例全 PASS：merge 3 + fetch_merged 3 + anomaly 2 + 端点 1 + quality 回退 3 + L2 防线 1
- **既有 quality 测试**：autouse fixture mock 新浪返空，保 ths 口径断言不破
- **真实冒烟**：fetch_merged_periods(600519) 5 期完整；anomaly 端点 200 + 5 信号（茅台触发 sig3）
- **全量 gate**：跑中

## 9. 风险与回滚

- **风险1**：新浪单表 12-25s，L4 finals 3 只×3 表=9 请求。**缓解**：限 L4 + 按需端点。
- **风险2**：period 跨表不一致。**缓解**：merge 按"报告期"严格匹配，独有期保留。
- **风险3**：quality 口径混合（ths 每股 vs 新浪绝对额）。**缓解**：第2/3/7 用绝对额，evidence 标数据源。
- **回滚**：删 fetch_merged_periods + merge + 端点 + funnel L4 anomaly 块 + quality 回退即退回孤儿态。

## 10. 冲突审查表

| 旧 spec R-item | 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S017 `sina_financials 孤儿` | fetch_raw/mapper 零调用 | fetch_merged_periods+端点激活 | **激活** | 整条管道上线 |
| S017 `detect_anomalies 孤儿` | 零调用 | funnel L4 + 端点调 | **激活** | 5 信号排雷上线 |
| S017 `FinancialPeriod 孤儿` | 仅 mapper 内部构造 | fetch_merged_periods 生产构造 | **激活** | 完整 FinancialPeriod 生产 |
| quality 第2/3/7 退化 | ths 缺 capex/利息/股本 | 新浪回退补 | **修复** | 真 FCF + 稳定利息 + 股本膨胀 |
| S106 `cross_validate` | 估值 PE/PB 仲裁 | 可复用 revenue/net_profit 仲裁 | 共存 | YAGNI 先不强接 |

## 11. 范围外明确处置（SDD 严格）

| 项 | 处置 | 理由 |
|---|---|---|
| revenue/net_profit cross_validate 仲裁 | **不做** | S106 范式可复用，但三表主消费 anomaly/quality 回退，仲裁非阻塞。YAGNI。 |
| 新浪三表 L2 全量预计算 | **不做** | 60 候选×3 表请求风暴，限 L4 finals + 按需端点。 |
| 前端 anomaly 面板 | **前端 spec** | 后端端点出口本 spec 完。 |
| 新浪源熔断器 | **暂不做** | 失败率待观测，先 try/except 降级。 |

## 12. 不在本 spec 范围

- revenue/net_profit 多源仲裁（S106 范式可复用，先不强接）
- 新浪源熔断器（待失败率数据）
- 前端 anomaly 面板渲染（前端 spec）
- 缓存治理全铺（datacenter/tencent，第 1 层后续）
