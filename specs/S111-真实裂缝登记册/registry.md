# 真实裂缝登记册（Living Registry）

> S111 的活文档。18 条数据源裂缝全档。一条裂缝"已修" = `test_data_honesty.py` 测试绿 + 本表状态列改"已修"。
> 本表比 spec.md 長命：S111 之后由后续承重切片（Tier-2/Tier-3）追加行。
> 数据源：S111 scan workflow（6 路扫描 + 综合 + 对抗核实，2026-08-30，22 agent）。

## 汇总

| 类别 | 条数 | 状态 |
|---|---|---|
| 诚实（S113 修 chip-breaker+premarket；chip-cyq S114 修；fund-flow-dual-break 仅登记） | 4 | 3已修+1登记 |
| Tier-1 撒谎（S111 已实现，全 confirmed_honest） | 6 | 已修 |
| Tier-2 撒谎（S112 已实现，全 confirmed_honest，含已知限制） | 8 | 已修 |

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

## S112 实现后状态 + 修复记录 + 已知限制（2026-08-30）

**Tier-2 8 条撒谎全修**（S112 workflow 4 并行 impl + 3 路 review，18 测试全绿，全量 2424 passed 0 S112 回归）。对抗 honesty 8/8 confirmed_honest on literal claims。

**review 驱动补修 3 项 + post-S112 over-reporting fix（2026-08-30）**：

| # | finding | severity | 补修 |
|---|---|---|---|
| 1 | extreme detector 漏补 sector 同款"不缓存 missing"守卫——源恢复后延迟再探测最长 5min | MEDIUM | get_extreme_market_signal 加 `if data_status!='missing': _set_cached` 守卫（对齐 sector_divergence:308），missing 不缓存源恢复即重探 |
| 2 | SOX dict 缺 is_delayed 字段（8 push2 指数有，SOX 无，前端按 is_delayed 消费得 None） | LOW | _fetch_sox_datacenter 返 dict 显式加 is_delayed=False（日频非延时镜像） |
| 3 | newsradar skeleton() 裸读 SOURCES_FILE 无 try/except + load_cache except 未含 UnicodeDecodeError/OSError | LOW | skeleton 包 try/except 退最简骨架；load_cache except 扩 (FileNotFoundError,JSONDecodeError,UnicodeDecodeError,OSError) |
| 4 | risk-trio over-report 'missing'（头部发现）：_is_empty 分不开源断 vs 未上榜→99% 非上榜股永久 missing | HIGH（reliability） | post-S112 fetch_ok fix：meta 加 fetch_ok 标志，risk-trio empty 分支按 fetch_ok 区分 ok(未上榜/无席位) vs missing(源断)；+3 测试钉死。原 crack 不可区分诉求已解决 |

**⚠ 已知限制（未修，待后续）**：

- ~~risk-trio over-report 'missing'~~ **✅ 已修（post-S112 fetch_ok fix, 2026-08-30）**：见上表 row 4。get_with_fallback_meta 加 fetch_ok 标志，risk-trio empty 分支按 fetch_ok 区分 ok(未上榜/无席位) vs missing(源断)，3 测试钉死。原 crack"源断 vs 未上榜不可区分"诉求已解决。residual：源限流返空(非抛异常)→ok（罕见，非 lie，data 确空）。
- **gstock is_delayed 无消费者**：backend 真标 is_delayed 透传到 /api/global/indices JSON 边界，但 grep 全仓零 reader（前端未消费）。"延时当实时"危害 backend 已诚实但未端到端闭环→前端任务。
- **DRY _resolve_pool_provenance / _resolve_sector_provenance**：两 helper 近乎逐字重复，日后易分叉→抽共享 helper（纯质量，非阻塞）。
- **extreme degraded 仍缓存 5min**：fix 1 只跳过 missing 缓存，degraded 仍缓存（陈旧计数有参考价值，可接受；若天气熔断要 best-effort 陈旧判定可改）。

## S113 实现后状态（2026-08-30，availability 切片）

S113 修 2 条诚实缺陷项 availability（非性质撒谎）+ 1 文档化。3 路 review 全 confirmed_available，5 测试全绿，全量 2432 passed 0 回归。

