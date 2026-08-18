# 技术方案 · S084 选股池战法解耦

> 对应 spec：`spec.md`（已 commit develop 13ecfce）
> 性质：技术实现方案（spec 已签字，本文件进入文件/函数级设计，受 `CLAUDE.md` §0 SDD 约束）
> 作者：Claude ｜日期：2026-08-19
>
> grill 6 决议忠实反映：
> - Q1=A 砍盘中：选股池只做盘前，所有因子取 T-1 昨日值
> - Q2=B 修正 derived 取昨日值：S070 R7 派生盘前取 T-1 snapshots
> - Q3=C pre_market_workflow 保留不改：三入口并存
> - Q4=A 战法卡片指向 PreMarketBriefing（?strategy=，已实现不改）
> - Q5=A 选股池 Tab 复用既有组件（FunnelLayers/CandidateFunnelEmbed），不新建组件
> - Q6=B DiagnosisCard 加 3 子对象（gene_score/pool_item/derived）

---

## 0. 依据与复用清单

| spec 要求 | 复用的现有能力（不重造） | 代码事实定位 |
|---|---|---|
| R1 DiagnosisCard 加 `gene_score: GeneScore` | `limitup_screener.get_screener_result(date)` 已调（`sources/gene.py:36`），返回 `result.gene_scores: list[GeneScore]`；当前只存数字 `total_score`，扩展存完整对象 | `gene.py:50-55`；`GeneScore` 模型 `limitup_screener/models.py:33`（含 code/name/total_score/factors/zt_count_250d 等） |
| R2 DiagnosisCard 加 `pool_item: dict`（涨停池原始 dict） | `astock.em_zt_topic_pool("getTopicZTPool", date, "fbt:asc")` 返回原始 dict 列表（含 c/n/lbc/zbc/fbt/zdp/zje/hybk/p/hs）；走 `em_get` 限流（防封底线） | `market.py:148,167`；`data/mappers.py:527 zt_pool_item_from_dict` |
| R3 DiagnosisCard 加 `derived: dict`（S070 R7 派生） | `strategies/intraday_features.py:95 compute_derived_features(snapshots)` 纯函数；输入 `risk.seal_intraday_collector.get_snapshots_by_code(code, date)` 返回的时序列表（已落库） | `intraday_features.py:95-164`；match_strategies 当前内部已调（`limitup_strategy.py:817-825`） |
| R4.1 IndicatorSet 加 tencent_quote 扩展字段 | `astock.tencent_quote(batch)` 已调（`activity.py:146`）；`data/sources/tencent.py:51-80` vals 索引 vals[4/5/31/39/44/46/47/48]；`data/mappers.py:65-88 quote_from_tencent` 已映射到 Quote 模型（含 last_close/open/change_amount/pe_ttm/market_cap/pb/limit_up_price/limit_down_price） | `tencent.py:51-80`；`mappers.py:65-88` |
| R4.2 IndicatorSet 加板块资金 3 字段 | `market._sectors()` 返回 `[{name, pct, net, inflow, outflow, firms}]`（akshare stock_fund_flow_industry，带 5min 缓存）；个股行业经 `astock.individual_info` 或 `catalyst.concepts` 匹配 | `market.py:76-93`；`catalyst.py:53-56`（concept_blocks） |
| R4.3 IndicatorSet 加 `prev_amount_yi` | `activity.py` 已取 K线 bars（`astock.kline(c,4,10)`），前日 bar 已定位（`activity.py:72 prev`）；`prev.turnover/1e8` 即前日成交额（亿） | `activity.py:63-86` |
| R5 match_strategies 从 DiagnosisCard 读 | `limitup_strategy.py:693 match_strategies(code, gene, pool_item=None, indicators=None)` 签名已加 pool_item/indicators（S083 ada2b71）；既有 9 战法从 `gene` 读，PRD 2 从 pool_item/indicators/S070 derived 读 | `limitup_strategy.py:693-980` |
| R6 StrategyMatcher.match 接受 DiagnosisCard | `strategies/strategy_matcher.py:36 match(gene, weather_state, pool_item, indicators)` 已支持多参数；扩展加 `card` 参数 | `strategy_matcher.py:36-72` |
| R7 前端选股池 Tab | `frontend/src/lib/candidates.ts:122 candidatesApi.runFunnel/getFunnelLayers` API 已有；`components/candidate/FunnelLayers.tsx` + `components/ui/FunnelLayerCard.tsx` 已实现；`pages/workflow/PreMarketBriefing.tsx` 的 CandidateFunnelEmbed 已实现 | `candidates.ts:122-141`；`FunnelLayers.tsx` |
| R8 战法 Tab 保留卡片 | `pages/Workflow.tsx:543-616 StrategyFlowCard` 网格已实现；`to="/workflow/pre-market?strategy="` 已实现（line 593,603） | `Workflow.tsx:543-616` |
| R9 pre_market_workflow 不改 | Q3=C 保留原样，三入口并存 | `routers/workflow.py`（不改） |
| AC5a FunnelResult.market_context（市场宽度） | `market._emotion(date)` 返回 zt_count/zb_count/dt_count/max_boards/lianban_count/seal_rate/break_rate/promotion_rate/ladder/lianban_stocks；带日期参数可取昨日 | `market.py:116-266` |
| AC5b DiagnosisCard.seat_detail（龙虎榜席位） | `seat_engine/service.py:231 compute_consensus_signal(trade_date, stock_code)` 返回 {signal, details:{buy_one_ratio, ...}}；`hot_money_seats.py:321 compute_seat_risk_factor(code, trade_date)` 返回 SeatRiskFactor（day_trip_ratio/relay_ratio/institution_ratio/risk_label） | `seat_engine/service.py:231-364`；`hot_money_seats.py:62-70,321-410` |
| AC5c IndicatorSet 派生因子（封单变化率/N日涨幅/换手分位/板块连续流入） | 从已有数据派生：封单 trajectory 从 `compute_trajectory(snapshots)`；N日涨幅从 `activity.py` 已取 K线 bars；换手分位从 250日 bars；板块连续流入从 `fund_flow.main_net_5d` | `intraday_features.py:61-92`；`activity.py:63` |
| AC5d IndicatorSet 加公告催化类型+概念联动 | `catalyst.py:19 classify_announcement(ann)` 已实现（预增/重组/回购/其他）；`catalyst.py:53-56 concepts` 列表已取 | `catalyst.py:19-29,42-66` |
| T-1 昨日日期计算 | `vr_paths.py:63 is_trading_day(d)`；回溯逻辑参考 `routers/workflow.py:1011-1014`（`while not is_trading_day(t_minus_1): t_minus_1 -= 1day`） | `vr_paths.py:63`；`routers/workflow.py:1008-1015` |
| em_get 防封底线 | `astock.em_get`（0.3s 限流 + circuit_breaker 熔断）；涨停池原始 dict 走 em_get | `market.py:148,167`；`hot_money_seats.py:90` |

