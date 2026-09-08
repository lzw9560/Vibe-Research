# Spec: S171 — 价值因子月度 §44v2 验证

> 状态：草案 | 日期：2026-09-08 | 分级：medium | 关联：S168/S169/S170/S159/multiline-strategy-direction

## 0. 问题/目标

S168 valuation_pe 在 SHORT 窗口（D+1→D+4 path，涨停股次日 3 天持有）测低/高 PE quintile，verdict 未 validated（winrate lift 1.031x，低高无差异=零信号）。value premium（价值溢价）是 LONG-horizon 现象——Fama-French HML 月度 rebalance + 长期持有。S168 测的是 SHORT 窗口 + 涨停股（momentum universe），S171 改测 LONG 窗口（月底 rebalance + 1 月持有）+ 全 A 股（value universe）。

**窗口+universe 双变更不可分离**：S168→S171 同时改了窗口（3 天→1 月）和 universe（涨停→全 A）。若 S171 发现 edge，无法归因于窗口变更还是 universe 变更。spec 承认此 confound，不声称"证否 S168 错窗口"。**S171 verdict 是全A+月度联合测试，不能解窗口或股票池单独贡献**（要 2×2 设计：涨停×全A × 3天×1月 = 4 组才能解，资源约束不做）。

**文献定位（诚实）**：Fama-French 1993（美国）value premium 月度/年度一致。但 Hu et al. 2019 "Fama-French in China" 发现 A 股 HML premium **"not definitive — 比 US 弱且不一致"**，regime-dependent（熊市 outperform 牛市 underperform）。spec 不预设 A 股 value 有 edge——可能 falsified/exploratory/underpowered。

**标题 caveat**：spec PRIMARY 测试是 1 月持有（月频 proxy），非 canonical 长线持有（数月-数年）。3m/6m/12m horizon 因 n<60 underpowered 无法出正式 verdict。1m verdict **不可外推**为"长线 value premium 有/无 edge"——从月频外推到年频是 §44v1 错窗口的镜像。因子选择是数据可得性驱动（PE 因 epsTTM 直接可得），非 A 股证据驱动——PE 是 pragmatic proxy 非 canonical B/M（Fama-French HML 用 book-to-market，baostock 无 BVPS 字段）。

**winrate vs mean（关键方法论）**：§44v2 verifier 的 selection verdict 用 `winrate_lift_avg` 驱动 status（verifier.py:283 实测确认），但 value premium 是 **mean-return 现象**（价值股赢的频率不一定更高，但平均收益更高 via 尾部）。`mean_lift_avg` 已计算（stats.py:231）但**从不用于 status 判定**。winrate lift 对 value 结构性 ≈1.0-1.2，永远到不了 2.0x robust_edge 门槛——会假阴性。spec 用**双 co-PRIMARY 互验**：① event Q1-Q5 long-short spread（mean t-test，canonical HML，beta 中性，无 winrate 偏——但跳 PurgedKFold/walk-forward OOS，因 event 不传 survivors/universe）；② Q1-excess-over-universe（selection edge_type，有 survivors/universe → 能跑 PurgedKFold+walk-forward OOS，补 ① 的 OOS 缺口——但自身 winrate 驱动有假阴性风险）。两 PRIMARY 互补：① 管 mean（无 winrate 偏），② 管 OOS。**互验 gate**：两都指向同方向才信，矛盾→降级 exploratory。**caveat**：① long-short 不可直接交易（A 股 short 受限），② long-only 才可实现。selection 降 AUXILIARY（标"winrate 对 value 结构性受限"）。**不改 verifier**（不改 selection_lift=winrate_lift_avg→mean_lift_avg）——YAGNI，用 edge_type 绕过。

## 1. 需求清单

