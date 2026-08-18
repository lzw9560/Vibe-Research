# Spec: S083 — 工作流重构：选股池分层（漏斗接入 pre_market_workflow）

> 状态：草案
> 作者：Claude  日期：2026-08-18
> 关联：`CLAUDE.md` §1.1、`specs/S002-打板工作流重构/`（P1 候选池漏斗已实现）、`specs/S070-intraday采集管道/`（R7 派生）、`specs/S079-打板P2战法与仓位闸/`（仓位闸+龙虎榜）、`specs/S081-打板P2战法匹配/`（PRD 2 战法）、原 PRD `/Users/lizhiwei/Downloads/Quantitative_Limit_Up_Trading_System_Implementation_Guide.md`
>
> **起因**：用户提出"第一步选股池是所有战法的基础，第二步才进入工作流"——当前 `pre_market_workflow.run()` 用 `_build_candidate_pool`（只做基因得分门槛 1/8 项过滤），S002 候选池漏斗（R1→R2→R3 完整八项+多层可检视+阈值自适应）已实现但未接入。战法因子散落在 `match_strategies` 各 elif 分支各自取数，与漏斗 R2 已采集的活跃度/资金流重复。

---

## 1. 问题 / 目标

当前工作流的问题：
1. **选股池弱**：`_build_candidate_pool` 注释"八项标准过滤（简化版）"但实际只做了基因得分门槛（1/8 项），连板/换手/量比/成交额/振幅/龙虎榜/北向/催化剂 7 项全缺
2. **战法因子重复取数**：S081 PRD 2 战法的 `match_strategies` 各 elif 分支各自调 astock/tencent/kline 取数，S002 漏斗 R2 `activity.py` 已调 `astock.kline` 取 bars 算振幅但只用了 1 次，战法匹配又调 `kline_rebuild._get_kline_bars` 重新取 K线
3. **vol_ratio_1d 缺口**：S081 弱转强接力第 5 因子恒 None（snapshots 无 hs 字段），战法永远到不了 high 置信度
4. **两条链路割裂**：漏斗由 `candidate_funnel_precompute` scheduled task 独立产出快照，`pre_market_workflow` 内部用 `_build_candidate_pool` 另一套筛选，两者并行不互通

**目标**：把 S002 漏斗接入 `pre_market_workflow` 替换 `_build_candidate_pool`，让**选股池（漏斗 R1→R2→R3）成为所有战法的基础数据源**，战法匹配从漏斗输出的 `DiagnosisCard`（含 `IndicatorSet` + `GeneScore`）读因子，不重复取数。一句话：选股池→工作流两层架构，选股池一站式输出所有战法因子。

---

## 2. 背景

### 2.1 两套选股标准差异（grill 核实）

| 维度 | `_build_candidate_pool`（现状） | S002 漏斗 R1→R2→R3（已实现未接入） |
|---|---|---|
| 筛选规则 | 只做基因得分门槛（≥60 合格/≥75 强基因）1/8 项 | R1 宽源（涨停基因+连板梯队）→ R2 收敛（换手≥8%+北向过滤）→ R3 定稿（竞价异动+公告催化+概念联动）完整八项 |
| 输出 | `list[GeneScore]`（候选）+ `list[GeneScore]`（强候选）+ `filtered_out` dict | `FunnelResult{final_candidates: list[DiagnosisCard], layers: list[FunnelLayer], indicators: IndicatorSet 映射}` |
| 指标采集 | 无（只读 screener_result 的基因得分）| R2 采集换手/量比/成交额/振幅/主力净流/龙虎榜机构/北向；R3 采集竞价/公告/概念 |
| 分层可检视 | 无 | R1→R2→R3 每层输出输入数/输出数/被过滤原因 |
| 阈值自适应 | 无 | 自动/建议/手动三模式，按情绪温度自适应 |
| 实际过滤力度 | 极弱（只按基因得分，不淘汰冷股/无北向/无催化股）| 强（R2 剔除换手<8% 冷股 + R3 只保留有竞价/催化/联动的）|

### 2.2 关键事实（grill 核实）