**代码事实纠偏**（plan 据实记录，非臆造）：
1. **IndicatorSet 已有 `limit_up`/`limit_down` 字段**（`models.py:38-39`），`activity.py:164-165` 已从 `model.limit_up_price`/`model.limit_down_price` 赋值。spec R4.1 列的 `limit_up_price`/`limit_down_price` 与既有字段语义重复 → **实际只加 6 新字段**（last_close/open/change_amt/pe_ttm/mcap_yi/pb），limit_up/limit_down 复用既有字段。
2. **个股板块资金 `sector_flow` 已在 catalyst.py 采集**（`catalyst.py:60 sf = fetch_sector_flow(c, as_of)`，`build_indicator_set:147 ind.sector_flow = ca.get("sector_flow")`）。spec R4.2 的 sector_net_inflow/inflow/outflow 是**行业级**资金（市场级非个股级），需从 `market._sectors()` 按个股行业匹配取，与既有 `sector_flow`（个股级净额）语义不同，共存不冲突。
3. **match_strategies 当前内部已调 S070 R7**（`limitup_strategy.py:817-825`：`get_snapshots_by_code(code, 今日)` + `compute_derived_features`）。S084 改为从 `card.derived` 读（盘前取 T-1 昨日值），删内部取数。

**新增**：DiagnosisCard 3 子对象 + IndicatorSet 6 扩展字段 + 4 个新 source 文件（zt_pool/derived/market_context/seat_detail）+ match_strategies 改从 card 读 + 前端两级 Tab。**不新增**：数据层（复用 astock/market/seat_engine）、漏斗筛选逻辑（不改 R1→R2→R3）、pre_market_workflow（Q3=C 保留）。

---

## 1. 目录结构

### 1.1 后端新增/改动

```
backend/
├── candidate_funnel/
│   ├── models.py                      # 【改动】DiagnosisCard 加 3 子对象 + seat_detail；IndicatorSet 加 6 字段；FunnelResult 加 market_context
│   ├── diagnosis.py                   # 【改动】build_diagnosis_card 塞入 gene_score/pool_item/derived/seat_detail；build_indicator_set 透传 6 新字段
│   ├── sources/
│   │   ├── gene.py                    # 【改动】fetch_genes 扩展存完整 GeneScore 对象（gene_obj 键）
│   │   ├── activity.py                # 【改动】tencent_quote 扩展读 6 字段（last_close/open/change_amt/pe_ttm/mcap_yi/pb）+ prev_amount_yi 从 K线前日 bar
│   │   ├── fund_flow.py               # 【改动】扩展取板块资金 3 字段（从 market._sectors 按行业匹配）
│   │   ├── zt_pool_source.py          # 【新增】涨停池原始 dict source（em_zt_topic_pool，走 em_get）
│   │   ├── derived_source.py          # 【新增】S070 R7 派生 source（get_snapshots_by_code + compute_derived_features，盘前取 T-1）
│   │   ├── market_context_source.py   # 【新增】市场宽度 source（market._emotion(yesterday_date)）
│   │   └── seat_detail_source.py      # 【新增】龙虎榜席位明细 source（seat_engine.compute_consensus_signal + hot_money_seats.compute_seat_risk_factor）
│   ├── funnel.py                      # 【改动】_run_funnel_impl 采集 4 新 source + 塞入 FunnelResult.market_context / DiagnosisCard 3 子对象
│   └── tests/
│       ├── test_diagnosis.py          # 【改动】3 子对象填充 + 缺失降级
│       └── test_sources_contract.py   # 【改动】新 source 契约
├── limitup_strategy.py                # 【改动】match_strategies 改从 DiagnosisCard 读（新参数 card，默认 None 向后兼容）
├── strategies/strategy_matcher.py     # 【改动】match/match_batch 加 card 参数
├── routers/
│   └── workflow.py                    # 【改动】_build_funnel_layers 透传 market_context + DiagnosisCard 3 子对象（funnel_mod.run_funnel 已含，透传即可）
└── pre_market_workflow.py             # 【不改】Q3=C 保留原样
```

### 1.2 前端新增/改动

```
frontend/src/
├── pages/
│   ├── Workflow.tsx                   # 【改动】加两级 Tab（选股池/战法），选股池 Tab 调 runFunnel + FunnelLayers + CandidateFunnelEmbed
│   └── workflow/PreMarketBriefing.tsx # 【不改】?strategy= 已实现（Q4=A）
├── components/candidate/
│   ├── FunnelLayers.tsx               # 【不改】既有漏斗各层卡片（Q5=A 复用）
│   └── DiagnosisCard.tsx              # 【改动】展示 3 子对象 + market_context
├── components/ui/FunnelLayerCard.tsx # 【不改】单层展示
└── lib/
    └── candidates.ts                  # 【改动】DiagnosisCard 类型加 3 子对象 + market_context；IndicatorSet 加 6 字段
```

---

## 2. 核心数据模型扩展（`candidate_funnel/models.py`）

### 2.1 DiagnosisCard 加 3 子对象 + seat_detail