- [ ] R1 数据采集 scan_long_value_cache.py：分 Layer0-4 background 跑（各自独立可 resume + checkpoint）
  - Layer0（exploratory pre-check，可选）：akshare stock_value_em 全股 × 2018-2026 daily PE/PB/PS（~2.5hr，**PIT-clean 待验**——spec 不预设 stock_value_em 历史 PE 是真 PIT，可能用 restated 值或报告期日算→lookahead）。**PIT 验证子步骤**：抽 10-20 股，对比 stock_value_em 历史 PE 跳变点 vs baostock profit pubDate——对齐（PE 在 pubDate 跳变）→ PIT-clean 通过；不对齐（报告期日跳变/用 restated）→ 有 lookahead，Layer0 不可信，跳过直接 Layer1-4。标 survivorship_biased=true（退市股返 None）。**决策规则**：Layer0 positive → baostock 全量确认；Layer0 falsified → **不直接省 baostock**，先 spot-check（抽 N 股含退市，baostock PIT 重建 PE 重算 Q1-Q5 spread，看跟 akshare 结论翻不翻——翻=偏差假阴性→跑全 baostock；不翻=falsified 可信→省 baostock）。双偏差（survivorship+lookahead）下 falsified 不可直接信
  - Layer1 kline 多年：baostock query_history_k_data_plus 全股 × **2016-01-01..2026-09-03**（~129 月，过 R6 60 门槛；2016+ 给 PIT earnings 4Q lookback），adjustflag=2 前复权，fields=date/open/high/low/close/volume/amount/turn/pctChg/isST。每 50 股 re-login（复用 first_board_premium_baseline.py RELOGIN_BATCH=50 + _bs_code），存 baostock_kline_cache_long.json（不覆盖现有 ~9 月 cache）
  - Layer2 profit_data 多年：baostock query_profit_data 全股 × **2016-2026 × 4Q（~44Q）**，取 pubDate+epsTTM+roeAvg+MBRevenue+totalShare，存 profit_data_cache_multiyear.json（PIT 锚点=pubDate；2016/2017 季度须取——2018-01 rebalance 的 PIT earnings 需 2017Q3 pubDate~2017-10）
  - Layer3 PIT universe + 退市：baostock query_all_stock(月末交易日) 重建每月 PIT active 集（主源），query_stock_basic **仅 type=1 过滤**（8945 全表含指数/债券非全股票——实测确认）取 outDate 元数据（补充）。退市股 kline 按 ipoDate..outDate 取活跃期。**退市 coverage 审计**：对全部 outDate!="" 的 type=1 退市股试取活跃期 kline，统计覆盖率（实测 sz.000033=364 bars 但 sz.000405=0 bars → 非全部覆盖）。存 historical_universe_monthly.json + stock_basic_type1.json
  - Layer4 benchmark：baostock sh.000300（HS300 大盘）+ sh.000905（ZZ500 中盘）2016-2026 日K（pctChg），存 benchmark_indices.json

- [ ] R2 factor 定义（PIT bottom-quintile，3 因子）：
  - F1 Low PE（earnings yield）：月底 rebalance 日 D = **月末最后交易日**（baostock query_trade_dates，非 calendar 月末——周末/假日无 close），PE = close / PIT_epsTTM（pubDate<=D 的最新 quarter epsTTM，复用 multifactor_combo_test.py:134 compute_pe 逻辑），取 bottom-quintile（最低 PE=最高 earnings yield）+ top-quintile（对照）。**显式标注**：compute_pe 过滤 `epsTTM > 0`（multifactor_combo_test.py:141 实测确认），排除亏损股（实测 ~32% 被排除），排除方向 = 高估 value premium（移除 value trap）。**universe_by_month 从 ALL PIT active 股构建**（含亏损股），非仅正盈利股——否则 universe 也被正向偏移。无 PIT earnings（pubDate<=D 无 epsTTM 或 epsTTM<=0）的股票从 PE ranking **排除**（标 "no PIT earnings, excluded from PE quintile"），统计排除率——若某月 >30% 排除则标该月 low-coverage
  - F2 PE+ROE composite（**非 Greenblatt**——EPS/price 受杠杆影响 ≠ EBIT/EV 资本结构中性）：earnings_yield_rank + roeAvg_rank 之和最高 quintile。**roeAvg 必须取自 F1 同一 pubDate<=D 最新 quarter 行**（用单 helper `get_pit_profit_row(code, D) → row` 派生所有因子，防止字段漂移到不同 quarter）。注意 baostock roeAvg 是 **YTD 累计**（非 TTM，实测茅台 Q1→Q4 roeAvg 递增）
  - F3 Low PB（高 B/M，deferred）：BVPS=epsTTM/roeAvg 派生 **对 3/4 季度失效**——roeAvg 是 YTD 累计、epsTTM 是 TTM，分母分子口径不匹配；亏损股双负产生正 BVPS（荒谬）。**仅 Q4 年报可用**（roeAvg 此时 = 全年 ROE）。deferred 到 Q4-only 验证

