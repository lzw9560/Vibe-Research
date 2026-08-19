# 技术方案 · S085 因子全量补全 + 游资画像

> 对应 spec.md（2026-08-19，基于全量因子审查 wur9khaus）
> 分阶段：A 修 bug → B 透传 backlog → C 游资画像 → D 接预警+防封

---

## 0. 依据与复用清单

| spec 要求 | 复用的现有能力 | 代码事实 |
|---|---|---|
| A1 seal_amount 接线 | pool_item.fund 已含（zt pool） | diagnosis.py build_indicator_set 缺一行 `ind.seal_amount = pool_item.get("fund")` |
| A2 dragon_tiger 补 seats | dragon_tiger_board 已返 seats（buy/sell TOP5） | mappers.dragon_tiger_from_dict L586 丢 seats；models/seat.py DragonTiger 无 seats 字段 |
| A3 K线派生盘前 T-1 | activity.py _fetch_activity_from_kline 已有 | 盘前走 tencent 当日路径恒 None，应强制 kline T-1 |
| A5 板块资金 em_get | market._sectors raw akshare | fund_flow industry_map 已用 zt pool hybk，板块资金源仍 raw |
| B1 market_context | board_ladder 经 market._emotion(date) 已采集 4 率 | 丢弃，只取 lianban_stocks；透传近乎免费 |
| B2 seat_detail | seat_engine + hot_money_seats 已实现 | 未接 DiagnosisCard（AC5b backlog） |
| B3 seal_delta | intraday_features.compute_seal_trajectory 已算 | derived_source 不透传 |
| C1 知名游资名单 | seat_engine 席位名已有 | 无知名游资字典 |
| C3 next_day_sell_rate | fetch_billboard_dates 交易日列表已有 | 用 1-3 自然日 offset，非真实交易日 |
| D1 竞价金额 | tencent 9:25 turnover/amount_wan + bidding_monitor + first_board_confirm.fetch_auction_data | auction.py 未走此路径 |
| D2 五档 | mootdx TDX client.bids(symbol) 免费 | mootdx_src.py 未暴露 bids；探针已验证 |
| D3 筹码 | akshare stock_cyq_em | IndicatorSet.chip_profit_ratio 预留未填 |
| D4 同花顺防封 | ths_limit_up_pool 已实现返 5 字段 | raw requests 无熔断 |

---

## 1. 目录结构

### 1.1 后端
```
backend/
├── candidate_funnel/
│   ├── diagnosis.py          # 【改】A1 seal_amount + B2 seat_detail + B3 seal_delta + B5 concept_count
│   ├── models.py              # 【改】B1 market_context + B2 seat_detail + B3 seal_delta + D1/D2 新字段
│   ├── funnel.py              # 【改】B1 market_context 透传 + A3/A4 K线派生盘前 T-1
│   └── sources/
│       ├── activity.py        # 【改】A3/A4 K线派生盘前 T-1 + B4 kline bars 扩 offset
│       ├── fund_flow.py       # 【改】A2 dragon_tiger 传 date + A5 板块资金 em_get + A6 date 参数
│       ├── derived_source.py  # 【改】B3 seal_delta 透传
│       └── auction.py         # 【改】D1 竞价金额（tencent 9:25）
├── data/mappers.py            # 【改】A2 dragon_tiger_from_dict 补 seats
├── data/sources/
│   ├── eastmoney.py           # 【改】A2 date 语义 + A5 板块资金 em_get + D4 同花顺 em_get
│   ├── mootdx_src.py          # 【改】D2 暴露 bids(symbol)
│   └── akshare_src.py         # 【改】D3 stock_cyq_em 筹码
├── models/seat.py             # 【改】A2 DragonTiger 补 seats + C4 持续性/一日游字段
├── seat_engine/               # 【改】C2 游资画像 + C4 字段沉淀
├── hot_money_seats.py         # 【改】C2 游资习惯 + C3 next_day_sell_rate 真实交易日
├── scheduled_tasks.py         # 【改】C2 游资画像预采集（16:30 后）
├── limitup_screener/models.py # 【改】A7 GeneScore date 戳
├── limitup_strategy.py        # 【改】C5 游资画像进战法因子
├── config/知名游资.json（新）  # C1 席位名字典
└── CLAUDE.md                  # 游资画像合规自查
```

### 1.2 前端
- DiagnosisCard.tsx + FunnelLayerCard.tsx：因子展示扩展（seat_detail/market_context/游资画像/竞价金额/五档/筹码）

---

## 2. 实现步骤（分阶段）