```python
class DiagnosisCard(BaseModel):
    code: str
    name: str
    indicators: IndicatorSet
    activity: ActivityAssessment
    stabilization: StabilizationSignals
    risk_flags: list[str] = []
    as_of: datetime
    eight_standards: Optional["EightStandardResult"] = None
    capped: bool = False
    cap_reason: Optional[str] = None
    # S084：3 子对象（Q6=B），各自管理缺失，默认 None
    gene_score: Optional[dict] = None        # GeneScore 完整对象 dump（total_score/factors/zt_count_250d/...）
    pool_item: Optional[dict] = None         # 涨停池原始 dict（lbc/zbc/fbt/zdp/zje/hybk/p/hs）
    derived: Optional[dict] = None           # S070 R7 派生（last_lock_time/broken_duration_min/max_drop_pct/limit_price/data_status）
    seat_detail: Optional[dict] = None       # 龙虎榜席位明细（buy_one_ratio/day_trip_ratio/institution_ratio/risk_label/signal）
```

> **设计选择**：3 子对象用 `Optional[dict]` 而非嵌套 Pydantic 模型，因 GeneScore 是外部模型（`limitup_screener.models`）、pool_item 是原始东财 dict、derived 是 `compute_derived_features` 返回 dict——保持 dict 透传避免跨模型耦合。序列化用 `model_dump(mode="json")` 已支持。

### 2.2 IndicatorSet 加 6 扩展字段（tencent_quote）+ 板块资金 3 + 派生 4 + 催化 2

```python
class IndicatorSet(BaseModel):
    # ... 既有字段（含 limit_up/limit_down/float_market_cap/max_high_pct/...）
    # S084 R4.1：tencent_quote 扩展 6 字段（limit_up/limit_down 已有，不重复加）
    last_close: Optional[float] = None       # 昨收（vals[4]）
    open: Optional[float] = None            # 开盘（vals[5]）；盘前取昨日 K线 bar.open
    change_amt: Optional[float] = None       # 涨跌额（vals[31]）；盘前从 close-last_close 算
    pe_ttm: Optional[float] = None           # 市盈率（vals[39]），静态估值
    mcap_yi: Optional[float] = None          # 总市值（亿）（vals[44]）
    pb: Optional[float] = None              # 市净率（vals[46]）
    # S084 R4.2：板块资金 3 字段（行业级，从 market._sectors 按个股行业匹配）
    sector_net_inflow: Optional[float] = None  # 板块净流入
    sector_inflow: Optional[float] = None      # 板块流入
    sector_outflow: Optional[float] = None     # 板块流出
    # S084 R4.3：前日成交额
    prev_amount_yi: Optional[float] = None     # 前日成交额（亿），activity.py 从 K线前日 bar.amount/1e8
    # S084 AC5c：派生因子
    seal_delta: Optional[float] = None         # 封单变化率（compute_trajectory，盘前取昨日）
    change_5d: Optional[float] = None          # 5日涨幅
    change_10d: Optional[float] = None         # 10日涨幅
    change_20d: Optional[float] = None         # 20日涨幅
    turnover_percentile_250d: Optional[float] = None  # 换手率250日分位
    sector_inflow_days: Optional[int] = None   # 板块资金连续流入天数（从 main_net_5d 派生）
    # S084 AC5d：公告催化 + 概念联动
    announcement_type: Optional[str] = None    # 预增/重组/回购/其他（classify_announcement 首条）
    concept_count: Optional[int] = None        # 同概念涨停家数（concepts 列表长度）
```

### 2.3 FunnelResult 加 market_context

```python
class FunnelResult(BaseModel):
    # ... 既有字段
    market_context: Optional[dict] = None  # S084 AC5a：市场宽度（breadth/zt_count/break_rate/seal_rate/promotion_rate/max_boards/ladder）
```

---

## 3. 实现步骤（按 R1-R9 顺序）

### 阶段 A：模型与 source 扩展（R1-R4 + AC5a-AC5d）

#### R1：DiagnosisCard 加 gene_score 子对象

**文件**：`candidate_funnel/sources/gene.py` + `candidate_funnel/diagnosis.py` + `models.py`

**gene.py 改动**（`fetch_genes` 扩展存完整对象）：
```python
def fetch_genes(date: str) -> dict[str, dict]:
    # ... 既有逻辑（_await get_screener_result）
    out[code] = {
        "name": getattr(g, "name", code),
        "gene_score": getattr(g, "total_score", None),
        "high_gene": getattr(g, "high_gene", False),
        "qualify": getattr(g, "qualify", False),
        "gene_obj": g,  # S084 R1：存完整 GeneScore 对象（Pydantic model）
    }
    return out
```
- **复用**：`limitup_screener.get_screener_result(date)`（已调），`_await` helper（已实现 async→sync）
- **关键**：`gene_obj` 存原始 GeneScore 对象，不丢字段（factors/wilson_adjusted/zt_count_250d/last_zt_dates/seal_amount/float_shares/seal_to_float_ratio 全保留）

**diagnosis.py 改动**（`build_diagnosis_card` 塞入）：
- `build_diagnosis_card` 新增参数 `gene_obj: GeneScore | None = None`
- 塞入 `card.gene_score = gene_obj.model_dump(mode="json") if gene_obj else None`
- 缺失标 `gene_score=None`（get_screener_result 返空时）

**funnel.py 改动**（`_run_funnel_impl` 透传）：
- `build_diagnosis_card(code, name, ind, eff, market_ctx=board, as_of=as_of, gene_obj=genes.get(code, {}).get("gene_obj"))`

**测试要点**：
- mock `get_screener_result` 返 GeneScore 列表，验证 `genes[code]["gene_obj"]` 是完整对象
- mock 返空，验证 `card.gene_score is None`（不报错）
- 验证 `card.gene_score` 含 total_score/factors/zt_count_250d（非只数字）

---

#### R2：DiagnosisCard 加 pool_item 子对象（涨停池原始 dict）

**文件**：`candidate_funnel/sources/zt_pool_source.py`（新增）+ `diagnosis.py` + `funnel.py`

