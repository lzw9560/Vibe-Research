# Tasks: S171 — 价值因子月度 §44v2 验证

> 状态：草案 | 日期：2026-09-08 | 关联：[spec.md](./spec.md)（822db17）+ [plan.md](./plan.md)

可执行 checklist。每条带依赖 + 验收点。按依赖序勾。

## T1 R3 event_materiality_floor 第 5 参数（先做，TDD）

- [ ] T1.1 `wire_verdict` 加 `event_materiality_floor` 参数（第 5，None 默认，条件透传 verify + 存 Recorder params）——依赖：无；验收：py_compile + 条件透传 None 不破 14 旧 harness
- [ ] T1.2a TDD `test_passes_event_materiality_floor`（wire_verdict 传 floor=0.001 → verify 收到 event_materiality_floor=0.001）——依赖 T1.1；验收：RED（TypeError unexpected）→ GREEN
- [ ] T1.2b TDD `test_stores_event_materiality_floor_for_reproduce`（floor 存 Recorder params，reproduce_verdict 重算用 harness 值非默认 0.003）——依赖 T1.1；验收：RED→GREEN + reproduce status 一致
- [ ] T1.2c 跑原 7 wire + 64 verifier 测试无回归——依赖 T1.2a/b；验收：全绿（R3 additive 向后兼容）
- [ ] T1.3 跑 `pytest tests/test_s44_wire.py`——验收：全绿

## T2 R1 Layer0.5 stock_basic 采集

- [ ] T2.1 `query_stock_basic` code 前缀过滤 A 股（sh.6/sz.000/sz.002/sz.30/sh.688/bj，非 type=1 参数 baostock 无）→ `stock_basic_type1.json`（ipoDate+outDate）——依赖：无；验收：退市股数 vs 已知~300+ 交叉验，漏标率统计
- [ ] T2.2 atomic write（tmp+os.replace）——验收：kill 测试不损坏 JSON

## T3 R1 Layer0 akshare pre-check（可选）

- [ ] T3.1 akshare `stock_value_em` 全股×2018-2026 PE/PB/PS → `stock_value_em_exploratory.json`（标 survivorship_biased=true）——依赖 T2.1；验收：cache 格式 + 限流稳
- [ ] T3.2 PIT 验证子步骤：抽 10-20 股对比 stock_value_em PE 跳变点 vs baostock pubDate（验 epsTTM 值跳变非 price 驱动）——依赖 T3.1+T5；验收：对齐→PIT-clean 通过，不对齐→Layer0 不可信跳过
- [ ] T3.3 决策规则：positive→baostock 全量；falsified→spot-check（抽 N 股含退市 baostock PIT 重建 PE 重算 spread，翻=偏差假阴性跑全 baostock，不翻=省）——依赖 T3.2；验收：2×2 分离 PIT vs survivorship

## T4 R1 Layer1 baostock kline 多年（两套 adjustflag）

- [ ] T4.1 `query_history_k_data_plus` 全股×2016-01-01..2026-09-03，adjustflag=2 前复权（return 用）+ adjustflag=3 不复权（PE 用，bug 1 fix）——依赖 T2.1；验收：两套 cache + per 50 股 re-login + 129 月覆盖
- [ ] T4.2 atomic write + per-batch-50 checkpoint sidecar——依赖 T4.1；验收：resume 跳过已完成股 + kill 不损坏

## T5 R1 Layer2 baostock profit_data 多年

- [ ] T5.1 `query_profit_data` 全股×2016-2026×4Q（pubDate+epsTTM+roeAvg+MBRevenue+totalShare）→ `profit_data_cache_multiyear.json`——依赖 T2.1；验收：44Q 覆盖 + pubDate PIT 锚点
- [ ] T5.2 atomic write + checkpoint——依赖 T5.1；验收：同 T4.2

## T6 R1 Layer3 PIT universe + 退市审计 + 停牌过滤

