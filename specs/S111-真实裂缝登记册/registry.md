# 真实裂缝登记册（Living Registry）

> S111 的活文档。18 条数据源裂缝全档。一条裂缝"已修" = `test_data_honesty.py` 测试绿 + 本表状态列改"已修"。
> 本表比 spec.md 長命：S111 之后由后续承重切片（Tier-2/Tier-3）追加行。
> 数据源：S111 scan workflow（6 路扫描 + 综合 + 对抗核实，2026-08-30，22 agent）。

## 汇总

| 类别 | 条数 | 状态 |
|---|---|---|
| 诚实（仅登记，含 3 条 Tier-2 健壮性/防封修复项） | 4 | 登记完成 |
| Tier-1 撒谎（S111 已实现，全 confirmed_honest） | 6 | 已修 |
| Tier-2 撒谎（待后续切片，全 confirmed_lying） | 8 | 登记 |

> 14 条撒谎全部经对抗核实 confirmed_lying（默认尝试反驳、代码实锤才确认）。
> `premarket-selection-unguarded-cache-read` 原判"撒谎"被 verify 推翻为 **actually_honest**（诚实崩 500，健壮性缺陷非数据撒谎）——正是对抗核实防的假阳性，差点把崩错当撒谎去缝补。

## 诚实裂缝（4 条，仅登记）

### `fund-flow-120d-dual-break-honest-empty`
- where: `backend/data/sources/eastmoney.py:432-467`
- 现状: 东财 push2his + push2delay（主源，双 host loop）全断/数据不足(<5条)且新浪 MoneyFlow（备源）也断 → `stock_fund_flow_120d` 退出三层降级链诚实返 []。函数内无静默兜底用别的数据顶上（新浪是同语义四档资金流的正当降级，非别的数据）。源函数诚实，撒谎发生在下游消费层（见 Tier-1 #2/#3）。
- is_honest_empty: true | needs_fix: false | 状态: 登记完成
- 修法: 仅登记。标明源端已诚实、修复责任在下游

### `chip-breaker-permanent-no-recovery`
- where: `backend/data/sources/akshare_src.py:149,184`（decl:19, global:147）
- 现状: 手搓筹码熔断器 `_chip_fail_streak` 连续失败 3 次即永久 OPEN，`:149` 短路 return {} 不发请求，`:184` 复位仅在成功路径而熔断后不可达 → 进程生命周期内永久返空直到后端重启。返 {} 本身诚实（不臆造数值），但熔断不可恢复是可用性悬崖（对比 transport.py 通用 eastmoney breaker 有 60s recovery+half-open+2次成功复位）。caller diagnosis 标 missing 但文案"筹码分布未取得(akshare stock_cyq_em)"把"未发请求"归因成逐股取数失败，轻度归因失真。
- is_honest_empty: true | needs_fix: false（诚实性）| 状态: 登记完成
- 修法: 仅登记（诚实 {}）+ Tier-2 健壮性修复项：对齐通用 circuit_breaker 加 recovery_timeout/half-open/record_success 让熔断可自愈（非性质问题，是可用性悬崖）。chip_profit_ratio 当前不进 gene/total/winrate，污染面有限但筹码维度长期失明风险真实
- fix-spec-ref: Tier-2

### `chip-data-bypasses-generic-em-breaker`
- where: `backend/data/sources/akshare_src.py:164`（root: akshare stock_cyq_em.py:233 裸 requests 无 timeout）
- 现状: `chip_distribution` 直调 `ak.stock_cyq_em` → akshare 内部 `requests.get` 无 timeout/无限流/无通用熔断，故项目用 daemon 线程 8s 硬截断 + 手搓计数器替代，丢了通用 breaker 的 60s 恢复/half-open/代理探测。防封与可用性在所有东财数据里最弱。{} 把"服务宕""超时""akshare异常""该股当日确无筹码"4态压成同一 {}，caller 无法区分。返 {} 诚实（标 missing 不臆造），缺陷在防封缺口（§1.2 em_get 工程底线未覆盖此路径）+ observability。
- is_honest_empty: true | needs_fix: false（诚实性）| 状态: 登记完成
- 修法: 仅登记（诚实 {}）+ Tier-2 防封修复项：后续自建 cyq 取数走 em_get（限流/熔断/代理探测）替代 akshare 内部裸 requests，对齐 §1.2 工程底线（非性质问题，是防封/可用性弱化）
- fix-spec-ref: Tier-2