- [ ] R3 §44v2 wire（双 co-PRIMARY 互验 + AUXILIARY selection）：
  - **co-PRIMARY ①**：Q1-Q5 long-short spread，edge_type="event"，returns = [bottom_quintile_month_ret - top_quintile_month_ret per month]，dates = [month_ISO...]。canonical Fama-French HML 测试（beta 中性——同月双臂市场 beta 对消；mean-based——t-test 检验 mean spread > 0）。harness 预扣成本：returns[i] -= 2 × round_trip_cost × turnover_i（long+short 双腿）。**不可直接交易**（A 股 short 受限，融券难+贵）。n_comparisons=4（Family A）
  - **co-PRIMARY ②**：Q1 excess over universe mean，edge_type="selection"，survivors_by_month={月: Q1 returns}, universe_by_month={月: all_active returns}。long-only 可实现版，selection edge_type → 有 survivors/universe → 能跑 PurgedKFold + walk-forward OOS（补 co-PRIMARY ① 跳的 OOS 缺口）。window_sanity={"path":{mean, winrate, base_rate}}（R5 前置 sanity）。**自身 winrate 驱动有假阴性风险**（由 co-PRIMARY ① mean 兜底）。n_comparisons=4（Family A）
  - **互验 gate**：co-PRIMARY ①② 指向同一方向（都 edge 或都无 edge）才信；矛盾 → verdict 降级 exploratory 标"双 PRIMARY 不一致"
  - **AUXILIARY**：selection low_pe + high_pe quintile，edge_type="selection"，survivors_by_month/universe_by_month，window_sanity={"path": {mean, winrate, base_rate}}。R5 前置 sanity 检 path 窗口——value 的 winrate 可能 ≈ universe → R5 触发 exploratory（**预期行为非 bug**——selection winrate 对 value 结构性受限）。n_comparisons=4（Family A）
  - **SECONDARY-benchmark**：Q1 excess over HS300，edge_type="event"，returns = [Q1_month_ret - HS300_month_ret]。caveat: "size-confounded（HS300 大盘，value 偏中小盘）——非 pure value edge"。n_comparisons=1（Family B，独立）
  - Family A K=4（4 测试同族 Bonferroni/BH 校正）；Family B K=1；F2 PE+ROE K=1（Family C）。全 K ≤ cap 8
  - wire_verdict 新增 4 参数透传：window_sanity=None / walk_train=None / walk_test=None / step=None。None 时 verify() 用日频默认值（保 S168/S169/S170 向后兼容）。S171 harness 传 monthly 值：walk_train=36, walk_test=12, step=12。**不加 periods_per_year**（verify():169 声明但 body 从未使用——dead param，实测 grep 确认）
  - round_trip_cost=0.0025（0.25%：佣金 0.025%×2 + 印花 0.05% + 滑点 0.10% + 过户 0.001%×2；2023-08-28 前印花 0.10% 略高估）。**harness 预扣**成本（returns -= cost × turnover），非依赖 wire_verdict 的 round_trip_cost（后者仅设 event materiality floor = max(0.003, cost*0.5)=0.003，不从收益扣除——verifier.py:366 实测确认）