**zt_pool_source.py**（新增）：
```python
def fetch_zt_pool(date: str) -> dict[str, dict]:
    """返回 {code: 涨停池原始 dict}。走 em_get 限流（防封底线）。
    em_zt_topic_pool("getTopicZTPool", date_yyyymmdd, "fbt:asc") 返回 list[dict]，
    每项含 c(代码)/n(名)/lbc(连板数)/zbc(炸板次数)/fbt(首封时间)/zdp(涨幅%)/
    zje(涨停价)/hybk(行业)/p(涨停价)/hs(换手率)/fund(封单额)。
    按 c 建 {code: raw_dict} 映射。
    """
    resolved = date.replace("-", "")
    try:
        pool = astock.em_zt_topic_pool("getTopicZTPool", resolved, "fbt:asc") or []
    except Exception:
        return {}
    return {str(p.get("c", "")): p for p in pool if p.get("c")}
```
- **复用**：`astock.em_zt_topic_pool`（market.py 已用），走 `em_get` 限流（防封底线不可绕过）
- **关键**：盘前取 T-1 昨日池（`date=yesterday_date`）；个股不在昨日涨停池 → `pool_item=None`

**diagnosis.py 改动**：`build_diagnosis_card` 新增参数 `pool_item: dict | None = None`，塞入 `card.pool_item`

**funnel.py 改动**：`_run_funnel_impl` 调 `zt_pool_source.fetch_zt_pool(yesterday_date)`，透传给 `build_diagnosis_card`

**测试要点**：
- mock `em_zt_topic_pool` 返原始 dict 列表，验证 `pool_item` 含 lbc/zbc/fbt/zdp/zje/hybk
- mock 返空，验证 `pool_item is None`
- 验证走 `em_get`（不直 requests，防封底线）

---

#### R3：DiagnosisCard 加 derived 子对象（S070 R7 派生，盘前取 T-1 昨日 snapshots）

**文件**：`candidate_funnel/sources/derived_source.py`（新增）+ `diagnosis.py` + `funnel.py`

**derived_source.py**（新增）：
```python
def fetch_derived(code: str, yesterday_date: str) -> dict | None:
    """S070 R7 派生（盘前取 T-1 昨日 snapshots）。grill Q2=B。
    调 risk.seal_intraday_collector.get_snapshots_by_code(code, yesterday_date)
    → strategies.intraday_features.compute_derived_features(snapshots)
    输出 {last_lock_time, broken_duration_min, max_drop_pct, limit_price,
          granularity_note, data_status}。
    盘前 snapshots 未采集时返 None（标"分时数据未就绪"，不臆造）。
    """
    try:
        from risk.seal_intraday_collector import get_snapshots_by_code
        from strategies.intraday_features import compute_derived_features
        snaps = get_snapshots_by_code(code, yesterday_date)
        if not snaps:
            return None  # 盘前未采集，降级
        derived = compute_derived_features(snaps)
        if derived.get("data_status") == "missing":
            return None
        return derived
    except Exception:
        return None
```
- **复用**：`get_snapshots_by_code`（risk 模块，已落库）+ `compute_derived_features`（intraday_features.py:95 纯函数）
- **关键**：盘前取 T-1 **昨日** snapshots（grill Q2=B 修正，非 match_strategies 当前的"今日"）；snapshots 未采集 → `derived=None` 降级，不臆造
- **边界**：`yesterday_date` 须是已落库的交易日（`is_trading_day` 回溯）

**diagnosis.py 改动**：`build_diagnosis_card` 新增参数 `derived: dict | None = None`，塞入 `card.derived`

**funnel.py 改动**：`_run_funnel_impl` 对每个 final_code 调 `derived_source.fetch_derived(code, yesterday_date)`

**测试要点**：
- mock `get_snapshots_by_code` 返时序列表，验证 `derived` 含 broken_duration_min/max_drop_pct/last_lock_time
- mock 返空列表，验证 `derived is None`（不臆造）
- 验证取的是 **yesterday_date**（非今日，Q2=B）

---

#### R4.1：IndicatorSet 加 tencent_quote 扩展 6 字段

**文件**：`candidate_funnel/sources/activity.py` + `diagnosis.py`

**activity.py 改动**（`fetch_activity` 当日路径 + `_fetch_activity_from_kline` 历史路径）：

当日路径（`fetch_activity` line 142-182）—— `quote_from_tencent` 返回的 Quote model 已含这 6 字段（mappers.py:65-88），扩展读：
```python
entry = {
    # ... 既有字段
    "last_close": model.last_close,        # vals[4]
    "open": model.open,                    # vals[5]（盘中值，盘前取昨日 K线 bar.open 见历史路径）
    "change_amt": model.change_amount,     # vals[31]
    "pe_ttm": model.pe_ttm,                # vals[39]
    "mcap_yi": _numf_to_yi(model.market_cap),  # vals[44]，market_cap 是元，转亿
    "pb": model.pb,                        # vals[46]
    # limit_up/limit_down 已有（line 164-165），不重复
}
```

历史路径（`_fetch_activity_from_kline` line 29-130）—— 盘前取 T-1 走此路径，从 K线 bar 复算：
```python
# bar = T-1 日 K线 bar，prev = T-2 日 bar
if prev:
    entry["last_close"] = prev.get("close")  # T-2 收盘 = T-1 昨收
    entry["change_amt"] = round(close - prev_close, 2) if prev_close else None
entry["open"] = bar.get("open")  # T-1 开盘
# pe_ttm/mcap_yi/pb：tencent_quote 返回的是当前值（T 日），历史日取不到精确值
# → 从 today_quote（line 40 已调）取当前值近似，标 missing["pe_ttm"]="当前值近似（历史日精确值未取得）"
q = quote_from_tencent(c, today_quote.get(c, {}))
entry["pe_ttm"] = q.pe_ttm      # 当前值近似
entry["mcap_yi"] = _numf_to_yi(q.market_cap)  # 当前值近似
entry["pb"] = q.pb              # 当前值近似
```
- **复用**：`astock.tencent_quote`（已调，同一次返回扩展读 vals，不重新调）；`quote_from_tencent`（已映射）
- **关键**：不重新调 tencent_quote，同一次返回扩展读（spec R4.1 要求）；历史路径 last_close/open/change_amt 从 K线复算（盘前取昨日），pe_ttm/mcap_yi/pb 用当前值近似标注