### `premarket-selection-unguarded-cache-read`【verify 推翻：诚实崩，非撒谎】
- where: `backend/strategies/premarket_selection.py:96`（KLINE_CACHE 定义 :22）
- 现状（verify 实锤）: `cache = json.loads(KLINE_CACHE.read_bytes())` 裸读无 exists() 检查无 try/except——此点属实。但异常经 `select_premarket_candidates`(:96)→`select_premarket_with_risk`(:190)→endpoint `routers/premarket.py:26`（均无 try）一路冒泡，最终被全局 `app.py:255-260 @app.exception_handler(Exception)` 接住返干净 HTTP 500 `{"detail":"服务器内部错误"}`，trace 落 uvicorn 日志。**全程不读旧缓存、不填默认值、不臆造候选——是 loud crash(500)，非 silent masking**。合成 agent 的"用替代数据掩盖"+"不报错"两处指控皆假。对照同仓 `first_board_filter.py:359-371`（`if not cache_path.exists(): _KLINE_CACHE={}`+try→{}）与 `first_board_premium_baseline.py:110-113`（`if not KLINE_CACHE.exists()`）均 exists()+try 优雅返空，唯此处裸读会崩。
- is_honest_empty: true（诚实崩）| needs_fix: false（诚实性）| 状态: 登记完成
- 修法: 仅登记（诚实）+ Tier-2 健壮性修复项（非性质修复）：补 `if not KLINE_CACHE.exists(): return []`（或 try FileNotFoundError→[]）对齐 `first_board_filter.py:359-371` / `first_board_premium_baseline.py:110-113` 守卫模式，使降级为空候选列表（附 data-missing 备注）而非 500 崩，盘前选股入口在 baostock 未装/首次运行时不致断。违反 spec S069"dev 无 baostock 降级不崩"契约。
- fix-spec-ref: Tier-2（健壮性，非性质）
- ⚠ 附带（verify 揪出兄弟项）: `scheduled_tasks.py:1860` `t1_review` 路径同型裸读，同崩不臆造，应加同款守卫。

## Tier-1 撒谎裂缝（6 条，S111 承重链，全部对抗核实 confirmed_lying）

### 1. `fallback-get-with-fallback-stale-cache-as-fresh`【根】
- where: `backend/fallback.py:135-137`
- 毒窗口: 实时 fetch 抛异常或返空时 `load_cache` 命中即原样返 ≤TTL 缓存，返回值无 stale/degraded/from_cache 元数据，调用方无法区分 live 与缓存。污染 6 调用方：risk_models capital_flow/dragon_tiger/seat、extreme_market_detector、sector_divergence 全 `get_with_fallback(ttl=600)`。叠加下游 `last_updated=now` 把陈旧标成"刚算完"。
- is_honest_empty: false | needs_fix: true | 状态: 已修
- 修法: R2 加旁路 `get_with_fallback_meta(key,fetch,ttl,fallback)` 返 `(data, meta{from_cache,is_stale})`，渐进迁移，不破坏既有 6 调用方签名
- fix-spec-ref: S111 R2

### 2. `realtime-capital-flow-stale-cache-mask`
- where: `backend/risk_models.py:473-488` + `backend/fallback.py:135-137`
- 毒窗口: `stock_fund_flow_120d` 诚实返 [] 被 `get_with_fallback(ttl=600)` 静默降级为 ≤10min 陈旧缓存当实时资金流，算出 `capital_flow_signal`(可能非0)/`big_fund_detected`(可能True)/`fund_flow_history`(5条陈旧)，`calculate_flow_adjustment=-signal*20`→`dynamic_score`→risk_level + recommendation 全基于陈旧资金流；`OneDayRisk.last_updated=now`(218) 伪标刚更新。经 `/api/limitup/analysis` 喂打板分析。
- is_honest_empty: false | needs_fix: true | 状态: 已修
- 修法: R4 消费 meta → `OneDayRisk.data_status=degraded`，不戳 last_updated=now，不返非零 signal（对齐 sentiment_context data_status 范式）
- fix-spec-ref: S111 R4