- **漏斗 `sources/gene.py:34` 已调 `limitup_screener.get_screener_result` 取 GeneScore**，但只提取 `gene_score`/`high_gene`/`qualify` 三个字段存到 `genes` dict，**丢掉了 `zt_count_250d`/`factors`/`last_zt_dates`/`missing_factors`**。既有 9 战法需要这些字段
- **前端 PreMarketBriefing 已消费 `funnel_layers` + `final_candidates`**（`briefing.funnel_layers` + `briefing.final_candidates`），说明 S002 漏斗 layers/final_candidates 已通过 `routers/workflow.py` 透传到前端，但 `pre_market_workflow.run()` 内部用 `_build_candidate_pool` 另一套筛选，两者割裂
- **漏斗 `activity.py:32` 已调 `astock.kline` 取 bars 算 `amplitude_pct`**（line 87），但只算了振幅没算 `max_high_pct`/`shadow_length_pct`/`ma_5_status` —— S081 形态反包又调 `kline_rebuild._get_kline_bars` 重复取 K线

### 2.3 与既有 spec 关系

- **S002（P1 已实现）**：漏斗 `candidate_funnel/run_funnel` 已实现 + 验收。本 spec 接入它到 `pre_market_workflow`，**不改 S002 漏斗本身**（只扩展 `sources/gene.py` 存完整 GeneScore + `activity.py` 扩展算 4 字段）
- **S070（已合并 develop）**：R7 派生函数 `compute_derived_features` 供弱转强接力战法取 `broken_duration_min`/`max_drop_pct`/`last_lock_time`，本 spec 不改 S070
- **S079（已合并 develop）**：仓位闸 + 龙虎榜黑名单已在 `pre_market_workflow` 串两层，本 spec 不改 S079 后处理逻辑（只改选股池入口，S079 的 `_apply_p2_post_filters` 在选股池之后串）
- **S081（已合并 develop）**：PRD 2 战法 `match_strategies` elif 分支已有，本 spec 改其因子取数路径（从各自调 astock/kline 改为从 `DiagnosisCard.indicators` 读）
- **原 PRD 第五节"东财实操"**：纯信号生成（Q2 决议），人工执行 checklist，本 spec 不涉及执行层

---

## 3. 需求清单

### 3.1 漏斗接入 pre_market_workflow（Q1=A 整体替换）

- [ ] R1：`pre_market_workflow.run()` 删掉 `_build_candidate_pool` + `get_screener_result` 调用，改调 `candidate_funnel.run_funnel(stage, date, cfg, ctx)` 拿 `FunnelResult`
  - [ ] R1.1 `FunnelResult.final_candidates`（list[DiagnosisCard]）作为选股池
  - [ ] R1.2 `FunnelResult.layers`（list[FunnelLayer]）透传到 `PreMarketReport.funnel_layers`（前端已消费）
  - [ ] R1.3 `CandidatePool` dataclass 改为从 `FunnelResult` 构造（DiagnosisCard → GeneScore 映射，见 R4）
- [ ] R2：`_build_candidate_pool` 方法删除或改为 `_funnel_to_pool(funnel_result: FunnelResult) -> CandidatePool` 适配器

### 3.2 漏斗扩展存完整 GeneScore（Q5=A）

- [ ] R3：`candidate_funnel/sources/gene.py` 扩展 `genes` dict 存完整 `GeneScore` 对象
  - [ ] R3.1 当前 `genes[code] = {name, gene_score, high_gene, qualify}`，扩展为 `{name, gene_score, high_gene, qualify, gene_obj: GeneScore}`
  - [ ] R3.2 GeneScore 从 `screener_result.gene_scores` 取（`get_screener_result` 已调，不重复调）
- [ ] R4：`DiagnosisCard` 加 `gene_score: GeneScore | None = None` 字段
  - [ ] R4.1 漏斗 `funnel.py` 构建 `DiagnosisCard` 时从 `genes[code].gene_obj` 取 GeneScore 塞入
  - [ ] R4.2 `pre_market_workflow` 从 `DiagnosisCard.gene_score` 取 GeneScore（既有 9 战法用），不再单独调 `get_screener_result`

### 3.3 漏斗 activity.py 扩展算 4 字段（Q5 依赖，因子复用基础）

