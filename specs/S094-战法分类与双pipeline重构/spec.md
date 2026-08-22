# Spec: S094 — 战法分类与双 pipeline 统一底座重构

> 状态：第一轮 Oracle 审查后大修（6 阻断 + 7 歧义吸收中）
> 作者：Claude 会话  日期：2026-08-23
> 级别：**large**（跨层 + 双 pipeline 统一底座 + score_candidates 分流 + confidence 统一 + kline 扩容 + 5 根因修复 + UI 重设计）
> 流程门：spec.md + plan + task；feature 分支 `feature/S094-战法分类与双pipeline重构`；完整 grill；playwright 验收
> 依赖：S093 已合并（M4 归档）；**前置硬门：gene_scores 错位修复（S094-P0，见 §0.7）已合并**
> Oracle 第一轮：ora-6 完成，6 阻断 + 7 歧义，逐项吸收中

## 0. 起因

S093 验收后 grill 8 轮 + spec 审查 31 issue + 5 维度深度摸清，发现核心问题：**非涨停 pipeline 有两套互不相连的实现**（FLOW A score_candidates 涨停 pipeline 误跑非涨停战法 + FLOW B run_non_limitup_funnel 独立端点未接主 pipeline），spec 没摸清既有代码导致重复造轮子。

**5 维度精确根因**（基于代码证据）：

1. **两条非涨停数据流断裂**（FLOW A vs FLOW B）：FLOW A（score_candidates 跑全 12 战法含 dragon_head 无条件命中 → 涨停股 factors 无相对强度/均线多头 → 全 0）；FLOW B（run_non_limitup_funnel PatternScan 独立端点，未接 briefing）。两流数据契约断：A 用 gene 涨停因子 + compute_strategy_score；B 用 PatternScan 形态 + compute_non_limitup_score（硬编码权重）。
2. **6 根因（RC1-RC6）**：RC1 baostock cache 无 ma5/ma10/ma20（check_ma_bullish 恒 False）；RC2 scan_patterns 不传 sector_bars（relative_strength 退化为绝对涨幅）；RC3 两套权重源（NON_LIMITUP_WEIGHTS 硬编码 vs strategy_weights.json）；RC4 StrategyContext 无 market_scan_ctx 字段；RC5 score_candidates L511 丢弃 dispatch_match 产的 confidence/signal_strength；RC6 输出 schema 不一致（score vs strategy_score + 无 name）。
3. **score_candidates 跑全 12 战法**：不加 funnel_type 过滤 → dragon_head（非涨停）对涨停股跑 → 0 分；既有调用（workflow.py L222 / scheduled_tasks.py L1605）不传 funnel_type。
4. **zt_real 定位错**：不在 market._emotion（L272 len(zt) 东财 push2ex），在 _sentiment（L76 akshare legu "真实涨停"）；_sentiment 历史日返 {}（P0-1）。
5. **板块轮动修错对象**：前端 ContextTab 用 /api/strategy/funnel/sector-rotation（sector_cycle），非 /api/sector/rotation（sector_divergence 已弃用）；"未取得"根因**非 aggregate_sectors industry 缺**（ora-6 实测每个历史日 industry 满值），而是端点 date 必填无默认值 + 前端未传 date → 端点返空（ora-6 B5 修正）。
6. **kline cache 无非涨停股**：1121 只全涨停股 + FIELDS 无 ma5/ma10/ma20。
7. **🔴 gene_scores 历史行系统性错位一天**（Oracle 独立复现，08-13 起每一天）：写入时刻在 T 日晚，用盘中口径的东财池值算了 T+1 的基因标 T+1——每天偏移一个交易日。已用 code 集合相等验证（gs(08-18)=106 == zh(08-17)=106，全等；gs(08-19)=79 == zh(08-18)=79，全等；以此类推）。**FLOW A 候选输入（workflow.py L182 load_gene_scores）、R12 confidence 复用、R18 aggregate_sectors、backtest_lite/forward_test 全部坐在这份错位数据上。** 今天的 is_trading_day 守卫只防非交易日，防不住"交易日拿前一天池"这种错位。**前置硬门：S094 的 S2/S4 合并前必须完成 gene_scores 写路径修复（S094-P0）+ 历史行重算**。

用户要坚实工程底座（不修补，重构架构），避免返工。

## 1. 问题 / 目标