| 项 | 状态 | 说明 |
|---|---|---|
| chip-breaker-permanent-no-recovery | ✅ 已修 | R1：删除手搓 _chip_fail_streak，复用通用 circuit_breaker.get_breaker("akshare_chip", config=failure_threshold=3/recovery_timeout=60/success_threshold=2)，OPEN→60s→half-open→2次成功复位/失败回 OPEN。返 {} 诚实不变。对齐 transport.py/worldmonitor/eastmoney/hithink_src sibling。 |
| premarket-selection-unguarded-cache-read | ✅ 已修 | R2：premarket_selection.py:96 加 _load_kline_cache() helper（exists()+try→{}）+ market_note data-missing，对齐 first_board_filter:357-384。缺 cache 返 [] 非 500，守 S069 优雅降级契约。 |
| chip-data-bypasses-generic-em-breaker | ✅ 已修（S114） | 自建 _fetch_cyq_klines 走 em_get（push2his kline/get + ut=_ZTB_UT + timeout=8 + breaker('eastmoney')），删 ak.stock_cyq_em 黑盒 + 删 daemon 8s + 删 chip breaker（em_get 覆盖）。CYQ_JS 搬东财原 JS 保真（py_mini_racer）。返{} 4态诚实。见 S114 状态节。 |
| source-key-leak（deferred LOW） | 📝 文档化 | R3：fund flow API 响应带 source provenance（_with_source 加性），前端可后续消费 degraded 徽章。不结构性收窄（provenance 对 R4/S112 cross-source 检测有用）。 |

**review 观察（2 LOW，非 bug，无需改码）**：
- scheduled_tasks:1860 守卫实为 c1a499e8（S101, 2026-08-28）既有，早于 S113——spec R2"同型裸读同崩"前提 stale，agent 查证后未加冗余守卫（不做"看起来正确但没用"的事）。S113 只加了钉死测试。availability 达成与哪个 commit 加守卫无关。
- CircuitBreaker 状态变更有无 threading.Lock——既有缺陷，与 transport.py 同款，影响低（当前无并发筹码取数路径），后续若并发成真再加锁。

## S114 实现后状态（2026-08-30，最后一条诚实缺陷项）

S114 把 chip_distribution 取数层从 ak.stock_cyq_em 黑盒改自建走 em_get，关最后一条防封缺口（§1.2 em_get 工程底线）。research（wf_be9f461b）+ impl（w074x03hi）+ 3 路 review。

| 项 | 状态 | 说明 |
|---|---|---|
| 取数层 em_get | ✅ 已修 | R1 _fetch_cyq_klines 走 em_get（push2his kline/get + ut=_ZTB_UT + timeout=8 + breaker('eastmoney') 限流/熔断/代理探测/UA），删 ak.stock_cyq_em 裸 requests 黑盒 |
| daemon 8s 硬截断 | ✅ 已删 | R2 em_get timeout=8 真实 socket 超时，无限挂起根因消除 |
| chip breaker | ✅ 已删（R8） | em_get breaker('eastmoney') 已覆盖，_CHIP_BREAKER_NAME 冗余删（对齐 hot_money_seats 复用范式） |
| CYQ_JS 保真 | ✅ 已搬 | R5 从 akshare stock_cyq_em.py:27-218 搬东财 CYQCalculator JS 到 cyq_js.py（6315 字符逐字一致），py_mini_racer 跑（策略 A，V8 依赖 akshare 已带不新增） |
| 返 {} 4态诚实 | ✅ | R3 em_get 熔断 OPEN/请求异常/无筹码/解析失败 → 均 {}（falsy，diagnosis.py:230 missing 标记）；R4 不返 {chip_profit_ratio:None} truthy 绕过 |
| 5键 shape 不变 | ✅ | R6 chip_profit_ratio/avg_cost/concentration/90_cost/70_cost |

**review**：6/7 availability confirmed（em_get 真用/ut 真带/熔断不冒泡/返 falsy {}/CYQ_JS 逐字保真/5键不变），1 still_broken 是测试残留（S113 chip_breaker 测试引用已删 _CHIP_BREAKER_NAME）→ 已删 dead 测试修复。1 LOW（_fetch_cyq_klines skip 坏行 vs akshare raise，改进非 bug，不修）。

