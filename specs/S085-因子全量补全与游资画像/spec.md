# Spec: S085 — 因子全量补全 + 游资画像 + 接预警 + 防封

> 状态：草案（核实完成 2026-08-19，约四成前提已修正，见 [核实报告.md](./核实报告.md)）｜ 日期：2026-08-19
> 关联：S084（选股池解耦 reframe，已实现 R1-only）、全量因子审查（4 agent 审计 54 因子，wur9khaus）
> 起因：S084 reframe 后全量因子审查发现：(1) 已有 32 因子 5+ bug（seal_amount 接线缺/dragon_tiger mapper 丢 seats/K线派生盘前 None/prev_amount_yi/板块资金防封）；(2) backlog 22 因子 20/22 数据源真有但未透传（市场宽度 board_ladder 已取数丢弃/seat_detail 已实现/seal_delta 已算）；(3) 预警 5 因子 2 个误判（竞价金额 tencent 9:25 可取/五档 mootdx bids 可取，未接选股池）；(4) 知名游资名单 + 持续性/一日游习惯分析全缺（你最初要的游资画像 + 习惯）；(5) 同花顺 raw requests 触防封底线。本 spec 全量补全。

---

## 1. 问题 / 目标

**问题**（全量因子审查 wur9khaus 4 agent 结论）：
1. 已有因子 bug：seal_amount 接线缺（八项标准⑥恒 missing）/ dragon_tiger mapper 丢 seats（席位级因子 mapper 层丢失）/ K线派生+auction 盘前走 tencent 当日路径恒 None / prev_amount_yi 盘前 None / 板块资金 raw akshare 非 em_get / stock_fund_flow_120d 不接 date / northbound 停更恒 None / GeneScore 无 date 戳
2. backlog 未透传：市场宽度 board_ladder 已采集丢弃 / seat_detail 已实现未接 / seal_delta 已算未透传 / N日涨幅+换手分位 kline bars 只取 10 不足 / concept_count 可 O(1) 派生未做
3. 预警误判：竞价金额（tencent 9:25 + bidding_monitor 有，auction.py 未走）/ 五档（mootdx bids 有，门面未暴露）/ 筹码（akshare stock_cyq_em 可行未接）
4. 游资画像缺：无知名游资名单（赵老哥/章建平等）/ 无持续性/一日游习惯分析（seat_engine._stock_buy_sell_pairs 有代理未沉淀）/ next_day_sell_rate 用自然日 offset 非真实交易日
5. 同花顺防封：ths_limit_up_pool raw requests 无熔断

**目标**：因子全量补全（修 bug + 透传 backlog + 接预警）+ 游资画像（知名游资 + 习惯分析）+ 防封（板块资金 em_get + 同花顺 em_get/降级）。

---

## 2. 背景：全量因子审查（54 因子，wur9khaus 审计）

| 段 | 数量 | 状态 | 关键 |
|---|---|---|---|
| A 已有 | 15（9 组） | 7 组已实现，1 部分（seal_amount），1 盘前 None（K线派生/auction） | 4 bug：seal_amount 接线/dragon_tiger seats/K线派生盘前 None/northbound 停更 |
| B S084 补 | 17（6 组） | 全已实现 + 进选股池，reframe 后透传 | 5 问题：prev_amount_yi 盘前 None/板块资金 raw akshare/tencent 估值非 T-1/derived cron 17:00/GeneScore 无 date |
| C backlog | 22 | 20/22 数据源真有，多数逻辑已实现 | 市场宽度 board_ladder 丢弃/seat_detail 未接/seal_delta 未透传/同花顺 raw requests/N日涨幅 kline 不足 |
| D 预警 | 5 | 2 误判（实际可取），2 属实，1 有替代 | 竞价金额 tencent 9:25/五档 mootdx bids/筹码 akshare stock_cyq_em |

**审查核心结论**：数据源层全合规（em_get/tencent urllib/derived SQLite），无数据源硬阻断；多数因子数据已存在或逻辑已实现，落地=透传+取数深度+派生补全+防封改造+新功能。

---

## 3. 需求（分阶段）