1. **统一双 pipeline 底座**：FLOW A + FLOW B 收敛为单一事实源——统一 K线契约 + 统一因子层 + 统一权重源 + 统一输出契约 + 统一候选输入
2. **战法分类分流**：12 战法按 funnel_type（7 limitup + 5 market_scan）分流，各对对应标的跑（涨停战法不对非涨停标的跑，反之亦然）
3. **score_candidates 分流 + confidence 统一**：加 funnel_type 参数 + 候选预分流契约 + 复用 dispatch_match 产的 compute_confidence（不派生）
4. **5 根因修复**：zt_real 显示层 / 板块轮动对对象 / kline cache 扩容 / MA 自算 / dragon_head 条件化
5. **UI 重设计**：双 pipeline 上下分区 + 折叠 + 卡片流转 + UI bug 修

## 2. 背景（现状挂载点，基于摸清）

- **FLOW A**（涨停 pipeline，briefing 消费）：workflow.py L177-227 load_gene_scores → cand_input → score_candidates L222 → dispatch_match（全 12 战法）→ scored_candidates → briefing 响应 → 前端 ForwardTabSection/StrategyMatchMatrix
- **FLOW B**（非涨停 pipeline，独立端点）：routers/strategy.py L245 /api/strategy/non-limitup-funnel → sector_rotation（TOP 板块）→ load_industry_map → get_sector_stocks → bars=cache.get(code)（len≥20）→ run_non_limitup_funnel L279 → scan_patterns（sector_bars=None 退化）→ compute_non_limitup_score（NON_LIMITUP_WEIGHTS 硬编码）→ 前端 NonLimitupLane（c.score/c.name 失配）
- **既有模块可复用**：strategies/non_limitup_funnel.py（run_non_limitup_funnel/compute_non_limitup_score）+ pattern_scan.py（compute_relative_strength/check_ma_bullish/compute_consolidation/compute_volume_breakout/compute_ma5_proximity/scan_patterns）+ sector_cycle.py（sector_strength_rank/aggregate_sectors/sector_rotation）+ strategy_base.py（dispatch_match L216 compute_confidence）+ compute_strategy_score（weight_set 机制）
- **zt_real**：market.py _sentiment L76（akshare legu "真实涨停"），历史日返 {}；_emotion L272 zt_count=len(zt) 东财 push2ex；下游 limitup_sti/service.py L164/L176 + workflow _market_emotion_from_ctx（ctx 路径读 sti_timeline）
- **板块轮动前端**：ContextTab.tsx L31-39 用 /api/strategy/funnel/sector-rotation（sector_cycle），sector_divergence 已弃用
- **kline cache**：baostock_kline_cache.json 1121 只全涨停股，FIELDS 无 ma5/ma10/ma20，refresh_kline_cache.py 增量不扩容

## 3. 需求清单（9 点坚实底座）

### A. 统一 K线契约（修 RC1/RC2）
- [ ] R1 pattern_scan 自算 MA（_compute_ma(bars,n) 由 close 序列算 ma5/ma10/ma20），不依赖 cache 字段
- [ ] R2 run_non_limitup_funnel L242 传 sector_bars（板块等权平均日K），compute_relative_strength 真为相对值

### B. 统一因子层 + 权重源（修 RC3）
- [ ] R3 删 non_limitup_funnel.py L48 NON_LIMITUP_WEIGHTS 硬编码
- [ ] R4 compute_non_limitup_score 委托 compute_strategy_score(weight_set="non_limitup")（strategy_weights.json 已存），消灭两套权重源
- [ ] R5 PatternScan 升为 market_scan 唯一因子事实源，indicator_based PatternReversalStrategy 改读 PatternScan（不读 ctx.indicators）