- [ ] R5：`candidate_funnel/sources/activity.py` 扩展算 4 个 K线派生字段（已取 bars 不重新取数）
  - [ ] R5.1 `max_high_pct = (bar.high / prev_close - 1) * 100`（当日最高涨幅）
  - [ ] R5.2 `shadow_length_pct = (bar.high / bar.close - 1) * 100`（上影线长度）
  - [ ] R5.3 `ma_5_status`：从最近 5 日 bars 算均线，比较 ma5 vs price 判定 "Upward"/"Downward"/"Flat"
  - [ ] R5.4 `prev_turnover_pct`：从前日 bar 算换手率（`vol*10000/float_shares`），前日 bar 取不到标 None
- [ ] R6：`IndicatorSet`（`candidate_funnel/models.py`）加 4 字段
  - [ ] R6.1 `max_high_pct: Optional[float] = None`
  - [ ] R6.2 `shadow_length_pct: Optional[float] = None`
  - [ ] R6.3 `ma_5_status: Optional[str] = None`
  - [ ] R6.4 `prev_turnover_pct: Optional[float] = None`

### 3.4 战法因子从漏斗 DiagnosisCard 读（Q3=C 双参数兼容）

- [ ] R7：`match_strategies` 加 `indicators: IndicatorSet | None = None` 参数（默认 None 向后兼容）
  - [ ] R7.1 既有 9 战法不依赖 indicators，传 None 行为不变
  - [ ] R7.2 PRD 2 战法从 indicators 读因子
- [ ] R8：`StrategyMatcher.match()` / `match_batch()` 加 `indicators: IndicatorSet | None = None` 参数透传
- [ ] R9：`pre_market_workflow` 战法匹配循环从 `DiagnosisCard` 取 GeneScore + IndicatorSet 传给 match()
  - [ ] R9.1 `gene = card.gene_score`（GeneScore，既有 9 战法用）
  - [ ] R9.2 `indicators = card.indicators`（IndicatorSet，PRD 2 战法用）
  - [ ] R9.3 `pool_item` 仍从涨停池补取（DiagnosisCard 不含涨停池原始 dict 的 lbc/hs/zdp/p，保留 C2 修复）
- [ ] R10：PRD 弱转强接力 elif 分支改从 indicators 读
  - [ ] R10.1 `vol_ratio_1d = indicators.turnover_pct / indicators.prev_turnover_pct`（两者都有且 prev>0 时算，否则 None）—— **解决 vol_ratio_1d 缺口**
  - [ ] R10.2 删掉 `vol_ratio_1d = None` 简化代码
  - [ ] R10.3 `hs` 从 `indicators.turnover_pct` 读（不从 pool_item.hs，统一口径）
  - [ ] R10.4 `broken_duration_min`/`max_drop_pct`/`last_lock_time` 仍从 S070 R7 派生（漏斗不含分时派生）
- [ ] R11：PRD 形态反包 elif 分支改从 indicators 读
  - [ ] R11.1 `max_high_pct`/`shadow_length_pct`/`ma_5_status` 从 indicators 读
  - [ ] R11.2 删掉 `kline_rebuild._get_kline_bars` 调用（漏斗 activity.py 已取 K线 bars 扩展算，不重复取）
  - [ ] R11.3 `close_pct` 仍从 pool_item.zdp 读（DiagnosisCard 不含 zdp）
  - [ ] R11.4 `volume_1d`/`volume_2d` 从 `indicators.amount_yi` + 前日对比（或保留 pool_item.fundamt）

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/pre_market_workflow.py`（修改） | 删 `_build_candidate_pool` + `get_screener_result`，改调 `run_funnel`；战法匹配循环从 DiagnosisCard 取 GeneScore + IndicatorSet 传 match() |
| `backend/candidate_funnel/sources/gene.py`（修改） | 扩展 `genes` dict 存完整 GeneScore 对象（`gene_obj` 字段） |
| `backend/candidate_funnel/models.py`（修改） | DiagnosisCard 加 `gene_score: GeneScore \| None` 字段；IndicatorSet 加 4 字段（max_high_pct/shadow_length_pct/ma_5_status/prev_turnover_pct） |
| `backend/candidate_funnel/sources/activity.py`（修改） | 已取 K线 bars，扩展算 4 字段（max_high_pct/shadow_length_pct/ma_5_status/prev_turnover_pct） |
| `backend/candidate_funnel/funnel.py`（修改） | 构建 DiagnosisCard 时从 genes[code].gene_obj 取 GeneScore 塞入 |
| `backend/strategies/strategy_matcher.py`（修改） | match()/match_batch() 加 indicators 参数透传 |
| `backend/limitup_strategy.py`（修改） | match_strategies 加 indicators 参数；PRD 2 战法 elif 从 indicators 读因子，删各自取数代码（kline_rebuild 调用 + vol_ratio None 简化） |
| `backend/tests/`（新增/修改） | 漏斗接入端到端 + IndicatorSet 新字段 + activity 扩展算 + 战法从 indicators 读 + 既有 9 战法不破坏 |

---

## 5. 设计方案

### 5.1 两层架构（选股池→工作流）

```
[选股池] S002 漏斗 run_funnel()
  R1 宽源（涨停基因+连板梯队）→ R2 收敛（活跃度+资金流）→ R3 定稿（竞价+催化+联动）
  输出：FunnelResult
    ├── final_candidates: list[DiagnosisCard]
    │     ├── gene_score: GeneScore（既有9战法用）
    │     ├── indicators: IndicatorSet（PRD2战法用，含max_high/shadow/ma5/prev_turnover/turnover/amount_yi）
    │     ├── activity: ActivityAssessment
    │     └── risk_flags: list[str]
    └── layers: list[FunnelLayer]（每层可检视，前端展示）
        ↓