**⚠ live AC1 未验**：本机被东财 push2his kline/get 拒连（RemoteDisconnected，反爬/IP 针对性拒绝，akshare 原版同款拒连——非实现缺陷）。em_get 防封工作（无挂起/熔断/代理探测/timeout），失败诚实返 {}。live test（test_chip_distribution_live_returns_nonempty_with_numeric_ratio）标 @pytest.mark.live，offline 跳过，待东财恢复或换网络手验。

**ut 厘清**：kline/get 用 _ZTB_UT（7eea...，实为日K通用公开 token 非密钥，被误命名涨停池）；非 fflow 的 _PUSH2_UT（fa5fd...）。两者同 host 不同 path 吃不同 ut。eastmoney.py:142 加注释说明。

## S115 实现后状态（2026-08-30，completeness-gaps 扫描 + 三修）

S115 scan（wf_fe0ad61d，7路+综合+对抗核实）扫 registry「本轮未覆盖维度」，发现 18 条新裂缝。impl（wf_f3ebbecb-116，4并行+3路review）修 3 confirmed_lying，15 非撒谎登记。3 fix 全 confirmed_honest，24 测试全绿，全量 2437 passed 0 S115 回归。

**3 confirmed_lying（全 confirmed_honest，已修）**：

| crack | where | 修法 |
|---|---|---|
| first-board-settlement-t0-bar-lte-fallback | first_board_settlement.py:524 | `<=`→`==` 精确匹配 signal_date，缺当日 bar→None 跳过（非邻近 bar 冒充），t0_date provenance。§44 承重链 |
| sina-fallback-no-min-bars-maxabs-drift | eastmoney.py:475 | 新浪降级路径加对称 len>=5 门（对齐东财 :466），<5→[] 落回 missing |
| storm-predictor-internal-null-sti-as-zero-calm | storm_predictor.py:162 | STI NULL 列/source_ok=0/no-row → missing+50.0（中性基线，非 0.0+ok 假平静） |

**6 actually_honest**（verify 推翻合成 over-claim，登记非修）：hithink-trio-bare-empty / query-quote-bare-empty-tencent / mcp-iserror-false-on-bare-empty / storm-predictor-global-discards-is-delayed / storm-daemon-snapshot-no-provenance（✅ S116 已修 availability，见 S116 状态节）/ portfolio-realtime-pnl-no-calendar-gate。皆诚实返空非 fabricate（防住 6 假阳性缝补）。

**1 uncertain**：gstock-us-hk-no-calendar-gate（周末返周五收盘 is_delayed=False 无 trade_date，live API 消费者难区分；非 fabricate，语义缺口，可选修 gstock 请求 f86 date）。

**8 honest_already**（latent，登记）：fallback-mem-shadows-disk / funnel-mem-shadows-db（多 worker 缓存分叉，当前单 worker 诚实，扩 gunicorn 前必修）/ premarket-funnel-cache-fdate-offbyone（✅ S117 已修，见 S117 状态节） / first-board-filter-kline-race / forward-test-daily-gene-scores-race / forward-test-t1-settle-baostock-race / first-board-t1-review-kline-sametick（cron 时序竞态诚实空，共同根因 baostock 当日 EOD 时点未定）/ baostock-t1-stuck-mark-7d-slows-section44-lift（§44 样本偏，诚实仅登记）。

**review 补修 2**：R2 broke S111 #4 test（2 行 fixture 被 R2 min-bars 门 gated）→ #4 fixture 扩 5 行（过门测 source provenance，#16 测 <5→missing）；R3 新 helper `_load_sti_internal_signals` bare except 无 log → 加 logger.warning（对齐 S111 R7/S112 anti-pattern 修复）。

**撒谎总账**：14（S111/S112）+ 3（S115）= **17 confirmed_lying 全修**。诚实登记 4（S111）+ 15（S115）= 19。registry 覆盖从 S111 的 18 扩到 36（18+18）。「本轮未覆盖维度」8 项已扫（S115），剩余 open：baostock EOD 时点 / 多 worker 硬化 / baostock stuck-mark 动否 / storm-daemon last-write-wins availability（✅ S116 已修）/ premarket off-by-one 提 medium 级否——见 spec §9。

## S116 实现后状态（2026-08-30，storm-daemon availability）