- [ ] R4 holding horizon 分层：
  - 1m：primary（月底 rebalance + 1 月持有，~100 非重叠月收益 IF 数据完整，实际 days_robust run 时确定）。月度是 R6 约束下的 valid proxy——FF HML 原始年度 rebalance 8.5yr 仅 8 数据点 underpowered，月度测同一信号但 ~100 数据点过 R6。**caveat**：月频 proxy 基于 US 文献（FF 1993 月度/年度一致），A 股无此证据；月度可能低估真 premium（高 cost drag）或加噪（短持 = 单信号噪声大）
  - 3m/6m/12m：secondary（重叠收益，仅报 mean/winrate 描述统计，标"overlapping returns, SE 未校正, exploratory only"，不跑 permutation/lift——verifier 假设 period 独立，重叠假显著）
  - walk-forward：step=12 修复后 ~2 OOS 窗口（60 月: range(0,13,12)=[0,12]），标 auxiliary 非 primary。**PurgedKFold**（5-fold OOS，verifier.py:312-323 自动跑）是更强的 OOS 测试——5 非重叠折 vs walk-forward 2 窗——标 primary OOS 信号

- [ ] R5 survivorship / lookahead / cost / regime 处理：
  - **survivorship = PARTIALLY correct**（非"survivorship-correct"）：baostock 覆盖 **多数** 退市股活跃期 kline（实测 sz.000033=364 bars, sh.600432=364 bars）但 **非全部**（sz.000405 返 0 bars，退市 337 个实测）。R1 Layer3 coverage 审计报**双数**：宽松覆盖率（返>0 bars 占退市股 %）+ 严格覆盖率（ipoDate..outDate 完整活跃期覆盖≥80% 占 %）。verdict caveat 用**严格覆盖率** gate：严格<50% 标"退市处理不可靠，verdict 降级 exploratory"。<100% 严格覆盖 → residual survivorship bias（value trap 缺失方向 = **高估 value premium**）。verdict 须标 "survivorship-partially-correct, bias direction: favors value"
  - **退市 return = anti-conservative for value**（非"保守"）：退市整理期实际损失 -50%~-90%（老三板 NEEQQ），用 outDate 前最后 close 仅计 -5%~-10% → 系统性高估 value premium。spec 采用 **-100% worst-case**（退市股**最后 active 交易月** return = -1.0，归零——不用 outDate 当月因停牌 volume=0 取不到）+ sensitivity 两档（-0.5 vs -1.0）。**一致性 gate**：两档 verdict 一致 → 结论不依赖退市假设（稳）；不一致 → verdict 降级 exploratory 标"依赖退市 return 假设，不可信为 robust"。退市 return 规则在 survivors_by_month 和 universe_by_month **一致**（同月同值，universe 不静默 drop 退市股——否则 base_rate winrate 被偏移）。**不剔除退市股**（退市是 value premium 承重样本，剔除=删 value trap 尾部损失=假性抬高 value=违反 §1.2 不臆造）
  - **lookahead**：PIT earnings gate 在 harness 层 enforce（pubDate<=D 的最新 quarter epsTTM，复用 compute_pe）。**restatement risk** caveat：baostock 可能存储 **restated**（修正后）epsTTM 但保留原始 pubDate——pubDate<=D 保证报告已公开，不保证值是 as-originally-reported。spec 加抽样验证步骤（5-10 stock-quarters 对比 as-reported vs baostock 值），偏差大则降级 verdict 为 exploratory
  - **cost**：round_trip_cost=0.0025，harness 预扣（returns -= cost × turnover）。**turnover 须实测**（首跑后统计月度 quintile 变化率），不可假设 50%——月度 quintile rebalance 是 **非低 turnover**（20-50%+ 月度换手），年 drag 可能 3% 非 1.5%（A 股 value premium 文献 3-5%/yr gross，3% drag 可能翻 verdict）。加 sensitivity：cost drag 1.5% vs 3% 看 verdict 是否翻转
  - **regime**：HS300 MA20 对 value 是 **错维度**（20 日价格趋势 ≠ 价值-成长 style regime，value premium regime 驱动因子是 value-growth spread，3-7 年周期）。spec 用 **value-growth spread**（月底 bottom vs top quintile PE ratio cross-section）作 regime 维度。per-regime n<60 → underpowered 不拆 verdict，仅存 descriptive metadata。**sample period caveat**：2018-2026 偏 growth-favorable（2019-2021 A 股成长/科技 rally），falsified verdict 是 period-specific 非全周期证否
  - **\*ST 两层分离**：验证层**保留** *ST/即将退市股（不剔，保"不剔除退市"一致性——*ST 是退市前奏，剔 *ST=删 value trap 尾部=美化 value=假 edge）。capture/执行层规避 *ST（实盘不买，涨跌停±5%+流动性差+退市风险）。caveat 标"验证含 *ST 尾部保守，capture 须 *ST filter；剔 *ST 美化 value，capture 剔后仍有 edge 才是真可交易 edge"
  - **月末资金面 confound**：entry 用月末最后交易日，A 股月底（季末/年末尤甚）资金面紧张可能系统性污染买入价。caveat 标"entry 时机含月末资金面 confound，verdict 是 period+entry-timing-specific"。不换月初（偏离 FF 月度基准）、不上 sensitivity 两套（YAGNI），若未来实测月末效应大再上

