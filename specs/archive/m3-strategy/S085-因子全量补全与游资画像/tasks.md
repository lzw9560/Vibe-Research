# 任务拆分 · S085 因子全量补全 + 游资画像

> 对应 spec.md + plan.md（分阶段 A/B/C/D）
> 规则：每条完成即跑单测；em_get 防封；不臆造；向后兼容。
>
> **核实状态（2026-08-19，见 [核实报告.md](./核实报告.md)）**：🟢先做 A7/A8/A2a-c/B2/B1；🔴defer 承重组 A1/A3/A4/A5/A6/A2d/B3/B4/C1-C4/D3/D4；❌证伪 D1/D2；⚪YAGNI B5。

---

## 阶段 A · 修已有因子 bug

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| A1 | seal_amount 接线：build_indicator_set 加 `ind.seal_amount = pool_item.get("fund")` | diagnosis.py | 八项标准⑥ 非 missing；映射 AC1 |
| A2 | dragon_tiger mapper 补 seats：DragonTiger 模型加 seats 字段（复用 BillboardDetail）；dragon_tiger_from_dict 补 seats + records date/reason/turnover + institution buy/sell 分项；fund_flow 调 dragon_tiger_board(c, date=yesterday) | mappers.py + models/seat.py + fund_flow.py | 席位明细进选股池；向后兼容 institution_net；映射 AC2 |
| A3 | K线派生盘前强制 T-1：max_high/shadow/ma_5/prev_turnover + auction 盘前走 kline T-1（不 tencent 当日 None） | activity.py + funnel.py | 盘前非 None；映射 AC3 |
| A4 | prev_amount_yi 盘前取 kline T-1 | activity.py | 盘前取 T-1；映射 AC4 |
| A5 | 板块资金 em_get 防封：stock_fund_flow_industry 走 em_get 或显式标注 raw + 缓存 | fund_flow.py + eastmoney.py | em_get 防封；映射 AC5 |
| A6 | stock_fund_flow_120d 加 date 参数（与 funnel date 一致） | fund_flow.py + eastmoney.py | 历史 replay 不误取最新；映射 AC6 |
| A7 | GeneScore per-score date 戳 | limitup_screener/models.py | date 戳；映射 AC17 |
| A8 | northbound 标"停更"（实质失效诚实标注） | fund_flow.py | missing 标停更；映射 AC17 |
| A9 | 单测：A1-A8 各因子修复 | tests/test_s085_factor_fix.py | 全绿 |

## 阶段 B · 透传 backlog 免费

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| B1 | FunnelResult 加 market_context；funnel.py 透传 board_ladder 已采集的 4 率（market._emotion yesterday） | models.py + funnel.py | market_context 透传；映射 AC6 |
| B2 | DiagnosisCard 加 seat_detail 子对象；diagnosis.py 塞入（seat_engine buy_one_ratio + hot_money_seats SeatRiskFactor） | models.py + diagnosis.py | seat_detail 进选股池；映射 AC7 |
| B3 | derived_source 透传 seal_delta（compute_seal_trajectory）；IndicatorSet 加字段 | derived_source.py + models.py | seal_delta 透传；映射 AC8 |
| B4 | activity.py kline bars 扩 offset（250 for turnover_percentile_250d；11+/21+ for change_5d/10d/20d） | activity.py | N日涨幅+换手分位可取；映射 AC9 |
| B5 | concept_count = len(concepts)；announcement_type 聚合字段 | diagnosis.py | 派生字段；映射 AC9 |
| B6 | 单测：B1-B5 透传 | tests/test_s085_backlog.py | 全绿 |

## 阶段 C · 游资画像 + 习惯分析

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| C1 | 知名游资名单（config/知名游资.json，席位代码 + 名字：赵老哥/章建平/炒股养家/作手新一等） | config/知名游资.json（新） | 名单；映射 AC10 |
| C2 | 游资画像（每个游资上榜习惯：持续性/一日游/胜率，基于历史龙虎榜 + 次日 K 线） | seat_engine/ + hot_money_seats.py | 画像；映射 AC11 |
| C3 | next_day_sell_rate 真实交易日匹配（fetch_billboard_dates 交易日列表） | hot_money_seats.py | 真实交易日；映射 AC12 |
| C4 | 持续性/一日游字段沉淀（seat_engine._stock_buy_sell_pairs → 模型字段 + 分数） | models/seat.py + seat_engine/ | 字段沉淀；映射 AC11 |
| C5 | 游资画像进选股池（DiagnosisCard 游资标识 + 习惯分数）+ 战法因子 | diagnosis.py + models.py + limitup_strategy.py | 进选股池；映射 AC11 |
| C6 | scheduled_tasks 加游资画像预采集（16:30 后，历史龙虎榜 + 次日 K 线） | scheduled_tasks.py | 预采集；映射 AC11 |
| C7 | 单测：C1-C6 游资画像 | tests/test_s085_hot_money.py | 全绿 |

## 阶段 D · 接预警 + 防封

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| D1 | 竞价金额：auction.py 走 tencent 9:25 turnover/amount_wan 或 bidding_monitor；IndicatorSet.auction_amount | auction.py + models.py | 竞价金额；映射 AC13 |
| D2 | 五档买卖盘：mootdx_src 暴露 bids(symbol)；IndicatorSet.bid/ask | mootdx_src.py + models.py | 5 档；映射 AC14 |
| D3 | 筹码分布：akshare stock_cyq_em（获利比例/平均成本/集中度）；填充 chip_profit_ratio | akshare_src.py + diagnosis.py | 筹码；映射 AC15 |
| D4 | 同花顺防封：ths_limit_up_pool 走 em_get 改造 或 保留降级 + 防封标注 | data/sources/（ths 或 eastmoney） | em_get 或降级；映射 AC16 |
| D5 | 单测：D1-D4 接预警 | tests/test_s085_warning.py | 全绿 |

## 阶段 E · 回归 + 验收

| ID | 任务 | 验收方式 |
|---|---|---|
| E1 | pytest 全过（candidate_funnel + s070/s079/s081/s084/s085 + seat_engine/hot_money_seats + scheduled_tasks） | 全绿 |
| E2 | 前端 tsc（DiagnosisCard.tsx + FunnelLayerCard 因子展示扩展） | 全过 |
| E3 | AC1-AC17 逐条核对 | 全过 |
| E4 | 验收报告 | specs/S085.../验收报告.md |

---

## 依赖图

```
A1（seal_amount）→ A9（单测）
A2（dragon_tiger seats）→ A9
A3/A4（K线派生 T-1）→ A9
A5/A6（板块资金/date）→ A9
B1（market_context）→ B6
B2（seat_detail）→ B6
B3（seal_delta）→ B6
C1（名单）→ C2（画像）→ C5（进选股池）→ C7
C3/C4（习惯）→ C2
D1-D4（接预警+防封）→ D5
E1-E4（回归+验收）
```

- A（修 bug）最紧急，先做；A2 改 mapper 向后兼容。
- B（透传）近乎免费，A 后做；B1 market_context 最简（board_ladder 已取）。
- C（游资画像）新功能，需数据积累（C6 预采集 + 回溯）；C1 名单先。
- D（接预警+防封）独立，可并行。
- 关键路径：A2→B2→C2→C5。

## 执行规则
1. 一次一任务，完成跑单测。
2. em_get 防封（dragon_tiger/板块资金/同花顺）。
3. 向后兼容（mapper 补 seats 不破坏 institution_net）。
4. 不臆造（缺失标 missing）。
5. §44 降级参考（游资画像习惯需数据积累）。
6. commit 引用 S085 + 任务 ID。