S116 修 S115 scan #7 storm-daemon-snapshot-no-provenance-last-write-wins（verify 判 actually_honest 但明确称"worth fixing independent of lying"的可用性缺陷）。impl（wf_4e5e0018）+ 3 路 review。4/4 confirmed_available，10 availability 测试全绿，全量 2440 passed 0 回归。

| 项 | 状态 | 说明 |
|---|---|---|
| fetch_snapshot provenance | ✅ 已修 | R1 global_fetch_ok=bool(global_indices 非空)；失败/空→fetch_ok=False/is_degraded=True 落盘（storm_daemon.py:41,46,53,54） |
| get_t1_global_snapshot 过滤 | ✅ 已修 | R2 从盲 snaps[-1] 改过滤 `[s for s if global_indices and fetch_ok]` 取最近好；全坏→reversed 取最近坏 + `{**s,is_degraded:True}` 不可变拷贝（:109-118） |
| storm_predictor 读 provenance | ✅ 已修 | R3 _collect_global_factor 读 snap.is_degraded→data_status='degraded'（非 ok 假装）；fallback 仅当 ok 才改 fallback_current（:86-96） |

**review 补修 3**：MEDIUM 全坏分支零覆盖（R4.2 mock 掉 get_t1 绕过）→ 加直接喂 [bad1,bad2] 测真实 get_t1 钉死 reversed+is_degraded；LOW fetch_snapshot exception 仅 debug → 升 warning（连续多日失败运维可见）；LOW StormFactor.data_status 注释 `# ok|missing` 陈旧 → 更新 `# ok|degraded|fallback_current|missing`。

storm cluster 终账：#8 NULL-sti（S115 R3 修）、#6 is_delayed（verify 推翻 honest 不修）、#7 last-write-wins（S116 修）——全收口。

## S117 实现后状态（2026-08-30，premarket off-by-one 功能性修复）

S117 修 S115 scan #13 premarket-funnel-cache-fdate-offbyone（honest_already：诚实但致 S101 整式空转）。非性质撒谎，是功能性日期 bug。2442 passed 0 回归。

**off-by-one**：S101 三时点通知（9:25 竞价 / 9:35 开盘 / 16:35 T+1）全用 `f_date = payload.get("date") or last_trading_date_str()`，但 `last_trading_date_str()` 在交易日返 today=T 日，而 final_candidates 存在 F 日（prev trading day）→ `_load_final_cards(T日)` 找不到 → no_candidates → S101 三时点通知**整式空转**（永远跳过从不发）。注释意图是 F 日，代码取 T 日，off-by-one。

**修**：vr_paths 加 `prev_trading_date_str` helper（对称 last_trading_date_str，返严格前一交易日）；3 S101 任务 f_date 改 `prev_trading_date_str()`（F 日）。对齐 storm_predictor `_prev_trading_day` 范式（S088 grill Q1 修过同款"前一交易日取到当日"bug）。

**测试**：①vr_paths 单元（prev≠last，d=交易日时 last 返 d、prev 返前一）②behavioral t1_review 空 payload → f_date=F 日 → _load_final_cards(F 日) → candidates 找到 → notified（非 no_candidates 空转）。

## 本轮未覆盖维度（completeness gaps，后续切片补扫）
- AI 出口诚实（chat.TOOLS/_exec_tool→registry.execute）：数据工具失败时返给 LLM 的是诚实 'unavailable' 还是 bare None/[]（LLM 可能据此臆造）——数据进入 AI 研判的最后一跳
- 写侧/落盘诚实：storm_daemon 每 30min 存 global_indices 快照，若 push2delay 已 latch 延时数据会被快照固化 → storm_predictor 读 T-1 快照做风暴预测；forward_test 写 verdict 时效性
- cron DAG 时序（消费者先于生产者）：baostock 16:15 vs kline_refresh 16:30 已确认一条；其余 cron 触发时点 vs 数据源就绪时点的 consumer-before-producer 竞态未系统审
- 多 worker 缓存一致性：fallback._MEM_CACHE 进程内+磁盘；多 uvicorn worker 时内存缓存分叉
- 交易日历门控：非交易日/周末路径是否返"今日"数据当实时
- 跨源 date 匹配口径一致性：全仓 date 匹配（== vs <= vs in-range）未做声明式断言统一
- baostock T+1 stuck-mark 7 日：拖慢 §44 lift 样本积累（forward_test T+1 回填慢、verdict 久留探索性 n<30），borderline 入册待定
- 新浪降级无最小条数校验：返 1-4 条当 120d 历史致 max_abs 归一化口径漂移