[工作流] pre_market_workflow.run()
  1. 选股池 = run_funnel() 输出（替换 _build_candidate_pool）
  2. 战法匹配：match(gene=card.gene_score, indicators=card.indicators, pool_item=补取)
     ├── 既有9战法：从 gene 读（total_score/zt_count_250d/factors）
     └── PRD2战法：从 indicators 读（max_high/shadow/ma5/turnover/prev_turnover）
        + S070 R7 派生（broken_duration/max_drop/last_lock）
  3. 仓位建议：PositionAdvisor.advise_batch(weather_state)
  4. [S079] cap_by_market_phase + DragonTigerSeatFilter（既有，不改）
  5. 推送飞书/前端
```

### 5.2 备选方案为何不选

- **B 加层（保留 get_screener_result + 加 run_funnel）**：两套筛选并行，重复调 get_screener_result（漏斗内部已调一次）
- **C 并行（漏斗和 _build_candidate_pool 取交集）**：_build_candidate_pool 只做 1/8 过滤，和漏斗完整八项不等价，取交集无意义
- **Q3 选 A 彻底改 DiagnosisCard 输入**：既有 9 战法依赖 GeneScore.total_score/zt_count_250d/factors，IndicatorSet 不含这些，破坏面大
- **Q5 选 B 两套并存**：重复调 get_screener_result 违反"不做重复工作"
- **Q5 选 C 既有 9 战法改从 IndicatorSet 读**：破坏既有 9 战法 + 改 IndicatorSet 结构影响漏斗+诊断卡+前端

### 5.3 工程约束

- **不破坏既有 9 战法**：match_strategies 新参数 indicators 默认 None，既有 9 战法传 None 行为不变
- **不破坏 S079 后处理**：`_apply_p2_post_filters`（cap_by_market_phase + DragonTigerSeatFilter）在选股池之后串，不改
- **不破坏 S070 R7 派生**：弱转强接力仍从 `compute_derived_features(get_snapshots_by_code)` 取分时派生
- **em_get 防封底线**：漏斗 activity.py 已走 `astock.kline`（em_get 限流），扩展算字段不重新取数
- **数据缺失透明**：IndicatorSet 新字段缺失标 None，不臆造（与 S002 AC6 一致）

---

## 6. 验收标准

- [ ] AC1：`pre_market_workflow.run()` 调 `run_funnel()` 替换 `_build_candidate_pool`，选股池 = 漏斗输出 `FunnelResult.final_candidates`
- [ ] AC2：`DiagnosisCard` 含 `gene_score: GeneScore`（从漏斗 sources/gene.py 扩展存），pre_market_workflow 不再单独调 `get_screener_result`
- [ ] AC3：`IndicatorSet` 含 4 新字段（max_high_pct/shadow_length_pct/ma_5_status/prev_turnover_pct），漏斗 activity.py 扩展算（不重新取 K线）
- [ ] AC4：`match_strategies` 加 `indicators` 参数（默认 None 向后兼容），既有 9 战法传 None 不破坏
- [ ] AC5：PRD 弱转强接力 `vol_ratio_1d` 从 `indicators.turnover_pct / indicators.prev_turnover_pct` 算（不再是 None 缺口）
- [ ] AC6：PRD 形态反包 `max_high_pct`/`shadow_length_pct`/`ma_5_status` 从 `indicators` 读，不再调 `kline_rebuild._get_kline_bars`（消除重复取 K线）
- [ ] AC7：既有 9 战法回归通过（match_strategies 传/不传 indicators 命中一致）
- [ ] AC8：S079 后处理（cap_by_market_phase + DragonTigerSeatFilter）在选股池之后串，不破坏
- [ ] AC9：前端 PreMarketBriefing `funnel_layers` + `final_candidates` 展示不变（透传链路已有）
- [ ] AC10：所有研判/买卖时机/仓位参数挂轻量风险提醒（CLAUDE.md §1.1 弱合规，继承 S079 §2.3 豁免）

---

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1）；挂轻量风险提醒
- [ ] 判断可复现：涉及数据的跑 `financial_rigor.py` 验算 —— **实现阶段验证**
- [x] 不接券商不下单（AC7 工程底线）
- [x] em_get 防封：漏斗 activity.py 已走 astock.kline 限流，扩展算不重新取数
- [x] 不臆造：IndicatorSet 新字段缺失标 None
- [x] S002 参考价位隔离决议 + AC10 显式豁免（继承 S079 §2.3）

---

## 8. 测试计划

- **单元测试**（`pytest -m "not live"`）：
  - 漏斗接入端到端：mock run_funnel 返回 FunnelResult，验证 pre_market_workflow 用漏斗输出替代 _build_candidate_pool
  - DiagnosisCard.gene_score 填充：mock sources/gene.py 扩展存 GeneScore，验证 DiagnosisCard 含 gene_score
  - IndicatorSet 4 新字段：mock activity.py 扩展算，验证 max_high/shadow/ma5/prev_turnover 正确
  - PRD 2 战法从 indicators 读：mock indicators 含新字段，验证弱转强 vol_ratio_1d 不再 None + 形态反包不再调 kline_rebuild
  - 既有 9 战法回归：传/不传 indicators 命中一致
- **回归**：S070/S079/S081 全套测试不破坏
- **手动验收**：前后端跑起来，盘前简报页面 funnel_layers + 战法 Tab + P2RiskPanel 展示

---

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 漏斗接入破坏 pre_market_workflow 既有链路 | 盘前简报空/报错 | match_strategies indicators 默认 None 向后兼容；_build_candidate_pool 删除前先加 _funnel_to_pool 适配器灰度 |
| DiagnosisCard 加字段破坏序列化 | 前端类型/快照不兼容 | gene_score 默认 None，既有快照无字段降级 None |
| activity.py 扩展算 K线字段精度 | max_high/shadow 计算偏差 | 复用既有 bar.high/bar.close/prev_close（activity.py 已有），不重新取数 |
| 既有 9 战法依赖 GeneScore 字段漏存 | 既有战法不命中 | sources/gene.py 存完整 GeneScore 对象（不只存 gene_score 数字）|

**回滚**：
1. `_build_candidate_pool` 改为适配器不删除，可快速切回
2. match_strategies indicators 默认 None，删除参数即回退
3. DiagnosisCard.gene_score 默认 None，不影响既有序列化

---

## 10. 待定项

- T1：`pool_item` 补取是否改为从 DiagnosisCard 提取（DiagnosisCard 不含涨停池原始 dict 的 lbc/hs/zdp/p）—— 实现阶段核实能否从 DiagnosisCard.code + 涨停池映射，或保留 C2 修复的 fetch_zt_pool 补取
- T2：`volume_1d`/`volume_2d` 从 `indicators.amount_yi` 还是 `pool_item.fundamt` 取 —— 实现阶段核实口径一致性
- T3：`close_pct`（zdp）是否加入 IndicatorSet —— 当前从 pool_item.zdp 取，如加入 IndicatorSet 可消除 pool_item 依赖（但改 IndicatorSet 结构）