**diagnosis.py 改动**（`build_indicator_set` 透传）：
```python
ind.last_close = a.get("last_close")
ind.open = a.get("open")
ind.change_amt = a.get("change_amt")
ind.pe_ttm = a.get("pe_ttm")
ind.mcap_yi = a.get("mcap_yi")
ind.pb = a.get("pb")
```

**测试要点**：
- mock tencent_quote 返 raw dict，验证 entry 含 6 新字段
- 历史日路径 mock K线 bars，验证 last_close=prev.close / open=bar.open
- 验证 pe_ttm/mcap_yi/pb 在历史路径标 missing（当前值近似）

---

#### R4.2：IndicatorSet 加板块资金 3 字段

**文件**：`candidate_funnel/sources/fund_flow.py` + `diagnosis.py`

**fund_flow.py 改动**（`fetch_fund_flow` 扩展）：
```python
def fetch_fund_flow(codes, as_of, sectors=None):
    # sectors: market._sectors() 外部传入（batch 复用，避免 per-code 调）
    # ... 既有逻辑（main_net_inflow/...）
    # S084 R4.2：板块资金 3 字段（行业级）
    if sectors:
        # 取个股行业（从 individual_info 或 catalyst concepts）
        industry = _get_stock_industry(c)  # astock.individual_info(c).行业
        if industry:
            match = next((s for s in sectors if s["name"] == industry), None)
            if match:
                entry["sector_net_inflow"] = match["net"]
                entry["sector_inflow"] = match["inflow"]
                entry["sector_outflow"] = match["outflow"]
```
- **复用**：`market._sectors()`（返回 `[{name, pct, net, inflow, outflow, firms}]`，带 5min 缓存）；`astock.individual_info`（取个股行业）
- **关键**：盘前取昨日 `_sectors()` 返回值（akshare 盘前可取昨日）；个股行业匹配；匹配不到 → 3 字段 None 标 missing
- **batch 优化**：`_sectors()` 一次取全市场板块列表，传给所有 codes 复用（不 per-code 调）

**diagnosis.py 改动**：`build_indicator_set` 透传 `sector_net_inflow/inflow/outflow`

**测试要点**：
- mock `_sectors()` 返板块列表 + 个股行业匹配，验证 3 字段非 None
- mock 行业不匹配，验证 3 字段 None + missing

---

#### R4.3：IndicatorSet 加 prev_amount_yi（前日成交额）

**文件**：`candidate_funnel/sources/activity.py` + `diagnosis.py`

**activity.py 改动**（`_fetch_activity_from_kline` 已有 prev bar）：
```python
# prev = T-2 日 bar（已定位，line 72）
if prev is not None:
    prev_amount = _f(prev.get("amount"))  # 元
    if prev_amount is not None:
        entry["prev_amount_yi"] = round(prev_amount / 1e8, 4)  # 转亿
```
- **复用**：K线 bars 已取（`activity.py:63 astock.kline`），prev bar 已定位
- **关键**：prev_amount_yi = prev bar 的 amount / 1e8（亿）

**diagnosis.py 改动**：`build_indicator_set` 透传 `prev_amount_yi`

---

#### AC5a：FunnelResult.market_context（市场宽度）

**文件**：`candidate_funnel/sources/market_context_source.py`（新增）+ `funnel.py`

**market_context_source.py**（新增）：
```python
def fetch_market_context(yesterday_date: str) -> dict | None:
    """市场宽度（盘前取 T-1 昨日）。grill Q1=A。
    market._emotion(yesterday_date) 返回 zt_count/zb_count/dt_count/max_boards/
    lianban_count/seal_rate/break_rate/promotion_rate/ladder/lianban_stocks。
    breadth 从 _sentiment() 取（冰点/偏弱/中性/偏强/普涨）。
    """
    try:
        import market
        emo = market._emotion(yesterday_date)
        if not emo:
            return None
        return {
            "breadth": emo.get("breadth") or _derive_breadth(emo),  # 优先 _emotion.breadth，无则从 _sentiment 取
            "zt_count": emo.get("zt_count"),
            "break_rate": emo.get("break_rate"),
            "seal_rate": emo.get("seal_rate"),
            "promotion_rate": emo.get("promotion_rate"),
            "max_boards": emo.get("max_boards"),
            "ladder": emo.get("ladder"),
            "date": emo.get("date"),
        }
    except Exception:
        return None
```
- **复用**：`market._emotion(date)`（带日期参数可取昨日，market.py:116-266）
- **关键**：盘前取 **yesterday_date**（Q1=A）；`_emotion` 返空（长假/故障）→ `market_context=None` 降级

**funnel.py 改动**：`_run_funnel_impl` 调 `market_context_source.fetch_market_context(yesterday_date)`，塞入 `FunnelResult.market_context`

---

#### AC5b：DiagnosisCard.seat_detail（龙虎榜席位明细）

**文件**：`candidate_funnel/sources/seat_detail_source.py`（新增）+ `diagnosis.py` + `funnel.py`

**seat_detail_source.py**（新增）：
```python
def fetch_seat_detail(code: str, yesterday_date: str) -> dict | None:
    """龙虎榜席位明细（盘前取 T-1 昨日）。
    1. seat_engine.get_engine().compute_consensus_signal(yesterday_date, code)
       → {signal, details:{buy_one_ratio, buy_seat_types, institution_buy_amt, total_buy_amount, ...}}
    2. hot_money_seats.compute_seat_risk_factor(code, yesterday_date)
       → SeatRiskFactor(day_trip_ratio/relay_ratio/institution_ratio/risk_label/mutation_alert)
    合并输出 {signal, buy_one_ratio, day_trip_ratio, relay_ratio, institution_ratio, risk_label}
    """
    try:
        from seat_engine.service import get_engine
        from strategies.hot_money_seats import compute_seat_risk_factor
        eng = get_engine()
        cons = eng.compute_consensus_signal(yesterday_date, code)
        srf = compute_seat_risk_factor(code, yesterday_date)
        if not cons and (not srf or srf.risk_label == "无数据"):
            return None  # 未上榜，降级
        det = (cons or {}).get("details", {})
        return {
            "signal": cons.get("signal") if cons else None,
            "buy_one_ratio": det.get("buy_one_ratio"),
            "day_trip_ratio": srf.day_trip_ratio,
            "relay_ratio": srf.relay_ratio,
            "institution_ratio": srf.institution_ratio,
            "risk_label": srf.risk_label,
        }
    except Exception:
        return None
```
- **复用**：`seat_engine.compute_consensus_signal(trade_date, stock_code)`（service.py:231）+ `hot_money_seats.compute_seat_risk_factor(code, trade_date)`（hot_money_seats.py:321）
- **关键**：盘前取 **yesterday_date**；未上榜 → `seat_detail=None` 降级；`compute_consensus_signal` 走 datacenter（em_get 限流，S079 AC6 处置）