- [ ] R6 days_robust 评估：月度 2016-2026 = TARGET ~129 月 IF 全股 profit_data fetch 成功。**actual days_robust run 时确定**——若 2016-2017 覆盖稀疏（小盘股 profit_data 缺）或 fetch 中断 → 可能 <60 → underpowered，spec 明说"待数据积累"不外推，不强行出 robust/falsified。不假设过 R6。

## 2. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/scan_long_value_cache.py` | 新建：Layer0-4 数据采集（akshare pre-check / kline 多年 / profit 多年 / universe PIT+退市审计 / benchmark），background + checkpoint/resume |
| `backend/tools/long_value_run.py` | 新建：月度 rebalance + quintile 选股 + Q1-Q5 spread / Q1-excess-universe / selection survivors build + window_sanity + cost 预扣 + 退市 -100% + sensitivity + wire_verdict（event PRIMARY + selection AUXILIARY） |
| `backend/tools/_s44_wire.py` | 改：wire_verdict 加 4 参数透传（window_sanity/walk_train/walk_test/step），None=日频默认保向后兼容。**不加 periods_per_year**（verify():169 声明但 body 从未使用——dead param，传了无效果） |
| `backend/s44_verifier/verifier.py` | 改：verify() 加 step 参数（传给 walk_forward_oos line 300-302，当前缺→默认 _WALK_STEP_DEFAULT=20=日步长→月度 60 月仅 1 OOS 窗口 insufficient） |
| `specs/S171-长线价值/spec.md` | 本 spec |

## 3. 设计方案

**张力1 R6 月度门槛**：kline + profit_data 拉 2016+（TARGET ~129 月远超 R6 60）。baostock 实测 2018Q2 profit_data 可取。若 fetch 不全 → underpowered 诚实标，不外推。

**张力2 PIT earnings**：baostock profit_data 有 pubDate（PIT 锚点）+ epsTTM。harness 层 enforce pubDate<=D 最新 quarter。restatement risk caveat（baostock 可能存 restated 值）。akshare stock_value_em PIT-clean 已验但 survivorship-biased → Layer0 exploratory pre-check（快速初判）+ baostock 正式 verdict。

**张力3 survivorship**：baostock **部分**含退市股（多数有活跃期 kline，少数返 0 bars）→ PARTIALLY correct。coverage 审计统计覆盖率，<100% caveat residual bias（favors value）。退市 return = -100% worst-case + sensitivity。universe_by_month 退市处理与 survivors 一致。

**张力4 regime**：per-regime n<60 underpowered → single verdict + regime metadata（value-growth spread 维度，descriptive 非 verdict）。sample period growth-favorable caveat。