### 3. `risk-realtime-capital-flow-empty-as-neutral-signal`
- where: `backend/risk_models.py:492-498`
- 毒窗口: fetch 空 + 缓存也 miss → `fallback_value=[]` → history=[] → 返 `{capital_flow_signal:0.0, big_fund_detected:False, fund_flow_history:[]}`，与"净流入≈0/无大资金"合法中性信号同形无 data_status 区分。signal=0→adjustment=0→risk_score=base 不变；trend='震荡'；断源被呈现成"平稳市"喂打板/情绪。
- is_honest_empty: false | needs_fix: true | 状态: 已修
- 修法: R4 空 history → `data_status=missing` 不伪装中性 dict（对齐 _empty_context 全None+missing）
- fix-spec-ref: S111 R4

### 4. `fund-flow-120d-sina-cross-source-silent-substitute`
- where: `backend/data/sources/eastmoney.py:464` (`stock_fund_flow_120d` → `_sina_fund_flow_fallback`)
- 毒窗口: 东财 push2his/push2delay 双 host 失败或 <5 条时静默切新浪 MoneyFlow，返回与东财字段名/形状/单位完全一致的 rows 无任何来源标记。下游 risk_models 当东财正典数据归一化算 signal/big_fund；新浪主力/超大单口径与东财 f52 聚合算法有细微差异，max_abs 跨源混算失真。S110 验证了"降级会发生"但未验证"下游能识别来源"。
- is_honest_empty: false | needs_fix: true | 状态: 已修
- 修法: R3 新浪降级路径加 source provenance（对齐 kline_resolver source_name 元组 / market._emotion data_source 字段）
- fix-spec-ref: S111 R3

### 5. `chip-structure-stale-nearest-bar-fallback`
- where: `backend/strategies/first_board_filter.py:316`
- 毒窗口: `extract_chip_structure` 用 `bars[i].date<=d` 取"当日或之前最近 bar"，请求日 bar 不在 cache 时静默回退前一日(D-1) 的 turnover/量比/成交额冒充当日。baostock 当日 bar 须 kline_refresh(16:30) 入 cache，first_board_filter 跑在 16:15（早 15min），故每日系统性缺当日 bar、`<=` 恒返昨日 → score_dim_turnover(权重0.15) + score_dim4_chip 用过期值打分 → 9维 total 偏高（掩盖涨停日筹码松动）→ rank → 精选/观察池 → forward_test picks。premarket `_compute_dual_confirmation` 读同 cache 同样滞后。反差：`_bar_close` 用 `==` 精确匹配缺则跳过（诚实范式在仓内）。
- is_honest_empty: false | needs_fix: true | 状态: 已修
- 修法: R6 `<=`→`==` 精确匹配（对齐 `_bar_close:1885`），缺当日 bar 返 {}
- fix-spec-ref: S111 R6

### 6. `risk-base-score-silent-50`
- where: `backend/risk_models.py:109-111`
- 毒窗口: `calculate_base_risk` 查 limitup_screener gene_scores 缺失或任一异常（含 DB/import 错误）→ bare `except: pass` → return 50.0，把"代码未入 screener（合法中性先验）"与"取数故障"压成同一 50.0 无 data_status 区分。50.0 进 `dynamic_score:149`→`risk_level:157-162`。半透明（score_components.base_score=50.0 可见但无 degraded 标）。
- is_honest_empty: false | needs_fix: true | 状态: 已修
- 修法: R7 收窄 except 或裸失败路径设 `data_status=missing` 区分"无 gene score 中性先验"与"取数故障"
- fix-spec-ref: S111 R7

## S111 实现后修复记录（review 驱动，2026-08-30）

实现 workflow（3 并行 impl + 3 路 review）落地 R2-R8，10 测试全绿，全量 2416 passed（+2 新测试，1 pre-existing S066 归档债非 S111）。review 抓 4 项，3 项已补修：