- [ ] T6.1 **PIT 第一步 gate**：抽查≥3 历史月末 `query_all_stock(D) ∩ stock_basic(outDate>D)` 须非空——依赖 T4+T5；验收：含即将退市股→PIT 确认，不含→fallback `ipoDate<=D AND (outDate>D OR outDate="")` 重建
- [ ] T6.2 type=1 交集过滤指数/债券/ETF（query_all_stock 返所有证券）——依赖 T6.1；验收：universe 仅 A 股股票
- [ ] T6.3 outDate='' 二义 sanity（last bar 远>6 月→疑似漏标退市不入 universe）+ akshare `stock_info_sh/sz_delist` 交叉验——依赖 T6.1；验收：漏标率统计
- [ ] T6.4 0 bars 退市股 coverage 审计（计入严格分母 0% 覆盖，>5% 标 unrecoverable bias 降级）——依赖 T6.1；验收：双数覆盖率（宽松+严格≥80%）报告
- [ ] T6.5 停牌股 stale close 过滤（kline(D) volume==0 或无 D 日 bar，从 universe+Q1/Q5 候选双重剔除，bug 9）——依赖 T4+T6.1；验收：停牌股不入 universe 统计

## T7 R1 Layer4 benchmark

- [ ] T7.1 `sh.000300`+`sh.000905` 2016-2026 日K pctChg → `benchmark_indices.json`——依赖 T2.1；验收：129 月覆盖 + 股息偏差 caveat 标注（pctChg 不含分红）

## T8 R2 harness 月度 rebalance + PIT earnings gate + quintile

- [ ] T8.1 月末最后交易日 `query_trade_dates` rebalance 日 D——依赖 T4；验收：非 calendar 月末
- [ ] T8.2a 改 `compute_pe` `<=` 为 `<`（pubDate < D 严格小于，bug 7——A 股盘后披露同日=lookahead ~25% 月）——依赖 T5；验收：PIT 断言每只 Q1/Q5 股 epsTTM quarter pubDate<D，记录 pubDate>=D 为 PIT violation
- [ ] T8.2b `get_pit_profit_row(code, D)` helper + `(pubDate, quarter_key)` 元组降序 sort tie-breaking（bug 8——compute_pe line 144 同 pubDate 取原 dict 顺序 Q4-dict-顺序错误，quarter_key parse (year, quarter_num) 非字符串）——依赖 T8.2a；验收：同 pubDate 时取最新 quarter（2026Q1 > 2025Q4）非 Q4-dict-顺序
- [ ] T8.3 不复权 close PE quintile 选股（bug 1，bottom+top quintile）——依赖 T4(adjustflag=3)+T8.2；验收：quintile 跨调整法（前复权 vs 不复权 vs basis-adjusted）stability 验证
- [ ] T8.4 compute_pe epsTTM>0 过滤排除率统计（>30% 标 low-coverage）——依赖 T8.2；验收：~32% 排除率报告

## T9 R2 co-PRIMARY ① Q1-Q5 spread wire

- [ ] T9.1 returns=[Q1_ret - Q5_ret per month]+dates=[month_ISO]，edge_type="event"——依赖 T8；验收：mean t-test + 不可直接交易 caveat（A 股 short 受限）
- [ ] T9.2 cost 预扣 `returns -= round_trip_cost × (turnover_Q1 + turnover_Q5)` 分腿实测（非 single×2）——依赖 T9.1；验收：双腿 turnover 异步>10% caveat

## T10 R2 co-PRIMARY ② Q1-excess-universe wire

- [ ] T10.1 survivors_by_month={月:Q1 returns}+universe_by_month={月:all_active returns}+dates=[month_ISO]，edge_type="selection"——依赖 T6+T8；验收：long-only 可实现 + dates 传（PurgedKFold 要求）
- [ ] T10.2 window_sanity={"path":{mean,winrate,base_rate}} R5 前置 sanity——依赖 T10.1；验收：value winrate≈base_rate→R5 触发 exploratory 预期

## T11 R2 AUXILIARY + SECONDARY wire