### C. StrategyContext 扩展 + match 分流（修 RC4，R5/R6/R7）
- [ ] R6 StrategyContext L47 加可选 market_scan_ctx：{pattern: PatternScan, sector_rank: int, rel_strength_vs_sector: float}
- [ ] R7 score_candidates 加 funnel_type 参数：limitup 用 gene ctx 跑 7 涨停战法；market_scan 用 market_scan_ctx 跑 5 非涨停战法，二者不交叉
- [ ] R8 既有调用点传 funnel_type：workflow.py _collect（涨停候选 limitup + 非涨停候选 market_scan 两次调）+ scheduled_tasks.py L1605（limitup）+ pre_market_workflow
- [ ] R9 DragonHeadStrategy.match L180 删无条件放行，改读 market_scan_ctx.rel_strength_vs_sector + sector_rank（板块内排名≤3 才命中）——**ora-6 A3：dispatch_match 经共享，波及所有 match_strategies 消费方（pre_market_workflow L174、workflow.py L860、strategy_backtest L145/L236、prediction_ingest L99、position_advisor_v2 L196），这些上下文无 market_scan_ctx → dragon_head + 4 形态战法从"可能命中"变"永不命中"——涨停股场景本就不该命中这 5 个非涨停战法，方向大概率对，但 spec 须显式声明行为变化面而非默认**。另注意 **pre_market_workflow 不调 score_candidates**（走 StrategyMatcher），R8 里"pre_market_workflow 传 funnel_type"表述有误，删
- [ ] R10 3 K线形态战法（low_absorption/platform_breakout/pattern_reversal）match 改读 PatternScan（consolidation_days/ma5_proximity/volume_breakout）——**reverse_package 不在 R10**（ora-6 A6：reverse_package 注册在 market_scan 但 match 在 db_based.py 读炸板池，本质是涨停生态战法，保留 db-based 不改读 PatternScan；§4 受影响文件 db_based.py 补列）**

### D. 板块领涨子（R3 补）
- [ ] R11 新增 compute_sector_stock_rank(code, sector_stocks, bars_map)：板块内按 relative_strength 降序排名（个股内，非 sector_strength_rank 板块间）

### E. 统一输出契约（修 RC5/RC6，R8 confidence）
- [ ] R12 score_candidates 复用 dispatch_match 产的 compute_confidence（L511 不丢弃，从 signals 取 confidence/signal_strength 填 scored_candidates）
- [ ] R13 ~~run_non_limitup_funnel 输出对齐 scored_candidates schema~~ **（ora-6 A4：R27 把 run_non_limitup_funnel 拆成"只产候选不打分"后，独立端点 /api/strategy/non-limitup-funnel 的输出契约会断——前端 NonLimitupLane 消费它拿打分结果。R13 与 R27 互相矛盾。拍板：独立端点同步切换为"产候选 → score_candidates(market_scan)"，R13 改为对齐该新路径的输出 schema：加 name + confidence + signal_strength，字段名统一 strategy_score）**

### F. 候选输入统一（修 RC6）
- [ ] R14 FLOW B 候选扩为 {code,name,bars,sector,sector_rank,close}，与 FLOW A cand_input 对齐，score_candidates 单一入口服务两 funnel_type

### G. zt_real 显示层修（根因 4）
- [ ] R15 ~~前端读 briefing.market_emotion.zt_count 正确字段~~ **（ora-6 B2 阻断：market_emotion 无 zt_real 字段，zt_count 是东财池 len 非"真实涨停"，方案不可行——删）**
- [ ] R16 zt_real 持久化 + 显示层修（ora-6 A1 拍板：R16 变体）：
  - `market.py _emotion` 加 `zt_real` 字段（latest 日从 `_sentiment` 拉 akshare legu "真实涨停"；历史日返 None，不臆造）
  - `sti_timeline` schema 加 `zt_real` 列 + `_execute_sti_post_market`（scheduled_tasks L655-708）存 zt_real（latest 日算）
  - `_market_emotion_from_ctx` 读 `zt_real` 维度（历史日读 DB 持久化值，不依赖 akshare 历史源）
  - 前端 `briefing.market_emotion.zt_real` 显示真实涨停；`zt_count` 保留供内部（seal_rate/promotion/STI 内部一致性不动）
- [ ] R17 refresh 快照（pre-market/refresh 调 _collect 重算 market_emotion）

### H. 板块轮动修对对象（根因 5）
- [ ] R18 板块轮动根因=date=None 默认 localTodayStr（非交易日空，**非 industry 缺**——08-21 industry 54/54 有值端点返 10 板块），修：后端 /api/strategy/funnel/sector-rotation 端点 date=None 默认 last_trading_date_str（routers/strategy.py）+ 前端 ContextTab 传 triplet.today
- [ ] R19 ~~删 sector_divergence calculate_sector_rotation L207-209 prev_sectors.copy() TODO，接入前一交易日历史板块排名~~ **（ora-6 非阻断 #4：前端已弃用 sector_divergence（ContextTab L31 注释实锤），残留消费仅 api.ts L212 + test_s008_t13e + smoke_test_apis；R19 有 YAGNI 嫌疑——砍掉或写明谁消费。若保留，"接前一交易日历史板块排名"也无历史板块数据源（sector_divergence 用东财 industry_comparison 实时接口，历史无存），需先回答数据从哪来）**