**张力5 winrate vs mean**（关键）：selection verdict 用 winrate_lift_avg 驱动 status（verifier.py:283 实测确认），对 value 结构性 ≈1.0-1.2（赢的频率不更高，但均值更高 via 尾部）→ 永远到不了 2.0x robust → 假阴性。spec 用**双 co-PRIMARY 互验**：① event Q1-Q5 spread（mean t-test，无 winrate 偏，canonical HML beta 中性——但跳 PurgedKFold/walk-forward OOS 因 event 不传 survivors/universe）；② Q1-excess-universe（selection edge_type，有 survivors/universe → 能跑 PurgedKFold+walk-forward OOS，补 ① 的 OOS 缺口，但自身 winrate 驱动有假阴性风险）。两 PRIMARY 互补：① 管 mean（无 winrate 偏），② 管 OOS。互验 gate：两都指向同方向才信，矛盾→降级 exploratory。**不改 verifier**（YAGNI，用 edge_type 绕 winrate）。**caveat**：① long-short 不可直接交易（A 股 short 受限），② long-only 才可实现。

**张力6 cost 扣除分离**：verifier round_trip_cost 仅设 event materiality floor（verifier.py:366 实测确认），不从收益扣除。harness 须自行预扣（returns -= cost × turnover）。S168 valuation_pe_lift.py:52 已有此模式（net = return_pct - COST）。

**张力7 S168 universe confound**：S168 测 PE 于涨停股（momentum universe），S171 测 PE 于全 A（value universe）——universe+窗口双变更不可分离。spec 承认 confound，不声称"S171 证否 S168 错窗口"。

**张力8 BVPS 派生失效**：F3 Low PB 的 BVPS=epsTTM/roeAvg 对 3/4 季度失效（roeAvg YTD 累计 vs epsTTM TTM，口径不匹配）。仅 Q4 年报可用。deferred。

**张力9 月度 autocorrelation**：月度 value portfolio 组合慢变（同股连续月在 bottom-quintile），跨月自相关违反 iid 假设——day_clustered t-test 的 se = day_std/sqrt(n_days) 假设月均值独立，自相关时 t 略偏高。selection permutation（月内 cross-sectional）不受影响。caveat 标注；PurgedKFold + walk-forward 补 OOS（仅对 co-PRIMARY ② selection 生效——co-PRIMARY ① event 不传 survivors/universe 跑不了 PurgedKFold，这是双 PRIMARY 互补设计的动机：① 管 mean 无 OOS，② 管 OOS 有 winrate 偏，互验）。Newey-West HAC SE deferred（caveat 标注）。

## 4. 验收标准

- [ ] A1 Layer0-4 采集完成 → 5 cache 文件在 .vibe-research/（.gitignore）：baostock_kline_cache_long / profit_data_cache_multiyear / stock_basic_type1+historical_universe_monthly / benchmark_indices / stock_value_em_exploratory（若跑 Layer0）。退市股 coverage 审计报告附覆盖率
- [ ] A2 long_value_run 出 verdict：Family A（K=4）= co-PRIMARY ① Q1-Q5 spread（event）+ co-PRIMARY ② Q1-excess-universe（selection）+ AUXILIARY selection-low_pe + selection-high_pe；Family B（K=1）= Q1-excess-HS300；Family C（K=1）= PE+ROE spread（若数据够）。全落 Recorder + lineage。**互验 gate**：co-PRIMARY ①② 一致才信
- [ ] A3 co-PRIMARY ① edge_type=="event"（Q1-Q5 spread）+ co-PRIMARY ② edge_type=="selection"（Q1-excess-universe）；AUXILIARY selection-low_pe/high_pe；days_robust ≥ 60 或诚实标 underpowered；**三 gate 全过才 robust**：互验 gate（①② 一致）+ sensitivity 一致性 gate（-0.5/-1.0 一致）+ 严格覆盖率 gate（≥50%）
- [ ] A4 退市股 -100% worst-case + sensitivity（-0.5 vs -1.0）跑两遍，**一致性 gate**：一致→稳，不一致→降级 exploratory 标"依赖退市 return 假设"
- [ ] A5 reproduce 验证 OK（reproduce_verdict 重算不崩，status 一致）
- [ ] A6 pytest -m "not live" --deselect newsradar --deselect s032 --deselect s040 全绿（无回归）
- [ ] A7 wire_verdict + verify 改动向后兼容（新参数 None=日频默认，S168 12 harness + S169/S170 旧调用不受影响）