## S118 实现后状态（2026-08-31，completeness-gaps 第二轮扫描 + 龙虎榜源端）

S118 scan（wf_552c8943-5d3，8 维并行 finder + per-finding 对抗核实 + 完整性 critic，26 agent 0 error，~1.2M token）扫旧「本轮未覆盖维度」7 项 + 用户追加龙虎榜源端（第 8 维，S107 占位草案从未实现）。17 裂缝：9 confirmed_lying / 8 actually_honest / 0 uncertain。已抽验 3 处代码实锤：fix_now（source-em-swallow，eastmoney.py:366 吞异常→[] + fallback.py:191-195 fetch_ok=不抛异常 + risk_models.py:305 ok 分支，链环闭合，"击败 S112"判词成立）/ hithink-rank（hithink_src.py:248 `if data is None: return []` 坍缩失败与合法空）/ critic 最 material 漏扫（risk 三子维度 risk_models.py:411-474 except 返 0.0 + _merge_data_status:215 不含三者）。verify gate 成立。**本节 critic 的 6 漏扫维度 = 新「本轮未覆盖维度」，取代旧 §本轮未覆盖维度（旧 8 项已全扫）。**

**9 confirmed_lying（待后续切片修，按 fix_urgency/sev 排序）**：

| crack | where | sev | fix_urgency | 修法 |
|---|---|---|---|---|
| source-em-swallow-defeats-fetch-ok | eastmoney.py:366 | HIGH | ✅ 已修（S119） | eastmoney_datacenter 改：em_get/.json() 抛异常时 raise typed SourceUnavailable（非 bare return []），仅 HTTP 成功但 result.data 空才返 []（真无数据）。单点覆盖 dragon_tiger_board 三处 + seat_engine._pull_records + hot_money_seats 间接。**⚠ 击败 S112**：fetch_ok 区分"源断 vs 未上榜"前提是源端源断会抛异常，但源端把源断也变 []→fetch_ok 恒 True→源断伪装"未上榜 ok"→risk 归零。S112 在源端被绕过，须回看。**S119 已修**（opt-in raise_on_failure，见 S119 状态节）。 |
| ai-hithink-rank-empty-on-failure | hithink_src.py:248 | HIGH | ✅ 已修（S120） | skyrocket/hot_stock/anomaly_list 把 `if data is None: return []` 改 raise RuntimeError；registry.execute 兜成 {"error"} 喂 LLM；router 同步 502；改 test_skyrocket_failure_empty 断言（从 ==[] 改 raises/返 error）。同仓 query_global_stock/worldmonitor_query 失败返 {"error":"暂不可达"} 是诚实范式。⚠ 关联 hithink APIKey 泄漏待轮换，轮换后旧 key 401 活体触发此路径。**S120 已修**（见 S120 状态节）。 |
| ai-tencent-num-zero-coercion | tencent.py:58 | HIGH | worth_fixing | num() 对空/非数值返 None 而非 0.0（根因），或范围修：quote_from_tencent 对 0 永不合法字段（price/pe_ttm/pe_static/pb/last_close/open/high/low/market_cap/float_market_cap）用 `_numf(...) or None` 把 0.0 归 None。亏损股 PE 未定义→gtimg 返空/"-"→num()→0.0 喂 LLM 当真 PE=0 极度低估。触 §1.2 不臆造底线。 |
| market-emotion-realttime-weekend-silent-fallback-no-calendar-gate | market.py:220 | HIGH | worth_fixing | market._emotion(date=None) 实时入口加交易日历门控：周末/非交易日不取 em_zt_topic_pool 当日池当实时，返 stale 或标 is_delayed/trade_date。em_zt_topic_pool 静默回退是唯一未守卫缺口。 |
| realtime-capital-flow-no-date-provenance-carryforward-as-fresh | risk_models.py:670 | MEDIUM | worth_fixing | _get_realtime_capital_flow 取 history[-1] 加 date 校验：盘前 carry-forward 资金流（无当日 bar）标 data_status=degraded/missing 不戳 last_updated=now。 |
| hot-money-seats-partial-fetch-silent | hot_money_seats.py:109 | MEDIUM | worth_fixing | fetch_billboard_for_date 单侧断流 except:continue 静默返半截→席位画像在残缺数据上算 next_day_sell_rate。返 {rows,buy_ok,sell_ok}，残缺日不纳入聚合 + warning 日志（非 bare continue）。 |
| seal-intraday-cron-misses-1500-close-auction-final | scheduled_tasks.py:2214 | MEDIUM | worth_fixing | seal_intraday_collect cron `* 9-14` 止于 14:59，漏采 15:00 收盘集合竞价终态涨停/炸板；注释假称覆盖 15:00-15:05。改 cron 到 15:05 或加 15:00 专项采集。verify 推翻 finder honest_empty 判 confirmed_lying（注释撒谎）。 |
| backtest-daily-snapshot-degraded-hit-rate-no-provenance | backtest_lite.py:78 | MEDIUM | worth_fixing | backtest_daily_snapshots 落盘 degraded hit_rate 加 provenance：取数失败被 _calc_next_day_return 静默压成 0.0 当真实命中率落盘固化。加 fetch_ok/is_degraded 标。 |
| storm-daemon-news-items-no-provenance | storm_daemon.py:40 | LOW | worth_fixing | storm_daemon 快照 news_items 加 provenance：部分源失败的新闻被当完整隔夜快照喂 storm_predictor。 |