### I. kline cache 扩容（根因 6）
- [ ] R20 baostock 全 A ~5500 刷新任务（非增量 list(cache.keys())，扩容到非涨停股）——**ora-6 非阻断 #1：全 A 代码可直接复用 `load_industry_map()`（5540 条已在产），不必调 baostock `query_stock_basic`（已式微）；扩容后 cache ~150MB，routers/strategy.py:267 每请求 json.loads 全量需配套模块级 memo 或迁 sqlite/parquet；"1-2h"改"预估 2-3h 实测为准"**
- [ ] ~~R21 MA 在消费侧算（R1 自算），不依赖 cache 字段~~ **（ora-6 非阻断 #3：与 R1 完全重复，合并到 R1，删）**

### J. UI 重设计
- [ ] R22 前瞻 Tab 双 pipeline 上下分区 + 折叠收缩（涨停 pipeline 主展开 / 非涨停+辅助折叠）+ region 级 vs 卡片级折叠层级
- [ ] R23 卡片按 pipeline 流转顺序（①涨停池②涨停战法③breakout 弱信号④交叉验证 / ⑤板块领涨⑥K线形态⑦非涨停战法）
- [ ] R24 StrategyMatchMatrix 涨停/非涨停分区（单组件内分区或两实例，②⑦ 分置两 region）
- [ ] R25 UI bug 修：板块轮动"更多信息"股票代码 2 次（SectorCyclePanel）/ 仓位摘要截断（Workflow.tsx advisory 内联 L357-426）/ P2 仓位闸显示（P2RiskPanel，补现象判据）/ 验证对 spec（VerificationCard，指明对齐哪条）/ 定稿失配（SelectionPipeline 定稿节点对齐 final_candidates）

### K. 双 pipeline 收敛数据流（第 10 问 a 定）
- [ ] R26 workflow.py `_collect` 调 `gather_non_limitup_candidates(date)`（抽自 routers/strategy.py 端点：sector_rotation→load_industry_map→get_sector_stocks→bars）产非涨停候选 → 喂 `run_non_limitup_funnel(candidates, weather, sector_rank_map)` 产 PatternScan factors → `score_candidates(candidates, funnel_type="market_scan")`（run_non_limitup_funnel 签名是消费候选不产候选不接 date，故抽 gather 函数）
- [ ] R27 `run_non_limitup_funnel` 拆"产候选"+"打分"：只产候选（PatternScan factors + sector_rank + close），删自打分 `compute_non_limitup_score` 调用（打分归 score_candidates 统一入口）+ **score_candidates market_scan 分支调 check_quality_standards + passes_hard_standards（硬剔除闸前移，不丢 S075 硬剔除底线）**
- [ ] R28 briefing 响应分区透传：涨停 scored_candidates（limitup）+ 非涨停 scored_candidates（market_scan），前端双 pipeline 分区消费