- [ ] T11.1 AUXILIARY selection-low_pe/high_pe（edge_type="selection"，survivors/universe+dates）——依赖 T8；验收：n_comparisons family
- [ ] T11.2 SECONDARY Q1-excess-HS300（edge_type="event"，size-confounded caveat + BH m=1 latent caveat 若扩 K）——依赖 T7+T8；验收：K=1 moot

## T12 R2 退市 -100% inject + sensitivity 两档

- [ ] T12.1 退市股最后 active 交易月→下月 return=-1.0，survivors/universe 一致（同月同值，bug 4）——依赖 T4+T6.4；验收：注入完整性 A-test（同月同值 -1.0）+ 0 bars 股 fallback outDate 锚定
- [ ] T12.2 sensitivity 两档 -0.5 vs -1.0 跑两遍——依赖 T12.1；验收：一致性 gate（status 一致→稳，不一致→降级 exploratory）+ lift 差值 flag

## T13 R2 wire_verdict 5 参数 + 三 gate

- [ ] T13.1 wire_verdict 传 window_sanity/walk_train=36/walk_test=12/step=12/event_materiality_floor=0.001——依赖 T1+T9+T10+T11；验收：5 参数全传 + 存 Recorder params
- [ ] T13.2a **互验 gate**（co-PRIMARY ①② status 一致：都 edge 或都无 edge 才 PASS，矛盾→降级 exploratory 标"双 PRIMARY 不一致"）——依赖 T13.1；验收：①② status 字符串比对（R5 skip 时 selection_lift=None 不崩，用 status 非 lift）
- [ ] T13.2b **sensitivity 一致性 gate**（退市 -0.5/-1.0 两档 status 一致→稳，不一致→降级 exploratory 标"依赖退市 return 假设"）——依赖 T12.2+T13.1；验收：两档 status 字符串全等 + lift 差值 |lift_-0.5 - lift_-1.0|>0.3 标敏感 flag
- [ ] T13.2c **严格覆盖率 gate**（退市覆盖率≥50% 才 robust，<50% 降级 exploratory，0 bars 股计入分母算 0% 覆盖，bug 4）——依赖 T6.4+T13.1；验收：严格覆盖率（ipoDate..outDate≥80% 占退市股 %）≥50% 才 PASS

## T14 dry-run + mini-wire 测试

- [ ] T14.1 `long_value_run.py --dry-run`：构建 survivors/universe 不跑 wire_verdict——依赖 T8-T13；验收：PIT gate + 退市注入完整性 + quintile 跨调整法 stability + 停牌过滤
- [ ] T14.2 mini-wire：5-10 月小样本跑 wire_verdict 全 5 参数（缩减 walk_train/walk_test=3/2 触发 OOS + PurgedKFold n_splits=2 ≥4 dates）→ Recorder.save → reproduce_verdict → status 一致——依赖 T13.1；验收：wiring 层 bug 在小样本暴露非 full run

## T15 验收 + 归档

- [ ] T15.1 A5 reproduce：每 verdict_id 重算 status 一致（含 event_materiality_floor 存了）——依赖 T13+T14；验收：status 一致
- [ ] T15.2 A6 pytest `-m "not live" --deselect 3 flaky` 全绿——依赖 T1；验收：R3 additive 无回归（92 pre-existing env 失败不算，R3 不引入新）
- [ ] T15.3 逐条对 spec §4 验收标准 A1-A7 核对——依赖 全部；验收：A1 cache 5 文件 + A2 verdict 落 Recorder + A3 三 gate + A4 sensitivity + A5 reproduce + A6 pytest + A7 向后兼容
- [ ] T15.4 归档：spec 顶部标已实现 + 日期——依赖 T15.3；验收：状态更新

## 依赖图

```
T1(R3 floor) ─┐
T2(stock_basic)─┼→T4(kline)─→T8(rebalance)─→T9(Q1Q5)─→T13(wire)─→T14(dry/mini)─→T15(验收)
              ┼→T5(profit)─→T8            ─→T10(Q1univ)─→T13
              ┼→T7(bench)─→T11(SECONDARY)─→T13
              └→T6(universe)─→T10
T3(Layer0 pre-check, 可选)─→T3.2(PIT 验)─→T3.3(spot-check)
```