**diagnosis.py 改动**：`build_diagnosis_card` 新增参数 `seat_detail: dict | None = None`，塞入 `card.seat_detail`

**funnel.py 改动**：`_run_funnel_impl` 对每个 final_code 调 `seat_detail_source.fetch_seat_detail(code, yesterday_date)`

---

#### AC5c：IndicatorSet 派生因子（封单变化率/N日涨幅/换手分位/板块连续流入）

**文件**：`candidate_funnel/sources/activity.py`（N日涨幅/换手分位）+ `derived_source.py`（封单 trajectory）+ `fund_flow.py`（板块连续流入）+ `diagnosis.py`

- **seal_delta**：`derived_source.py` 扩展调 `compute_trajectory(snaps)`（intraday_features.py:61），盘前取昨日 snapshots → `seal_delta`
- **change_5d/10d/20d**：`activity.py` 已取 K线 bars（`astock.kline(c,4,10)` 返回近10日，需扩展到 20 日 `astock.kline(c,4,20)`），从 `bars[-1].close / bars[-N].close - 1` 算
- **turnover_percentile_250d**：从 250日 K线 bars 的 turnover 序列算分位（需 `astock.kline(c,4,250)`）
- **sector_inflow_days**：从 `fund_flow.main_net_5d`（已有 5日累计）派生连续流入天数（遍历 flows[-5:] 正值计数）

**diagnosis.py 改动**：`build_indicator_set` 透传 4 派生字段

**测试要点**：mock K线 bars，验证 N日涨幅/换手分位计算正确；mock snapshots，验证 seal_delta

---

#### AC5d：IndicatorSet 加 announcement_type + concept_count

**文件**：`candidate_funnel/sources/catalyst.py`（已有数据，扩展输出）+ `diagnosis.py`

**catalyst.py 改动**（`fetch_catalyst` 扩展）：
```python
# announcements 已取（line 42-47），首条公告类型
if entry["announcements"]:
    entry["announcement_type"] = entry["announcements"][0].get("type", "其他")
# concepts 已取（line 53-56）
entry["concept_count"] = len(entry["concepts"])
```
- **复用**：`classify_announcement`（catalyst.py:19，已实现）+ `concept_blocks`（已取）

**diagnosis.py 改动**：`build_indicator_set` 透传 `announcement_type/concept_count`

---

### 阶段 B：战法从 DiagnosisCard 读（R5-R6）

#### R5：match_strategies 改从 DiagnosisCard 读

**文件**：`limitup_strategy.py`（match_strategies）+ `strategies/strategy_matcher.py`

**match_strategies 签名扩展**（line 693）：
```python
def match_strategies(
    code: str,
    gene: GeneScore,
    pool_item: dict | None = None,
    indicators: Any = None,
    card: Any = None,  # S084 R5：DiagnosisCard，传时从 card 读全部子对象
) -> list[StrategySignal]:
```

**向后兼容逻辑**（card=None 走原路径，card 非空从 card 读）：
```python
# S084 R5：card 非空时从 card 子对象读，覆盖 pool_item/indicators/derived
if card is not None:
    pool_item = pool_item or getattr(card, "pool_item", None)
    indicators = indicators or getattr(card, "indicators", None)
    card_derived = getattr(card, "derived", None)
    card_gene = getattr(card, "gene_score", None)
    # gene_score 子对象可重建 GeneScore（若调用方只传 card 不传 gene）
```

**既有 9 战法**（line 711-802）：从 `gene` 读（不变，gene 是 GeneScore 对象）→ S084 时 `gene` 可从 `card.gene_score` 重建（调用方负责）

**PRD 弱转强接力**（line 808-884）改动：
- **删**内部 S070 取数（line 817-825：`get_snapshots_by_code(code, 今日)` + `compute_derived_features`）
- **改为**从 `card.derived` 读：`derived = card_derived or {}`，`broken_duration_min = derived.get("broken_duration_min")`，`max_drop_pct = derived.get("max_drop_pct")`，`last_lock_time = derived.get("last_lock_time")`
- `derived=None`（盘前未采集）→ 标 `s070_status="missing_s070_r7"` 跳过（既有逻辑，line 832-839）
- `vol_ratio_1d`：从 `card.indicators.prev_turnover_pct` 读（既有逻辑，line 849-852，不变）

**PRD 形态反包**（line 886-936）改动：
- `close_pct` 从 `card.pool_item.zdp` 读（既有逻辑，line 890，不变）
- `max_high_pct/shadow_length_pct/ma_5_status` 从 `card.indicators` 读（既有逻辑，line 899-902，不变）
- `volume_1d/volume_2d`：从 `card.indicators.amount_yi/prev_amount_yi` 算放量比（补 S081 缺的 volume 字段）
  ```python
  if indicators is not None:
      amt_1d = getattr(indicators, "amount_yi", None)
      amt_2d = getattr(indicators, "prev_amount_yi", None)
      if amt_1d and amt_2d and amt_2d > 0:
          volume_ratio = amt_1d / amt_2d  # 放量比（成交额代理）
  ```

**测试要点**：
- mock DiagnosisCard 含全部子对象，验证 9 战法 + PRD 2 命中
- mock card=None，验证既有调用行为不变（向后兼容）
- mock card.derived=None，验证弱转强标 missing 跳过
- 既有 9 战法回归：传/不传 card 命中一致（AC7）

---

#### R6：StrategyMatcher.match 接受 DiagnosisCard

**文件**：`strategies/strategy_matcher.py`