| # | finding | severity | 补修 |
|---|---|---|---|
| 1 | R7 narrowed except 漏 sqlite3.OperationalError/TypeError/OSError → DB 故障 propagate 502 | MEDIUM | 改 broad `except Exception`+log+missing（故障 vs 合法先验靠异常路径区分）；加 test_calculate_base_risk_db_operational_error_marks_missing 钉死 |
| 2 | #4 source provenance 孤立——_get_realtime_capital_flow 从不读 source，live-sina 仍当东财正典标 ok | LOW（关毒窗口） | _get_realtime_capital_flow 读 source→sina 降级行标 degraded；加 test_realtime_capital_flow_sina_cross_source_marks_degraded 钉死。**#4 由 uncertain → confirmed_honest** |
| 3 | get_with_fallback_meta bare `except:pass` 无日志（spec R7 批的同款 anti-pattern） | LOW | 加 `logging.getLogger("fallback").debug(...)`；原 get_with_fallback 保持零改动 |
| 4 | _with_source 把 source 键泄漏到所有 fund flow API 响应（/api/fund-flow 等） | LOW | **延后 Tier-2**：字段加性兼容（JSON 序列化无碍，62 相关测试过），spec 加性哲学下可接受；前端后续可消费作 degraded 徽章。结构性收窄（仅 risk_models 消费路径）留 Tier-2 |

## Tier-2 撒谎裂缝（8 条，登记待后续切片，全部对抗核实 confirmed_lying）

### `risk-dragon-tiger-silent-zero`
- where: `backend/risk_models.py:267-268`
- 毒窗口: `_get_dragon_tiger_risk`：dragon_tiger_board 取数/解析任一异常或 fallback 缓存空 → return 0.0，无日志无标记，与"近期未上榜=0风险"同形。`_build_risk_factors` 见 dragon_tiger_risk<=30 不加"龙虎榜风险较高"→风险低估，risk_level 可能 HIGH→MEDIUM。bare except 无 logger（对比 :347/:371/:391 有 warning）。
- 修法: 0.0→data_status=missing + 补 logger 对齐 :347/:371/:391 warning sibling；级联自 fallback 根#1

### `risk-seat-info-silent-empty`
- where: `backend/risk_models.py:320-325`
- 毒窗口: `_get_seat_info`：compute_consensus_signal 任一异常或 fallback=None → return {one_day_seats:[],multi_seat_signal:False,seat_confidence:0.0}，与"当日无特征席位"合法结果同形无 data_status。席位共识信号源断时漏报。bare except 无 logger。
- 修法: 空 dict→data_status=missing + 补 logger；级联自 fallback 根#1

### `risk-concentration-silent-zero`
- where: `backend/risk_models.py:398-420`
- 毒窗口: `_calculate_concentration_risk`：直调 `astock.dragon_tiger_board`（未走 get_with_fallback 缓存层，更脆，单次断连即返空）→ records 空 return 0.0 或 bare except return 0.0，无日志无标记。集中度维度被低估。裸调 + except:420 无 logger。
- 修法: 套 get_with_fallback 缓存层（对齐同模块 dragon_tiger）+ 0.0→missing + logger

### `sector-divergence-silent-empty`
- where: `backend/sector_divergence.py:172-173`
- 毒窗口: `calculate_sector_divergence`：industry_comparison 源断 → fallback_value 空板块 → return[]，或 bare except return[]（无 logger 无标记）。板块分化/轮动在源断时返空，情绪面板板块维度静默漏报；`calculate_sector_rotation` 同模式返 None。`last_updated=now`(:165) 把陈旧标 fresh。
- 修法: []→data_status=missing + 补 logger（:172/:227/:313 三处）；级联自 fallback 根#1

### `extreme-market-broken-zt-pool-as-normal`
- where: `backend/extreme_market_detector.py:119-164`
- 毒窗口: 涨停/跌停/炸板池源(em_zt_topic_pool)断连且缓存失效时，fallback_value={zt/dt/zb:[]} → zt_count=0 → signal_type='正常'、is_extreme=False，ExtremeMarketSignal 无 data_status/degraded 字段 + last_updated=now。涨停潮/跌停潮判定在源宕时静默漏报，盘中断源期情绪面板与打板信号基于假"平静市"触发天气熔断/仓位闸误判。
- 修法: 空池(源断)→data_status=missing/degraded 不判"正常"，与"真平静"区分；级联自 fallback 根#1，修 meta 透传即解