### L. 各 R 细节定稿（grill 收敛）
- R1 `_compute_ma(bars, n)` = SMA（close[-n:]/n），n=5/10/20，bars<20 返 None（诚实降级）；放 pattern_scan.py，PatternScan 自持 TA
- R2 `sector_bars` = 板块成分股等权平均日K（close/high/low/volume 简单平均），compute_relative_strength 真为相对值（个股5日涨幅-板块5日涨幅）——**ora-6 A5：成分股集合=板块全成分（有 bar 者参与），停牌/缺 bar 按日期对齐取交集，写进定稿**
- R5 PatternReversal 沿用"长上影洗盘修复"形态（上影线>=4%+未封涨停+放量1.2x+5日线向上）——**ora-6 B3：PatternScan 现有 7 字段无 shadow_length_pct，须先扩 compute_shadow_length_pct(bars) + compute_ma5_slope(bars) 两个新 compute_\*，不能假装从 PatternScan 取不存在的字段**；改读 PatternScan 不读 ctx.indicators；spec §3"突破昨日最高"作废；放量口径变更（现 indicator_based 是今量/昨量≥1.2，PatternScan 是今量/前5日均量）须显式声明并说明阈值沿用理由（按数据支撑优先，口径变阈值不能默认不变）
- R16 zt_real 持久化：sti_timeline schema 加 zt_real 列 + `_execute_sti_post_market`（scheduled_tasks L672-690）存 zt_real（latest 日算）+ `_market_emotion_from_ctx` 读 zt_real 维度（历史日读 DB，不依赖 akshare 历史源）
- R18 板块轮动根因修正（ora-6 B5 收敛三处矛盾）：根因**非 aggregate_sectors industry 缺**（ora-6 实测每个历史日 industry 都是满值，save_gene_scores L112 code_industry 兜底），真正根因是端点 `/api/strategy/funnel/sector-rotation` date 参数必填无默认值 + 前端未传 date → 端点返空。修法：后端端点 date 默认 `last_trading_date_str()`（routers/strategy.py 改），前端 ContextTab 传 `triplet.today`（非交易日=F=最近交易日）。叠加 B1 错位影响：历史日聚合的是前一天的池（错位修复后自动消解）
- R4 委托 compute_strategy_score 须保留 per-strategy volume_signal 语义（ora-6 B6）：现 `compute_volume_signal_score`（non_limitup_funnel.py L86-120）按战法分支（platform_breakout volume_breakout_ratio>2 / reverse_package 成交额>15亿 / low_absorption >5亿 / dragon_head >10亿），而 `compute_strategy_score`（registry L362-420）是"候选一份 factors × weight_set"——score_candidates 循环里同一候选对所有命中战法用**同一份 factors**（L514-522），per-(候选,战法) 的 volume_signal 无处安放。**修法**：在 R14/R26 候选生产中引入"每战法一份 factors"（或把 volume_signal 计算下沉到 match 层）——这是打分语义变更，须在 spec 里显式定义，不能"实现时定"
- R20 kline cache 扩容：baostock `query_stock_basic` 取全 A ~5500 代码 + 一次性扩容（后台 scheduled_tasks kline_refresh 扩容版，周末/盘后跑 1-2h）+ 后续增量维护（5500 append 新 bar）

### M. 实施细节定稿（grill 第 2 轮收敛）
- **12 战法归组表**（STRATEGIES_BY_FUNNEL_TYPE）：
  - limitup（7）：first_plate 首板挖掘 / consecutive_relay 连板接力 / break_reseal 炸板回封 / n_shape_counterattack N字反击 / end_of_day_sneak 尾盘偷袭 / weak_turn_strong 弱转强接力 / storm_reversal 暴风雨逆势涨停
  - market_scan（5）：dragon_head 龙头 / low_absorption 低吸 / reverse_package 反包 / platform_breakout 平台突破 / pattern_reversal 形态反包
- **funnel_type 默认**：必填（无默认 None=全跑）——None=全跑与 R7"不交叉"矛盾 + market_scan_ctx 缺失 crash。既有调用（workflow/scheduled_tasks L1605）传 limitup；market_scan 调用传 market_scan
- **模块归属**：新建 `market_scan.py`（因子层+形态子+领涨子 compute_sector_stock_rank）；`non_limitup_funnel.py` 保留 `run_non_limitup_funnel` 瘦身为"调 market_scan 产候选"入口（R27 拆分后只产候选不打分）。删 §4"或"字样
- **PatternScan 字段清单**（R10 + R5 对齐）：
  - pattern_reversal = shadow_length_pct / volume_breakout / ma_bullish（长上影洗盘修复）
  - low_absorption = ma5_proximity（均线回调）/ ma_bullish
  - reverse_package = 保留炸板池 db-based（open_count>=2，非 K线形态子——口径修正，单列 db 子）
  - platform_breakout = consolidation_days / volume_breakout（突破平台）
- **性能预算**（market_scan pipeline）：top N 板块上限（如 10）+ 每板块成分股上限 ≤50 + scan_patterns 超时熔断 + 候选 cap ≤30 喂 score_candidates（5500 股全扫分钟级超时，故限定 top 板块成分股）

## 4. 受影响文件