## 5. 合规与工程底线自查

- [x] 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1）；验证管道非用户可见推荐，verdict 落 Recorder 诚实标
- [x] 判断可复现：§44v2 verifier = 复现机制（reproduce_verdict 重算）；baostock 真实 kline + profit_data，PIT earnings gate（pubDate<=D），退市 -100% + sensitivity，不假收益。financial_rigor.py 不适用（非市值/估值验算）
- [x] 涨停四池/连板股榜个股属公开榜单客观事实（本 spec 不涉及涨停四池）
- [x] 用户私有数据（cache 在 .vibe-research/ VR_DATA_DIR，.gitignore）未进 git、未上传
- [x] 新增东财端点走 em_get 限流：本 spec 用 baostock 非 em_get（无 IP 封禁风险，但须 re-login per 50 股防 timeout）。Layer0 akshare stock_value_em 走 akshare 内置限流（非裸 requests），标 deferred 若限流不稳

## 6. 测试计划

- pytest -m "not live" --deselect backend/tests/test_newsradar.py --deselect backend/tests/test_s032_refresh.py --deselect backend/tests/test_s040_backfill.py（离线快测，3 flaky 跳过）
- long_value_run.py --dry-run：只构建 survivors/universe 不跑 wire_verdict，验证 PIT earnings gate + 退市处理 + quintile 选股逻辑
- reproduce_verdict：对每个 verdict_id 重算，status 一致
- 退市 sensitivity：-50% vs -100% 两遍，verdict 一致或注明翻转

## 7. 风险与回滚

- 数据不到 5yr（profit_data 2016-2017 覆盖稀疏）→ underpowered，不可消除（诚实标，待数据积累）
- 退市 coverage <100% → residual survivorship bias（favors value），不可完全消除（caveat 标注，-100% worst-case 部分缓解）
- restatement risk → baostock 可能存 restated 值（抽样验证，偏差大降级 exploratory）
- 月度 autocorrelation → day_clustered t-test 假设独立，t 略偏高（caveat 标注，PurgedKFold 补充 OOS）
- sample period 2018-2026 growth-favorable → falsified 是 period-specific（不外推）
- 回滚：删 scan_long_value_cache.py + long_value_run.py + 还原 _s44_wire.py/verifier.py（新参数 None=日频默认，不改旧行为）

## 8. deferred

- F3 Low PB（BVPS=epsTTM/roeAvg YTD/TTM 口径不匹配，仅 Q4 年报可用）——先 Q4-only 验证派生值 vs akshare stock_value_em 实测 PB 偏差<5%，否则 deferred
- 多因子组合（value+momentum+quality composite）——YAGNI NOW，单因子先验
- 3m/6m/12m 非重叠 rebalance（季频/半年频）——n<60 underpowered，待数据积累
- turnover sensitivity（cost drag 1.5% vs 3%）——首跑后实测 turnover，加 sensitivity 跑
- baidu PIT 验证（D 日 baostock profit_data vs baidu PE 对比）——baostock 为主，baidu 备选
- 实盘 capture——robust_edge 才接（capture 层须 *ST filter 规避即将退市，见 R5 *ST 两层分离）
- 摘帽 event（S170 underpowered 待 60 天复验）是 value trap 反转形态（*ST 摘帽→基本面改善，"摘帽股反而涨得好"经验观察）——若 S170 复验 robust 可作 S171 value 的 event 补充（不同线路：event vs factor，S170 管 S171 不测）
- Newey-West HAC SE（替代 iid t-test 处理月度自相关）——caveat 标注，YAGNI NOW
- PE as A-share value proxy 的局限性（非 canonical B/M，数据可得性驱动非证据驱动）——F3 PB deferred 后 PE 是 pragmatic proxy
- query_all_stock 含即将退市股的验证（≥3 历史月末抽查含 outDate>D 股）——实现时验证，若不含则 fallback stock_basic outDate 重建