**8 actually_honest（登记非修，verify 推翻 lying 主张或判诚实空/latent）**：
- ai-eastmoney-reports-soft-empty（eastmoney.py:72，MEDIUM）— reportapi 信封无 success/message 字段（实测），返 [] 诚实；verify 称未触发真 429（违防封底线）不活测，留登记。
- ai-query-quote-bare-empty-dict（stock_tools.py:30，LOW）— query_quote tencent 瞬态失败返裸 {}，与兄弟工具范式不一，但非 fabricate。
- premarket-t1-review-kline-refresh-completion-race（scheduled_tasks.py:1860，MEDIUM honest_empty）— 16:35 读 baostock cache 时 16:30 kline_refresh 未原子写完，S101 T+1 通知系统性空（与 S117 f_date off-by-one 不同根因，另立登记）。
- scheduler-daemons-no-single-worker-guard（app.py:88 + scheduled_tasks.py:2072/2079/2122/510，HIGH availability）— lifespan 调度器/守护/采样器无单 worker 守卫 + fire 无跨 worker dedup，多 worker 下 N× 跑（N× em_get 防封底线 + 缓存分叉）。当前单 worker 诚实，扩 gunicorn 前必修（对齐 multi-worker-cache latent）。
- funnel-config-inprocess-no-propagation（candidates.py:51/140/105，MEDIUM robustness）— ThresholdConfig `_store` 纯进程内无持久化/跨 worker 传播，多 worker 阈值改动分叉→rerun 候选集静默不一致。
- storm-t1-snapshot-no-night-gating-blocks-current-fallback（storm_daemon.py:90-121 + storm_predictor.py:82-96/140，MEDIUM robustness）— get_t1_global_snapshot 取 good[-1] 无夜间时段门控，非空 T-1 快照阻塞 current fallback（dev 盘前停机用盘中/盘前美盘值当隔夜）。
- forward-test-t1-settle-stuck-mark-conflates-transient-with-permanent（scheduled_tasks.py:1252-1265 + kline_returns.py:91-118 + scheduled_tasks.py:2294 vs :2254，MEDIUM robustness）— stuck-mark 把暂态 fetch-empty 当永久 no-bar 施 7 日抑制，15:50 cron 命中 baostock EOD 未就绪（baostock-stuck 维度 borderline，登记）。
- s107-hithink-dragon-tiger-unimplemented（S107 spec.md:3，LOW completeness_gap）— S107 占位草案从未实现，hithink 个股+概念维度与东财席位维度不重叠，东财断无备援是维度约束下诚实缺口，非缺陷（用户追加龙虎榜维度的产出）。