### 后端
| 文件 | 改动 |
|---|---|
| `strategies/pattern_scan.py` | R1 自算 MA + R2 传 sector_bars + R5 因子事实源 |
| `strategies/non_limitup_funnel.py` | R3 删硬编码权重 + R4 委托 compute_strategy_score + R14 候选扩字段 |
| `strategies/strategy_base.py` | R6 StrategyContext 加 market_scan_ctx |
| `strategies/strategy_funnel_registry.py` | R7 score_candidates 加 funnel_type + R12 复用 confidence + R13 输出对齐 |
| `strategies/impl/gene_based.py` | R9 DragonHead 条件化 + ~~R10 4 战法 match 改读 PatternScan~~（R10 改 3 战法，reverse_package 不在，ora-6 A6） |
| `strategies/impl/db_based.py` | R10 reverse_package 保留 db-based 不改读 PatternScan（ora-6 A6 补列，§4 漏列修复） |
| `strategies/impl/indicator_based.py` | R5 PatternReversal 改读 PatternScan |
| `strategies/sector_cycle.py` | R11 compute_sector_stock_rank + R18 端点 date 默认值修复（非 aggregate_sectors industry 修，ora-6 B5） |
| `strategies/non_limitup_funnel.py` 或新建 `market_scan.py` | R11 板块领涨子（复用既有函数，非重写） |
| `routers/workflow.py` | R8 传 funnel_type + 双 pipeline 响应 |
| `routers/strategy.py` | /api/strategy/non-limitup-funnel 对齐新 schema |
| `scheduled_tasks.py` | R8 L1605 传 funnel_type |
| `market.py` | R16 _emotion 加 zt_real 字段（可选） |
| `sector_divergence.py` | R19 删 prev_sectors TODO |
| `tools/refresh_kline_cache.py` | R20 扩容全 A |

### 前端
| 文件 | 改动 |
|---|---|
| `Workflow.tsx` | R22 双 pipeline 分区+折叠 + R23 卡片流转 + 仓位摘要内联修 |
| `StrategyMatchMatrix.tsx` | R24 涨停/非涨停分区 |
| `SectorCyclePanel.tsx` | R25 代码 2 次修 |
| `P2RiskPanel.tsx` | R25 P2 显示 |
| `VerificationCardBlock.tsx` | R25 验证对 spec |
| `NonLimitupPlaceholder.tsx` | R13 对齐新 schema（c.score→c.strategy_score） |
| `components/pipeline/SelectionPipeline.tsx` | R25 定稿失配 |

## 5. 验收标准

- [ ] AC1 战法分类分流正确（7 limitup + 5 market_scan，各对对应标的跑，dragon_head 不对涨停股跑——条件化 match）
- [ ] AC2 双 pipeline 统一底座（**ora-6 A7：= AC3+AC6+AC7+AC8 合称，无独立可测判据，降级为合称标注**）
- [ ] AC3 score_candidates funnel_type 分流 + confidence 复用（不再全 None/0，从 dispatch_match 取）
- [ ] AC4 zt_real 显示层修（market_emotion 加 zt_real 字段 + sti_timeline 持久化 + 历史日读 DB 值，不破坏 _emotion 内部 zt_count）
- [ ] AC5 板块轮动不再"未取得"（sector_cycle 端点 date 默认 last_trading_date_str + 前端传 triplet.today；非 aggregate_sectors industry 缺——ora-6 B5 实测 industry 54/54 满值）
- [ ] AC6 kline cache 扩容非涨停股 + MA 消费侧算
- [ ] AC7 pattern_scan MA 自算（check_ma_bullish 不恒 False）+ relative_strength 相对值（传 sector_bars）
- [ ] AC8 UI 双 pipeline 分区+折叠+卡片流转
- [ ] AC9 UI bug 修（代码2次/摘要/P2/验证/定稿失配）
- [ ] AC10 离线全测绿（pytest + vitest + tsc + vite build）
- [ ] AC11 playwright e2e

## 6. 设计取舍

1. **统一底座非接入修补**——FLOW A+B 收敛单一事实源（用户要求坚实底座，不返工修补）
2. **复用既有函数**（pattern_scan compute_* / sector_cycle / compute_strategy_score），不重写算法
3. **PatternScan 升 market_scan 唯一因子源**——消灭 indicator_based 第三条算路
4. **confidence 复用 dispatch_match**（不派生 strategy_score/100，保留 per-strategy 语义）
5. **zt_real 显示层修**（不改 _emotion 破坏内部一致性）或加字段保留 zt_count
6. **kline cache 扩容 + MA 消费侧算**（不依赖 cache 字段）
7. **UI 上下分区+折叠**（涨停主/非涨停次）

## 7. 合规自查

- [x] 不臆造：score_candidates 分流 + match 条件化，数据缺标 None 不命中；板块轮动 rotation_speed 不造假值（R19 接前日历史）
- [x] 私有数据 .vibe-research/ 不进 git
- [x] em_get 防封：kline 用 baostock（非东财不被限流）；板块用 sector/industry（既有防封）
- [x] 历史统计特征标注