### 阶段 A：修已有因子 bug
- [ ] A1：`seal_amount` 接线——`build_indicator_set` 加 `ind.seal_amount = pool_item.get("fund")`（pool_item 已含 fund，从未赋值致八项标准⑥恒 missing）
- [ ] A2：`dragon_tiger` mapper 补 seats——`dragon_tiger_from_dict` 扩 DragonTiger 模型承载 seats（买/卖 TOP5 席位 name/buy/sell/net）+ records date/reason/turnover + institution buy/sell 分项；统一 BillboardDetail 路径复用；fund_flow 调 dragon_tiger_board 传 date（与 funnel T-1 一致）
- [ ] A3：K线派生盘前强制 T-1——`max_high_pct/shadow_length_pct/ma_5_status/prev_turnover_pct` + `auction_open_pct` 盘前走 kline T-1 路径（不 tencent 当日路径恒 None）
- [ ] A4：`prev_amount_yi` 盘前取 kline T-1（当日路径不取 kline bars 致 None）
- [ ] A5：板块资金 em_get 防封——`stock_fund_flow_industry` 走 em_get/circuit_breaker 或显式标注 raw akshare + 缓存
- [ ] A6：`stock_fund_flow_120d` 加 date 参数（与 funnel date 一致，历史 replay 不误取最新）
- [ ] A7：GeneScore per-score date 戳（口径 stale 修正）
- [ ] A8：northbound 标"停更"（实质失效，诚实标注）

### 阶段 B：透传 backlog 免费
- [ ] B1：市场宽度 `market_context`——FunnelResult 加 market_context 字段，board_ladder 已采集的 4 率（seal/break/promotion/max_boards）透传（近乎免费，board_ladder 经 market._emotion(date) 已取但丢弃）
- [ ] B2：`seat_detail` 子对象——DiagnosisCard 加 seat_detail（seat_engine buy_one_ratio + hot_money_seats SeatRiskFactor 已实现，接入选股池）
- [ ] B3：`seal_delta` 透传——derived_source 透传 compute_seal_trajectory 的 seal_delta；IndicatorSet 加字段
- [ ] B4：N日涨幅 + 换手分位——activity.py kline bars 扩 offset（change_5d/10d/20d 需 11+/21+，turnover_percentile_250d 需 250）
- [ ] B5：`concept_count`/`announcement_type` 聚合字段（concepts 列表已在，O(1) 派生 count；announcement_type 聚合）

### 阶段 C：游资画像 + 习惯分析
- [ ] C1：知名游资名单——席位名字典（赵老哥/章建平/炒股养家/作手新一等），手工维护 + 可配（config 或 json）
- [ ] C2：游资画像——每个游资的上榜习惯（持续性/一日游/胜率），基于历史龙虎榜 + 次日 K 线
- [ ] C3：`next_day_sell_rate` 真实交易日匹配——fetch_billboard_dates 交易日列表做 buy_date→下一交易日映射（替换 1-3 自然日 offset）
- [ ] C4：持续性/一日游字段沉淀——seat_engine._stock_buy_sell_pairs 沉淀为模型字段 + 分数
- [ ] C5：游资画像进选股池（DiagnosisCard 游资标识 + 习惯分数）

### 阶段 D：接预警 + 防封
- [ ] D1：竞价金额——auction.py 走 tencent 9:25 turnover/amount_wan 或 bidding_monitor；IndicatorSet 加 auction_amount 字段
- [ ] D2：五档买卖盘——mootdx_src.py 暴露 `bids(symbol)`；IndicatorSet 加 bid/ask 字段（5 档买卖挂单）
- [ ] D3：筹码分布——akshare stock_cyq_em（获利比例/平均成本/集中度）；填充 IndicatorSet.chip_profit_ratio（预留字段）
- [ ] D4：同花顺防封——ths_limit_up_pool 走 em_get 改造 或 保留降级 + 防封标注（raw requests 不同域，需 em_get 适配或显式降级）

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `candidate_funnel/diagnosis.py` | A1 seal_amount 接线 + B2 seat_detail 塞入 + B3 seal_delta 透传 + B5 concept_count/announcement_type |
| `candidate_funnel/models.py` | B1 FunnelResult.market_context + B2 DiagnosisCard.seat_detail + B3 IndicatorSet.seal_delta + D1 auction_amount + D2 bid/ask |
| `candidate_funnel/funnel.py` | B1 market_context 透传（board_ladder 已取）+ A3/A4 K线派生盘前 T-1 |
| `candidate_funnel/sources/activity.py` | A3/A4 K线派生盘前 T-1 + B4 kline bars 扩 offset |
| `candidate_funnel/sources/fund_flow.py` | A2 dragon_tiger 传 date + A5 板块资金 em_get + A6 stock_fund_flow_120d date 参数 |
| `candidate_funnel/sources/derived_source.py` | B3 seal_delta 透传 |
| `candidate_funnel/sources/auction.py` | D1 竞价金额（tencent 9:25 / bidding_monitor） |
| `data/mappers.py` | A2 dragon_tiger_from_dict 补 seats + 统一 BillboardDetail |
| `data/sources/eastmoney.py` | A2 dragon_tiger_board date 语义 + A5 板块资金 em_get + D4 同花顺 em_get（或 data/sources/ths） |
| `data/sources/mootdx_src.py` | D2 暴露 bids(symbol) |
| `data/sources/akshare_src.py` | D3 stock_cyq_em 筹码 |
| `models/seat.py` | A2 DragonTiger 模型补 seats + C4 持续性/一日游字段 |
| `seat_engine/` | C2 游资画像 + C4 字段沉淀 |
| `hot_money_seats.py` | C2 游资习惯 + C3 next_day_sell_rate 真实交易日 |
| `scheduled_tasks.py` | C2 游资画像预采集任务（16:30 后）|
| `limitup_screener/models.py` | A7 GeneScore date 戳 |
| 知名游资名单（新） | C1 config/json 席位名字典 |
| `limitup_strategy.py` | C5 游资画像进战法因子 |
| `CLAUDE.md` | §44 降级已（S084），游资画像合规自查 |
| 前端 | 因子展示扩展（DiagnosisCard.tsx + FunnelLayerCard） |