**撒谎总账**：14（S111/S112，全修）+ 3（S115，全修）+ 1（S119，已修）+ 1（S120，已修）= 19 全修 → +7（S118 待修）= **26 confirmed_lying，其中 7 待修**。诚实登记 19 + 8 = 27。registry 覆盖从 36 扩到 53（36+17）。

## S119 实现后状态（2026-08-31，source-em-raise 诚实化——恢复 S112 fetch_ok 前提）

S119 修 S118 scan #15 `source-em-swallow-defeats-fetch-ok`（fix_now confirmed_lying）。spec + impl + 4 测试，全量 2445 passed 0 回归（24 deselected newsradar/s032/spec_consistency 既有 flaky/归档债）。

| 项 | 状态 | 说明 |
|---|---|---|
| eastmoney_datacenter raise_on_failure | ✅ 已修 | 加 `raise_on_failure: bool=False` 参数；异常路径 `if raise_on_failure: raise`（re-raise 原异常保 em_get 错误信息），HTTP 成功但 result.data 空仍返 []（合法空不抛）。默认 False 向后兼容，保护 margin_trading/block_trade/lockup_expiry/gstock/fund_flow predict 等 10+ 直调消费者零影响 |
| dragon_tiger_board opt-in | ✅ 已修 | 加 `raise_on_failure=False` 透传 3 内调（DETAILSNEW/BUY/SELL）；risk-trio 两 lambda（risk_models.py:284 `_get_dragon_tiger_risk` + :508 `_calculate_concentration_risk`）传 True |
| seat_engine _pull_records opt-in | ✅ 已修 | `_pull_records` 加 `raise_on_failure=False` 透传；`compute_consensus_signal` 3 调传 True（seat-info 腿）；build_seat_profiles/precompute_daily 用默认 False 不变 |
| S112 fetch_ok 前提恢复 | ✅ | 源端 raise → get_with_fallback_meta fetch_ok=False → risk-trio "missing"（非 ok）。S112 区分源断 vs 未上榜在源端不再被绕过 |

**设计**：opt-in 参数（raise_on_failure 默认 False）而非全局改契约——10+ eastmoney_datacenter 消费者诚实性未扫（critic missed_dim #6），改全局契约 blast radius 大且破既有 `[]` mock 测试。YAGNI：只修 confirmed_lying 的 risk-trio 路径（dragon_tiger 两腿 + seat-info 一腿），其余消费者留下一轮 scan 判。备选 `eastmoney_datacenter_strict` 新函数（同效但 DRY 分叉）与返 `(rows,ok)` 元组（破签名）均否决。

**测试**：4 新测（test_data_honesty.py）mock `eastmoney.em_get` 层走真链——①源断 + raise_on_failure=True → dragon_tiger 抛 → fetch_ok=False → missing；②seat 腿同；③HTTP 成功但 data 空（真未上榜）→ fetch_ok=True → ok（合法路径保留）；④默认 False → 吞 [] 向后兼容。S112 risk-trio 旧测（mock 整个 dragon_tiger_board）全绿无回归。修 test_s008_t13e_misc 2 处严格 mock 签名（`lambda code, look_back=10`→加 `**k`，risk-trio 现传 raise_on_failure=True，严格签名会 TypeError）。

**撒谎总账更新**：26 confirmed_lying = 18 全修（S111/S112/S115 17 + S119 1）+ 8 待修。registry 覆盖 53 不变（S119 修不新增裂缝）。

**下一步候选**：剩 8 confirmed_lying 待修（ai-hithink-rank-empty / ai-tencent-num-zero / market-weekend-calendar-gate 三 HIGH + 5 M/LOW）；或跑 S120 scan round 2 扫 critic 6 漏扫（risk 三子维度承重链为头条 + `or 0` 归零反模式 ~30+ 处）。