### `score-dim4-chip-silent-50-neutral-fallback`
- where: `backend/strategies/first_board_filter.py:848,893-894`
- 毒窗口: `score_dim4_chip` 子项换手/量比/成交额缺数据各默认 50.0（:848/:862/:878），整函数异常 try/except 返 50.0（:893），把"数据断裂"伪装成"筹码结构中等"。raw_values 字段虽诚实 None 但 scores['chip']=50 已撒谎。当前 chip 不在 MARKET_PHASE_WEIGHTS（:81-98 仅5核心维度）→:1349 权重门对 chip 为 False → 50 既不进 weighted_sum 也不进 total，故 latent 不污染；但写进候选 dict 展示误导，且:1319 注释"待回测校准后调整"——一旦给 chip 非零权重，缺失→50 掩盖真实筹码松动/过冷。同胞 `score_dim_turnover:1274` 缺失返 -1 不加权（诚实范式在仓内）。
- 修法: 50.0→-1 对齐 score_dim_turnover:1274 sibling（缺失不参与加权）。latent 项（权重0不污染 total），与 chip 权重回测校准同批

### `gstock-push2delay-permanent-latch-no-delay-flag`
- where: `backend/gstock.py:53-65`
- 毒窗口: `_push2_stock_get`：push2(实时)失败一次后 `_gs_host[0]=i` 永久 latch 到 push2delay（延时~15min 镜像），整进程后续所有 global_indices/us_hk_stock 调用永久走延时且不回探 push2，返回 d 无 is_delayed/latency 标记。`routers/market.py:101` 直接当前态返前端，单次 push2 瞬断后整进程给前端喂延时美港股/指数当"实时"。storm_predictor 读 T-1 夜间快照（延迟语境危害较小）但前端实时展示无延时提示。对比 bids/turnover 是 per-call 重试 push2 危害小。
- 修法: 去永久 latch 改 per-call 重试 push2（对齐 bids/turnover）或保留 latch 但加 is_delayed 标记透传 _quote_from/global_indices（对齐 market._emotion data_source）

### `newsradar-cache-no-ttl-stale-as-fresh`
- where: `backend/newsradar.py:215-218`
- 毒窗口: `newsradar.get_radar(force=False)` 恒返 `load_cache()`，load_cache 仅 FileNotFoundError/JSONDecodeError→None 无 TTL/时间戳校验。调度 fetch 断/未跑时返上次成功写的旧缓存当新 radar，generated_at 虽是旧时间（部分诚实）但系统不标 stale 不回退 skeleton，recent_days 时效窗口在调度断期间静默失真。比 fallback.py 更糟（无 TTL 上界）。
- 修法: load_cache 加 TTL 比较 + 过期返 skeleton（诚实空，对齐 fallback.py TTL 范式）

## 本轮未覆盖维度（completeness gaps，后续切片补扫）
- AI 出口诚实（chat.TOOLS/_exec_tool→registry.execute）：数据工具失败时返给 LLM 的是诚实 'unavailable' 还是 bare None/[]（LLM 可能据此臆造）——数据进入 AI 研判的最后一跳
- 写侧/落盘诚实：storm_daemon 每 30min 存 global_indices 快照，若 push2delay 已 latch 延时数据会被快照固化 → storm_predictor 读 T-1 快照做风暴预测；forward_test 写 verdict 时效性
- cron DAG 时序（消费者先于生产者）：baostock 16:15 vs kline_refresh 16:30 已确认一条；其余 cron 触发时点 vs 数据源就绪时点的 consumer-before-producer 竞态未系统审
- 多 worker 缓存一致性：fallback._MEM_CACHE 进程内+磁盘；多 uvicorn worker 时内存缓存分叉
- 交易日历门控：非交易日/周末路径是否返"今日"数据当实时
- 跨源 date 匹配口径一致性：全仓 date 匹配（== vs <= vs in-range）未做声明式断言统一
- baostock T+1 stuck-mark 7 日：拖慢 §44 lift 样本积累（forward_test T+1 回填慢、verdict 久留探索性 n<30），borderline 入册待定
- 新浪降级无最小条数校验：返 1-4 条当 120d 历史致 max_abs 归一化口径漂移