---

## 5. 设计

### 5.1 分阶段实现（A 修 bug → B 透传 → C 游资画像 → D 接预警）
- A 紧急（已有因子 bug，修后选股池因子靠谱）
- B 近乎免费（board_ladder 已取数丢弃，透传即可）
- C 新功能（知名游资 + 习惯分析，需数据积累 + 名单）
- D 后续（接预警 + 防封）

### 5.2 防封底线
- dragon_tiger 走 em_get（datacenter，已有）
- 板块资金 stock_fund_flow_industry 走 em_get 或显式标注 raw akshare + 缓存
- 同花顺 ths_limit_up_pool 走 em_get 改造 或 保留降级 + 防封标注
- tencent_quote urllib（不封 IP）
- mootdx bids TDX 协议（免费，不封）
- akshare stock_cyq_em（东财筹码，走 akshare）

### 5.3 不臆造 + §44 降级参考
- 各因子缺失标 missing + 原因（不臆造）
- §44 降级为参考性建议（S084 reframe），游资画像习惯分析需数据积累（回溯模块）

---

## 6. 验收标准

- [ ] AC1：seal_amount 接线（八项标准⑥ 非 missing）
- [ ] AC2：dragon_tiger mapper 补 seats（席位明细进选股池）
- [ ] AC3：K线派生 + auction 盘前走 kline T-1（不 None）
- [ ] AC4：prev_amount_yi 盘前取 T-1
- [ ] AC5：板块资金 em_get 防封
- [ ] AC6：market_context 透传（FunnelResult）
- [ ] AC7：seat_detail 子对象（DiagnosisCard）
- [ ] AC8：seal_delta 透传
- [ ] AC9：N日涨幅 + 换手分位（kline bars 扩）
- [ ] AC10：知名游资名单（席位字典）
- [ ] AC11：游资画像 + 习惯（持续性/一日游）
- [ ] AC12：next_day_sell_rate 真实交易日
- [ ] AC13：竞价金额（tencent 9:25）
- [ ] AC14：五档买卖盘（mootdx bids）
- [ ] AC15：筹码分布（akshare stock_cyq_em）
- [ ] AC16：同花顺防封（em_get 或降级）
- [ ] AC17：GeneScore date 戳 + northbound 停更标注

---

## 7. 合规与工程底线自查
- [x] em_get 防封：dragon_tiger/板块资金/同花顺走 em_get 或显式降级
- [x] 不臆造：各因子缺失标 missing
- [x] §44 降级参考（S084）：游资画像习惯需数据积累
- [x] 私有数据隔离：游资名单 config/json（非私有）

## 8. 测试计划
- 单测：A1-A8 各因子修复 + B1-B5 透传 + C1-C5 游资画像 + D1-D4 接预警
- 回归：candidate_funnel + s070/s079/s081/s084 + scheduled_tasks + seat_engine/hot_money_seats
- 前端 tsc：因子展示扩展

## 9. 风险与回滚
- A2 dragon_tiger mapper 改可能破坏消费方（risk_models/first_board_filter/fund_flow）→ 向后兼容（新增字段，旧 institution_net 不变）
- C 游资画像需数据积累（16:30 预采集 + 历史回填）→ 回溯模块
- D2 mootdx bids 暴露可能影响 mootdx client → 探针验证
- D4 同花顺防封改造可能无 em_get 适配 → 保留降级

## 10. 待定项
- T1：知名游资名单维护机制（手工 vs 社区数据）
- T2：游资画像习惯分析的数据积累周期（60 天？§44 回溯）
- T3：同花顺 em_get 适配可行性（同花顺不同域，可能需独立防封）