**completeness critic 抓 6 漏扫维度（= 新「本轮未覆盖维度」，下一轮 S119 scan 头条）**：
1. ⭐ **risk score 三子维度 provenance 缺口（最 material）**：_calculate_volatility/_calculate_max_drawdown/_calculate_liquidity_risk（risk_models.py:411-474）失败返裸 0.0 + warning 但无 data_status，_merge_data_status（:215）不含三者 → composite risk 可在 3/8 维度静默归零时仍标 ok+LOW。**在仓位决策承重链上**。抽验实锤。
2. `or 0`/`or 0.0` None→zero 强制归零反模式系统性遍布 ~30+ 处（portfolio.py:147 price or 0.0 / bidding_monitor / seat_engine / first_board_filter），S118 只抓 tencent num() 冰山一角。
3. 聚合层顶层 provenance 缺失：StormPrediction（storm_predictor.py:30-38）probability/suggested_position 由含 degraded 因子的加权和算出当权威呈现，无顶层 data_status。
4. 前端渲染层未扫：TrendChart.tsx:103 `typeof r.hit_rate==='number'` 把 0.0 渲染为 "0% 胜率" 非 "数据缺失"（backend→API→React 路径未系统审）。
5. 3 个 AI 工具未审计：query_valuation（full_valuation hithink 备源失败→PS/PCF=None 透传）/query_news（akshare 异常是否被吞成 []）/prediction_short_sector（load_cached 静默）源不可达路径。
6. em_get 消费者吞异常→返空结构全量未扫（eastmoney.py:721-722 concept_blocks `except Exception: return {'total':0,...}` 同型等）。

**下一轮（S119 scan）建议 7 条**：①系统扫 `or 0` 归零反模式全仓 / ②审 risk_models 三子维度 provenance / ③审聚合层顶层 provenance（StormPrediction/composite risk_score/funnel total_score）/ ④审前端渲染层（TrendChart/HonestyBanner/ContextTab/StatsMetrics/WinRateCard）/ ⑤扫剩余 3 AI 工具源不可达路径 / ⑥em_get 消费者吞异常→返空结构全量 / ⑦scheduled_tasks.py 56 个 except 子句 bare except:pass。

## S120 实现后状态（2026-08-31，hithink 三榜源断 raise——AI 出口诚实化）

S120 修 S118 scan #1 `ai-hithink-rank-empty-on-failure`（HIGH confirmed_lying）。spec + impl + 4 测试，全量 2448 passed 0 回归。

| 项 | 状态 | 说明 |
|---|---|---|
| 三榜源断 raise | ✅ 已修 | skyrocket/hot_stock/anomaly_list（hithink_src.py:242/253/261）`if data is None: return []` → `raise RuntimeError("...暂不可达（熔断/离线/API Key 缺失）")`。源断经 stock_tools.query_* → registry.execute 兜成 {"error"} 喂 LLM（诚实，非 `"[]"`）；router market.py:63-92 三端点已 try/except→502（零改动，验毕） |
| 合法空保留 | ✅ | 合法空榜（code==0, item=[]）路径 `_items({"item":[]})`→`[]` 不抛（盘后空诚实保留，与源断 raise 区分） |
| APIKey 轮换前置 | ✅ | 源断 raise 后，APIKey 轮换旧 key 401（非 `_RETRYABLE_HTTP_STATUS`→record_failure→None→raise）不再伪装空榜喂 LLM |

**设计**：raise `RuntimeError`（非 typed 异常）——registry.execute 与 router 均捕 `Exception`，typed 无额外收益。备选返 `{"error":...}` dict（破 `list[dict]` 签名 + LLM 可能当合法 dict）否决。同仓 query_global_stock/worldmonitor_query 失败返 `{"error"}` 是诚实范式，本修复对齐之。

**测试**：test_s104 改 `test_skyrocket_failure_empty`→`test_skyrocket_failure_raises`（None→`pytest.raises(RuntimeError, match="...暂不可达")`）+ 加 skyrocket/hot_stock/anomaly 合法空测试（`{"item":[]}`→`[]` 不抛）。anomaly_list docstring 诚实标注两路径（盘后合法空 `[]` / 源断 raise）。

**撒谎总账更新**：26 confirmed_lying = 19 全修（S111/S112/S115 17 + S119 1 + S120 1）+ 7 待修。registry 覆盖 53 不变（S120 修不新增裂缝）。

**下一步候选**：剩 7 confirmed_lying 待修——2 HIGH（`ai-tencent-num-zero-coercion` tencent.py:58 num() 空→0.0 当真 PE/PB 触 §1.2 不臆造 / `market-emotion-realttime-weekend` market.py:220 周末返周五池当实时）+ 5 M/LOW；或跑 S121 scan round 2 扫 critic 6 漏扫（risk 三子维度承重链头条）。