## 8. 已知盲点（基于摸清已收敛大部分）

1. ~~market_scan 新建工作量~~→复用既有 non_limitup_funnel/pattern_scan/sector_cycle（不重写）
2. K线形态 4 战法 match 改读 PatternScan——R10 给 consolidation_days/ma5_proximity/volume_breakout 阈值（实现时定，复用既有 compute_*）
3. 板块领涨 compute_sector_stock_rank——个股内排名（R11，复用 relative_strength）
4. confidence 口径——复用 compute_confidence（R12，不派生，收敛）
5. zt_real akshare legu "真实涨停"口径——R15/R16 显示层或加字段（不改 _emotion 内部）
6. 板块轮动端点 date 默认值缺失——R18 修端点 date 默认 `last_trading_date_str()` + 前端传 triplet.today（非 aggregate_sectors industry 缺，ora-6 B5 修正）
7. kline cache 扩容——R20 baostock 全 A 刷新任务

## 9. 冲突审查

| 旧 spec/代码 | 旧决策 | S094 决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S093 R4 前瞻 pipeline | 涨停单 pipeline | 双 pipeline 统一底座 | 替换 | Workflow.tsx 双分区 + FLOW A+B 收敛 |
| S086 score_candidates | 跑全 12 战法 | funnel_type 分流 | 替换 | strategy_funnel_registry.py 加 funnel_type |
| S066 non_limitup_funnel | 独立端点 FLOW B | 接入主 pipeline + 统一底座 | 共存+重构 | non_limitup_funnel.py 委托 compute_strategy_score + 输出对齐 |
| NON_LIMITUP_WEIGHTS 硬编码 | L48 硬编码 | 删，委托 strategy_weights.json | 替换 | non_limitup_funnel.py L48 删 |
| market zt_count | len(zt) 东财 | 显示层 zt_real / _emotion 加字段 | 共存 | market.py 加 zt_real + 前端读 |
| sector_divergence 板块轮动 | 前端用 | 前端弃用，改 sector_cycle | 替换 | ContextTab 已改，R18 修 sector_cycle |
| baostock cache 1121 | 增量不扩容 | 全 A 扩容 | 替换 | refresh_kline_cache.py 全 A |

## 10. 阶段划分（ora-6 B4 重排：消除 S2 依赖 S3 倒置 + R26-R28 归属）

### S0 前置硬门：gene_scores 错位修复（S094-P0，独立 spec/分支）
- 写路径根因修复（_fetch_zt_pool 对历史日请求加 code 集合校验 / 换源校验）+ 历史行重算
- **S2/S4 合并前必须完成**

### S1 统一 K线契约 + 因子层 + 权重源（R1-R5）
- pattern_scan 自算 MA + 扩 compute_shadow_length_pct/compute_ma5_slope（B3）+ 传 sector_bars + 删 NON_LIMITUP_WEIGHTS + 委托 compute_strategy_score（B6 保留 per-strategy volume_signal）+ PatternScan 升唯一源

### S2 候选生产拆分 + sector_rank（R11/R14/R27）← ora-6 重排：sector_rank 前置
- compute_sector_stock_rank（R11）+ FLOW B 候选扩字段（R14）+ run_non_limitup_funnel 拆"只产候选"（R27）+ market_scan.py 新建（因子层+形态子+领涨子）

### S3 StrategyContext 扩展 + match 分流 + confidence（R6-R13/R26/R28）
- StrategyContext market_scan_ctx + score_candidates funnel_type + 既有调用传（含 forward_test L491，ora-6 A2）+ dragon_head 条件化 + 4 战法 match 改 PatternScan + confidence 复用 + R26 workflow._collect 调 gather_non_limitup_candidates + R28 briefing 分区透传

### S4 5 根因修复（R16-R21）
- zt_real 持久化 + 板块轮动端点 date 默认 + sector_divergence TODO + kline cache 扩容（R20 全 A 代码复用 load_industry_map 5540 条，ora-6 非阻断 #1）

### S5 前端 UI（R22-R25）
- 双 pipeline 分区+折叠 + 卡片流转 + StrategyMatchMatrix 分区 + UI bug

### S6 全量回归 + playwright
- pytest + vitest + tsc + vite build + playwright e2e AC1-AC11