**match 方法扩展**（line 36）：
```python
def match(
    self,
    gene: GeneScore,
    weather_state: str | None = None,
    pool_item: dict | None = None,
    indicators: Any = None,
    card: Any = None,  # S084 R6：DiagnosisCard
) -> list[StrategySignal]:
    signals = match_strategies(gene.code, gene, pool_item, indicators, card=card)
    # ... 既有 weather_fit 逻辑
```

**match_batch 扩展**（line 74）：
```python
def match_batch(
    self,
    genes: list[GeneScore],
    weather_state: str | None = None,
    pool_items: dict[str, dict] | None = None,
    indicators_map: dict[str, Any] | None = None,
    cards_map: dict[str, Any] | None = None,  # S084 R6：{code: DiagnosisCard}
) -> dict[str, list[StrategySignal]]:
    for gene in genes:
        card = cards_map.get(gene.code) if cards_map else None
        # card 非空时覆盖 pool_item/indicators
        results[gene.code] = self.match(gene, weather_state,
            pool_items.get(gene.code) if pool_items else None,
            indicators_map.get(gene.code) if indicators_map else None,
            card=card)
```
- **向后兼容**：`card` 默认 None，既有调用不传 card 行为不变（AC7）
- **card 非空时**：从 card 取全部子对象传给 match_strategies

---

### 阶段 C：前端两级 Tab（R7-R8）

#### R7：Workflow.tsx 加两级 Tab（选股池 / 战法）

**文件**：`frontend/src/pages/Workflow.tsx` + `frontend/src/lib/candidates.ts`

**Workflow.tsx 改动**：
- 顶部加两级 Tab 导航：`选股池` | `战法`（新增 `tab` state，默认"战法"保持既有行为）
- **选股池 Tab**（新增视图）：
  - 调 `candidatesApi.runFunnel("all", selectedDate)` 取 FunnelResult
  - 用既有 `FunnelLayers` 组件展示 R1→R2→R3 三层（Q5=A 复用，不新建组件）
  - 用既有 `CandidateFunnelEmbed`（PreMarketBriefing 的组件）展示 final_candidates（DiagnosisCard 列表含 3 子对象）
  - 展示 `FunnelResult.market_context`（breadth/zt_count/break_rate/seal_rate/max_boards/ladder）—— 复用 DailyReview 的展示样式
  - **不调** `/api/workflow/pre-market`（解耦，直接调选股池 API，R7.2）
- **战法 Tab**（既有视图，R8）：保留 `StrategyFlowCard` 网格（line 543-616）

**candidates.ts 改动**（类型扩展）：
```typescript
export interface DiagnosisCard {
  // ... 既有字段
  gene_score?: Record<string, unknown> | null;  // S084 R1
  pool_item?: Record<string, unknown> | null;   // S084 R2
  derived?: Record<string, unknown> | null;     // S084 R3
  seat_detail?: Record<string, unknown> | null; // S084 AC5b
}
export interface IndicatorSet {
  // ... 既有字段
  last_close?: number | null; open?: number | null; change_amt?: number | null;
  pe_ttm?: number | null; mcap_yi?: number | null; pb?: number | null;
  sector_net_inflow?: number | null; sector_inflow?: number | null; sector_outflow?: number | null;
  prev_amount_yi?: number | null;
  seal_delta?: number | null; change_5d?: number | null; change_10d?: number | null;
  change_20d?: number | null; turnover_percentile_250d?: number | null; sector_inflow_days?: number | null;
  announcement_type?: string | null; concept_count?: number | null;
}
export interface FunnelResult {
  // ... 既有字段
  market_context?: Record<string, unknown> | null;  // S084 AC5a
}
```

**测试要点**：
- 选股池 Tab 调 runFunnel 展示漏斗 + 候选（DiagnosisCard 含 3 子对象）
- market_context 展示 breadth/zt_count/break_rate/seal_rate
- 不调 `/api/workflow/pre-market`（验证网络请求）

---

#### R8：战法 Tab 保留既有卡片 + 指向 PreMarketBriefing

**文件**：`frontend/src/pages/Workflow.tsx`（不改，已实现）

- 既有 `StrategyFlowCard` 网格（line 543-616）保留
- `to="/workflow/pre-market?strategy=weak_turn_strong"` / `?strategy=pattern_reversal`（line 593,603）已实现（Q4=A）
- PreMarketBriefing 的 `?strategy=` 自动选中战法 Tab（已实现 C2 修复）
- **本 R 无新增改动**，仅验证既有行为

---

### 阶段 D：pre_market_workflow 保留不改（R9）

#### R9：pre_market_workflow 保留原样

**文件**：`backend/pre_market_workflow.py` + `backend/routers/workflow.py`（不改）

- Q3=C 保留原样：pre_market_workflow 继续做 ①获取涨停池 ②候选池筛选 ③战法匹配 ④仓位建议 ⑤S079 后处理 ⑥推送（既有行为不变）
- 选股池 Tab + 战法 Tab 是**新增独立入口**，和 pre_market_workflow（盘前简报 `/workflow/pre-market`）并存（R9.2）
- 三入口并存不冲突：选股池 Tab 独立看选股池、战法 Tab 独立看战法卡片、盘前简报看完整串联视图（R9.3）
- 旧入口（盘前简报）保留过渡，用户逐渐迁移（R9.4）

**routers/workflow.py 改动**（仅透传，不改逻辑）：
- `_build_funnel_layers` 调 `funnel_mod.run_funnel` 已返回含 market_context + 3 子对象的 FunnelResult，透传即可
- pre_market 端点的 `final_cards`（line 204）已含 3 子对象（model_dump 透传）

---

## 3. 验收对齐