### 阶段 A：修已有 bug
- A1：diagnosis.py build_indicator_set 加 `ind.seal_amount = pool_item.get("fund")`
- A2：mappers.dragon_tiger_from_dict 补 seats（DragonTiger 模型加 seats 字段，复用 BillboardDetail）；fund_flow 调 dragon_tiger_board(c, date=yesterday)
- A3：activity.py 盘前强制走 kline T-1 路径（_is_historical_date 或强制 date-1）算 max_high/shadow/ma_5/prev_turnover + auction
- A4：prev_amount_yi 盘前走 kline T-1
- A5：板块资金 stock_fund_flow_industry 走 em_get 或显式标注 raw + 缓存
- A6：stock_fund_flow_120d 加 date 参数
- A7：GeneScore 加 per-score date 戳
- A8：northbound 标"停更"

### 阶段 B：透传 backlog
- B1：FunnelResult 加 market_context；funnel.py 调 _emotion(yesterday) 透传 4 率（board_ladder 已取但丢弃）
- B2：DiagnosisCard 加 seat_detail；diagnosis.py 塞入（seat_engine + hot_money_seats）
- B3：derived_source 透传 seal_delta；IndicatorSet 加字段
- B4：activity.py kline bars 扩 offset（250 for turnover_percentile）
- B5：concept_count = len(concepts)；announcement_type 聚合

### 阶段 C：游资画像 + 习惯
- C1：知名游资名单（config/知名游资.json，席位代码 + 名字）
- C2：游资画像（每个游资上榜习惯：持续性/一日游/胜率，基于历史龙虎榜 + 次日 K 线）
- C3：next_day_sell_rate 真实交易日匹配（fetch_billboard_dates）
- C4：持续性/一日游字段沉淀（seat_engine._stock_buy_sell_pairs → 模型字段 + 分数）
- C5：游资画像进选股池（DiagnosisCard 游资标识 + 习惯分数）+ 战法因子

### 阶段 D：接预警 + 防封
- D1：auction.py 走 tencent 9:25 或 bidding_monitor 取竞价金额；IndicatorSet.auction_amount
- D2：mootdx_src 暴露 bids(symbol)；IndicatorSet.bid/ask（5 档）
- D3：akshare stock_cyq_em 筹码；填充 chip_profit_ratio
- D4：同花顺 em_get 改造 或 保留降级 + 防封标注

---

## 3. 验收对齐

| spec AC | plan 步骤 | 关键验证 |
|---|---|---|
| AC1 seal_amount | A1 | 八项标准⑥ 非 missing |
| AC2 dragon_tiger seats | A2 | 席位明细进选股池 |
| AC3 K线派生盘前 T-1 | A3 | 盘前非 None |
| AC4 prev_amount_yi | A4 | 盘前取 T-1 |
| AC5 板块资金 em_get | A5 | em_get 防封 |
| AC6 market_context | B1 | FunnelResult 透传 |
| AC7 seat_detail | B2 | DiagnosisCard |
| AC8 seal_delta | B3 | 透传 |
| AC9 N日涨幅+换手分位 | B4 | kline bars 扩 |
| AC10 知名游资名单 | C1 | 席位字典 |
| AC11 游资画像+习惯 | C2/C4 | 持续性/一日游 |
| AC12 next_day_sell_rate | C3 | 真实交易日 |
| AC13 竞价金额 | D1 | tencent 9:25 |
| AC14 五档 | D2 | mootdx bids |
| AC15 筹码 | D3 | akshare stock_cyq_em |
| AC16 同花顺防封 | D4 | em_get 或降级 |
| AC17 GeneScore date + northbound | A7/A8 | 戳 + 标注 |

---

## 4. 工程约束
- em_get 防封：dragon_tiger/板块资金/同花顺走 em_get 或显式降级
- 不臆造：各因子缺失标 missing
- 向后兼容：dragon_tiger mapper 补 seats 不破坏 institution_net（新增字段）
- §44 降级参考：游资画像习惯需数据积累（回溯模块）
- 数据积累：C 游资画像需历史龙虎榜 + 次日 K 线（16:30 预采集 + 回填）

## 5. 风险与回滚
- A2 mapper 改破坏消费方 → 向后兼容（新增 seats 字段，institution_net 不变）
- C 游资画像数据不足 → 16:30 预采集 + 历史回填 + 回溯模块
- D2 mootdx bids 暴露 → 探针验证 + 不破坏 kline
- D4 同花顺 em_get 不可行 → 保留降级 + 防封标注
- C1 知名游资名单维护 → 手工 + 社区数据（后续）