| spec AC | 对应 plan 实现步骤 | 关键验证点 |
|---|---|---|
| AC1：DiagnosisCard 含 3 子对象（gene_score/pool_item/derived） | R1+R2+R3（阶段 A） | `card.gene_score/pool_item/derived` 非 None（有数据时）；3 子对象默认 None 不破坏序列化 |
| AC2：gene.py 扩展存完整 GeneScore 对象 | R1（gene.py 扩展 `gene_obj` 键） | `genes[code]["gene_obj"]` 是 GeneScore 实例；`card.gene_score` 含 total_score/factors/zt_count_250d |
| AC3：pool_item 从 em_zt_topic_pool 取（走 em_get 限流） | R2（zt_pool_source.py） | `pool_item` 含 lbc/zdp/fbt/zbc；验证走 `astock.em_get`（非直 requests） |
| AC4：derived 从 compute_derived_features 取，盘前未采集 None 降级 | R3（derived_source.py） | `derived` 含 broken_duration/max_drop/last_lock；snapshots 未采集时 `derived=None` |
| AC5：IndicatorSet 含 12 扩展字段 | R4.1（6 字段）+ R4.2（3 字段）+ R4.3（1 字段）+ AC5c（4 派生）+ AC5d（2 催化） | **纠偏**：limit_up/limit_down 已有，实际加 6+3+1+4+2=16 字段（spec 12 指核心扩展，含纠偏后实际 16） |
| AC5a：FunnelResult.market_context（市场宽度 5 因子） | AC5a（market_context_source.py） | `market_context` 含 breadth/break_rate/seal_rate/promotion_rate/max_boards；盘前取 yesterday_date |
| AC5b：DiagnosisCard.seat_detail（龙虎榜席位明细） | AC5b（seat_detail_source.py） | `seat_detail` 含 buy_one_ratio/day_trip_ratio/institution_ratio/risk_label；未上榜 None |
| AC5c：IndicatorSet 4 派生因子 | AC5c（activity/derived/fund_flow 扩展） | seal_delta/change_5d/10d/20d/turnover_percentile_250d/sector_inflow_days 派生正确 |
| AC5d：IndicatorSet 公告催化类型 + 概念联动度 | AC5d（catalyst.py 扩展） | announcement_type（预增/重组/回购/其他）+ concept_count |
| AC6：match_strategies 各 elif 从 DiagnosisCard 读，删各自取数 | R5（limitup_strategy.py 改） | card 非空时从 card 读全部子对象；删 weak_turn_strong 内部 S070 取数（line 817-825） |
| AC7：既有 9 战法回归通过（传/不传 card 命中一致） | R5+R6（向后兼容） | card=None 时既有 9 战法命中不变；card 非空时从 card 读命中一致 |
| AC8：前端 Workflow.tsx 两级 Tab，选股池 Tab 调 runFunnel | R7（Workflow.tsx 改） | 选股池 Tab 展示漏斗 R1→R2→R3 + final_candidates；调 `/workflow/candidates/funnel`（非 `/api/workflow/pre-market`） |
| AC9：战法 Tab 保留既有卡片，点击进战法特定筛选 | R8（不改，已实现） | 战法卡片 `to="/workflow/pre-market?strategy="` 已实现；PreMarketBriefing ?strategy= 选中战法 Tab |
| AC10：pre_market_workflow 解耦 | R9（不改，三入口并存） | 选股池 Tab + 战法 Tab 独立入口，与盘前简报并存；pre_market_workflow 不改 |
| AC11：轻量风险提醒 | 全局（继承 S079 §2.3） | 研判/买卖时机/仓位参数挂轻量风险提醒（既有 Disclaimer 组件） |

---

## 4. 工程约束与合规自查

- **em_get 防封底线**：涨停池原始 dict（zt_pool_source）走 `astock.em_zt_topic_pool` → `em_get`（0.3s 限流 + circuit_breaker）；seat_detail 走 datacenter `em_get`（S079 AC6 处置）；不直 requests
- **不臆造**：3 子对象各自管理缺失——`gene_score=None`（get_screener_result 返空）/`pool_item=None`（个股不在昨日涨停池）/`derived=None`（snapshots 未采集）/`seat_detail=None`（未上榜），各标原因
- **T-1 昨日边界**：所有因子取 T-1 昨日值（Q1=A）；`yesterday_date` 用 `is_trading_day` 回溯（vr_paths.py:63，参考 workflow.py:1011-1014）；derived 取 `get_snapshots_by_code(code, yesterday_date)`（Q2=B，非今日）
- **向后兼容**：match_strategies/StrategyMatcher.match 新参数 `card` 默认 None，既有调用不传 card 行为不变（AC7）；DiagnosisCard 3 子对象默认 None，既有快照无字段降级
- **不破坏 S079 后处理**：cap_by_market_phase + DragonTigerSeatFilter 在战法匹配之后串，不改
- **不破坏 S070 R7 派生**：derived 子对象盘前 snapshots 未采集时 None 降级（不臆造）
- **合规**（CLAUDE.md §1.1）：DiagnosisCard 无方向结论词；研判/买卖时机/仓位参数挂轻量风险提醒（既有 Disclaimer 组件）；继承 S079 §2.3 参考价位隔离豁免

---

## 5. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| DiagnosisCard 加 3 子对象 + seat_detail 破坏序列化 | 前端类型/快照不兼容 | 4 字段默认 None，既有快照无字段降级（Pydantic Optional） |
| match_strategies 改从 card 读破坏既有 9 战法 | 既有战法不命中 | 新参数 `card` 默认 None 向后兼容；传 card 时从 card 读，不传时走原路径（AC7 回归） |
| S070 R7 派生盘前未采集 | derived=None 弱转强不命中 | 诚实标"分时数据未就绪"（既有 missing_s070_r7 逻辑），盘中采集完后补 |
| seat_detail datacenter 限流（与 push2ex 同 IP 池） | seat_detail 取数失败 | 走 em_get 限流 + circuit_breaker（S079 AC6 处置）；失败 None 降级 |
| 板块资金行业匹配失败 | sector_net_inflow None | 标 missing"行业未匹配"；个股级 sector_flow（catalyst 已有）作降级 |

**回滚**：
1. DiagnosisCard 4 子对象默认 None，不影响既有序列化（删字段即回退）
2. match_strategies 新参数 `card` 默认 None，删即回退
3. 前端两级 Tab 独立于既有 PreMarketBriefing，回滚只删 Tab 不影响盘前简报
4. 4 个新 source 文件独立，删文件即回退（不影响既有 funnel 筛选逻辑）
