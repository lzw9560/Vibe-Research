# 任务拆分 · S084 选股池战法解耦

> 对应：`spec.md`（AC1-AC11，AC5a-d 已移 backlog）+ `plan.md`（技术方案，598 行，含 Oracle B2/B3/B4/H1 修订）
> 粒度：原子任务（独立可验，1-2h/条）。每条含：依赖、改动文件、验收方式、映射 AC。
> 规则：每条完成即跑对应单测/验收；数据走 `astock.em_get`（防封底线）；不臆造缺失数据；match_strategies card=None 保留 fallback（B2）；AC5a-d 不在 tasks 范围（移 backlog）。

---

## 阶段 A · 模型与 source 扩展（R1-R4，AC1-AC5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | `DiagnosisCard` 加 `gene_score: Optional[dict]=None` 字段（Q6=B，3 子对象之一） | — | `backend/candidate_funnel/models.py` | 实例化 `DiagnosisCard(gene_score=None)` 不报错；`model_dump` 含字段；映射 AC1 |
| A2 | `DiagnosisCard` 加 `pool_item: Optional[dict]=None` 字段（涨停池原始 dict 占位） | A1 | `backend/candidate_funnel/models.py` | 同 A1 验收；映射 AC1 |
| A3 | `DiagnosisCard` 加 `derived: Optional[dict]=None` 字段（S070 R7 派生占位） | A2 | `backend/candidate_funnel/models.py` | 同 A1 验收；映射 AC1 |
| A4 | `IndicatorSet` 加 6 扩展字段（last_close/open/change_amt/pe_ttm/mcap_yi/pb）。**注**：limit_up/limit_down 复用既有字段不新增（plan §0 纠偏第1条）；按字段注释标明取数路径分历史日 kline 复算 vs tencent_quote 当日（B4） | A3 | `backend/candidate_funnel/models.py` | 实例化各字段默认 None 不报错；映射 AC5 |
| A5 | `IndicatorSet` 加板块资金 3 字段（sector_net_inflow/sector_inflow/sector_outflow，行业级）+ prev_amount_yi（前日成交额） | A4 | `backend/candidate_funnel/models.py` | 同 A4 验收；映射 AC5 |
| A6 | `sources/gene.py` `fetch_genes` 扩展：`genes[code]` 加 `gene_obj` 键存完整 GeneScore 对象（不只存 total_score 数字） | A1 | `backend/candidate_funnel/sources/gene.py` | mock `get_screener_result` 返 GeneScore 列表，验证 `genes[code]["gene_obj"]` 是 GeneScore 实例；mock 返空验证无 `gene_obj` 键不报错；映射 AC2 |
| A7 | 新建 `sources/zt_pool_source.py`：`fetch_zt_pool_map(date) -> dict[str,dict]` 从涨停池原始 dict 建 {code: raw_dict} 映射。**复用** `strategies/first_board_filter.fetch_zt_pool(date)`（已实现，走 em_get 限流 + 24h 缓存，返回 list[dict]），按 c(代码) 建 dict 映射 | A2 | `backend/candidate_funnel/sources/zt_pool_source.py` | mock `fetch_zt_pool` 返原始 dict 列表，验证映射 key=code、value 含 lbc/zbc/fbt/zdp/zje/hybk/p/hs；验证走 `fetch_zt_pool`（非直 requests，em_get 防封底线）；映射 AC3 |
| A8 | 新建 `sources/derived_source.py`：`fetch_derived(code, yesterday_date) -> dict|None` 调 `compute_derived_features(get_snapshots_by_code(code, yesterday_date))` 取 T-1 昨日派生（Q2=B，非今日）。snapshots 未采集返 None 降级，不臆造 | A3 | `backend/candidate_funnel/sources/derived_source.py` | mock `get_snapshots_by_code` 返时序列表，验证 derived 含 broken_duration_min/max_drop_pct/last_lock_time；mock 返空列表验证 `derived is None`；验证取 yesterday_date（非今日）；映射 AC4 |
| A9 | `sources/activity.py` 扩展按历史日路径分字段取数（B4）：路径1 kline prev_bar 复算 open/last_close/change_amt（`_fetch_activity_from_kline` 已有 bar+prev）；路径2 tencent_quote 当日取 pe_ttm/mcap_yi/pb（标 missing"当前值非T-1"，复用 line 40 已调的 today_quote 不重新调）；路径3 limit_up/limit_down 复用既有字段不新增 | A4 | `backend/candidate_funnel/sources/activity.py` | 历史日路径 mock K线 bars，验证 last_close=prev.close / open=bar.open / change_amt=close-prev_close；验证 pe_ttm/mcap_yi/pb 标 missing"当前值非T-1"；验证 limit_up/limit_down 未新增字段；映射 AC5 |
| A10 | `sources/fund_flow.py` `fetch_fund_flow` 扩展：加 `sectors` 参数（batch 复用），从 `market._sectors()` 返板块列表按个股行业匹配取 sector_net_inflow/inflow/outflow 3 字段。匹配不到 3 字段 None + missing | A5 | `backend/candidate_funnel/sources/fund_flow.py` | mock `market._sectors()` 返板块列表 + 个股行业匹配，验证 3 字段非 None；mock 行业不匹配验证 3 字段 None + missing；映射 AC5 |
| A11 | `sources/activity.py` 扩展算 `prev_amount_yi`：`_fetch_activity_from_kline` 已有 prev bar（line 72），`prev_amount_yi = prev.amount/1e8`（亿） | A5 | `backend/candidate_funnel/sources/activity.py` | mock K线 bars，验证 prev_amount_yi = prev bar amount/1e8；prev 缺失验证 None；映射 AC5 |
| A12 | `diagnosis.py` `build_diagnosis_card` 扩展：加 `gene_obj/pool_item/derived` 参数，塞入 `card.gene_score`（`gene_obj.model_dump(mode="json")`）/`card.pool_item`/`card.derived`。缺失各标 None + 原因 | A1,A2,A3,A6,A7,A8 | `backend/candidate_funnel/diagnosis.py` | mock 3 子对象非空，验证 card.gene_score/pool_item/derived 非 None；mock 各 None 验证降级不报错；映射 AC1 |
| A13 | `diagnosis.py` `build_indicator_set` 透传 6+4 新字段（last_close/open/change_amt/pe_ttm/mcap_yi/pb + sector_net_inflow/inflow/outflow + prev_amount_yi） | A4,A5,A9,A10,A11 | `backend/candidate_funnel/diagnosis.py` | mock source dict 含新字段，验证 IndicatorSet 各字段透传；缺失字段 None + missing；映射 AC5 |
| A14 | `funnel.py` `_run_funnel_impl` 扩展：采集 2 新 source（zt_pool_source.fetch_zt_pool_map(yesterday) + derived_source.fetch_derived per code），透传给 `build_diagnosis_card`。**注**：yesterday_date 用 `is_trading_day` 回溯（vr_paths.py:63，参考 workflow.py:1011-1014） | A6,A7,A8,A12 | `backend/candidate_funnel/funnel.py` | 离线 mock 端到端：验证 FunnelResult.final_candidates 的 DiagnosisCard 含 3 子对象；个股不在涨停池验证 pool_item=None；snapshots 未采集验证 derived=None；映射 AC1 |
| A15 | 单测：models 3 子对象 + sources 契约（gene/zt_pool/derived/activity/fund_flow）+ diagnosis 塞入 + funnel 端到端 | A6-A14 | `backend/candidate_funnel/tests/test_diagnosis.py`、`tests/test_sources_contract.py` | `pytest -m "not live" backend/candidate_funnel/tests/` 全过；映射 AC1-AC5 |

---

## 阶段 B · 战法从 DiagnosisCard 读（R5-R6，AC6-AC7）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | `match_strategies` 加 `card: Any=None` 参数（默认 None 向后兼容，B2）。card 非空时从 card 子对象 override 读（`pool_item = pool_item or card.pool_item` 等），**card=None 时保留既有 fallback 路径不删**（S070 自取数/kline_rebuild 调用保留，Q3=C pre_market_workflow 不传 card 走 fallback 行为不变） | A14 | `backend/limitup_strategy.py` | 既有调用不传 card 验证行为不变（fallback 路径未删）；mock card 非空验证 override 读取；映射 AC6 |
| B2 | 既有 9 战法（first_plate/consecutive_relay/break_reseal/low_absorption/reverse_package/n_shape_counterattack/platform_breakout/end_of_day_sneak）：从 `gene` 读（不变）。**注**：card 非空时 gene 可从 `card.gene_score` 重建（调用方负责），card=None 走原 gene 参数 fallback | B1 | `backend/limitup_strategy.py` | mock card=None + gene 验证 9 战法命中不变（fallback）；mock card 非空 + gene 重建验证命中一致；映射 AC7 |
| B3 | PRD 弱转强接力（weak_turn_strong）：card 非空时从 `card.derived` override 读（broken_duration_min/max_drop_pct/last_lock_time）+ `card.indicators.prev_turnover_pct` 读 vol_ratio_1d。**card=None 走既有 S070 取数 fallback**（line 817-825 `get_snapshots_by_code(code, 今日)` + `compute_derived_features` 保留不删，B2）。card.derived=None 且 card 非空 → 标 `missing_s070_r7` 跳过（既有逻辑） | B1 | `backend/limitup_strategy.py` | mock card 含 derived 验证从 card 读命中；mock card=None 验证走既有 S070 fallback 命中一致；mock card.derived=None 验证标 missing 跳过；映射 AC6 |
| B4 | PRD 形态反包（pattern_reversal）：card 非空时从 `card.pool_item.zdp` 读 close_pct + `card.indicators`（max_high_pct/shadow_length_pct/ma_5_status）+ `card.indicators.amount_yi/prev_amount_yi` 算放量比（补 S081 缺 volume 字段）。**card=None 走既有 fallback**（既有从 pool_item/indicators 参数读路径保留不删，B2） | B1 | `backend/limitup_strategy.py` | mock card 含 pool_item+indicators 验证从 card 读命中；mock card=None 验证走既有 fallback 命中一致；映射 AC6 |
| B5 | `StrategyMatcher.match()` + `match_batch()` 加 `card`/`cards_map` 参数透传给 `match_strategies`。**card 默认 None**，既有调用不传 card → 走既有 fallback 路径（Q3=C pre_market_workflow 行为不变）；card 非空时 override 从 card 取全部子对象传 | B1 | `backend/strategies/strategy_matcher.py` | 既有调用不传 card 验证行为不变；mock cards_map 非空验证透传到 match_strategies；映射 AC6-AC7 |
| B6 | 单测：card 传/不传 命中一致（既有 9 战法 + PRD 2 战法）+ card.derived=None 降级 + card=None 走 fallback | B2,B3,B4,B5 | `backend/tests/test_s084_match_card.py`（新增） | `pytest -m "not live" backend/tests/test_s084_match_card.py` 全过；**AC7 回归：传/不传 card 命中一致** |

---

## 阶段 C · 前端两级 Tab（R7-R8，AC8-AC9）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | `candidates.ts` `DiagnosisCard` 类型加 3 子对象字段（gene_score/pool_item/derived，均 `Record<string,unknown>\|null`）+ `IndicatorSet` 加 10 字段（6 tencent_quote + 3 板块资金 + prev_amount_yi）。**注**：seat_detail/market_context/派生/催化（AC5a-d）不在本 spec 实现 | A1,A2,A3,A4,A5 | `frontend/src/lib/candidates.ts` | `npx tsc --noEmit` 过；类型含新字段；映射 AC8 |
| C2 | `Workflow.tsx` 加两级 Tab 导航（`选股池` \| `战法`）：新增 `tab` state，默认"战法"保持既有行为。战法 Tab 保留既有 `StrategyFlowCard` 网格（line 543-616，已实现不改，R8） | C1 | `frontend/src/pages/Workflow.tsx` | `tsc --noEmit` 过；默认渲染战法 Tab（既有视图）；切换选股池 Tab 渲染新视图；映射 AC8-AC9 |
| C3 | 选股池 Tab 新增视图：调 `candidatesApi.runFunnel("all", selectedDate)` 取 FunnelResult → 用既有 `FunnelLayers` 组件（独立组件，`components/candidate/FunnelLayers.tsx`）展示 R1→R2→R3 三层 + 用既有 `SelectionPipeline`（Candidates.tsx 已有独立使用先例）展示 final_candidates。**注**：CandidateFunnelEmbed 是 PreMarketBriefing 局部函数不可复用（H1）；**不调** `/api/workflow/pre-market`（解耦，R7.2） | C2 | `frontend/src/pages/Workflow.tsx` | `tsc --noEmit` 过；选股池 Tab 渲染漏斗三层 + final_candidates；网络请求调 `/workflow/candidates/funnel`（非 `/api/workflow/pre-market`）；映射 AC8 |
| C4 | 前端类型检查 + 冒烟 | C3 | — | `cd frontend && npx tsc --noEmit` 全过；`npm run dev` 打开 /workflow 选股池 Tab 展示漏斗+候选，战法 Tab 保留既有卡片 |

---

## 阶段 D · pre_market_workflow 保留不改（R9，AC10）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | 确认 `pre_market_workflow.py` + `routers/workflow.py` 不改（Q3=C 保留原样）。`_build_funnel_layers` 调 `funnel_mod.run_funnel` 已返回含 3 子对象的 FunnelResult，透传即可；pre_market 端点 `final_cards`（line 204）已含 3 子对象（model_dump 透传） | A14 | —（不改，仅验证） | `pytest -m "not live" backend/tests/test_pre_market_workflow*.py` 既有测试全过；pre_market_workflow 行为不变（三入口并存）；映射 AC10 |

---

## 阶段 E · 验收（全 AC）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | 逐条核对 AC1-AC11（AC5a-d 已移 backlog，标"不在本 spec 实现"） | A15,B6,C4,D1 | — | AC checklist 全绿（AC1-AC4/AC5/AC6-AC11）；AC5a-d 标 backlog |
| E2 | 合规自查（spec §7）：DiagnosisCard 无方向结论词；研判/买卖时机/仓位参数挂轻量风险提醒（既有 Disclaimer 组件）；继承 S079 §2.3 参考价位隔离豁免 | 全部 | — | 自查表全绿；映射 AC11 |
| E3 | `pytest -m "not live"` 全过（candidate_funnel + match_card + pre_market 回归） | A15,B6,D1 | — | 全绿 |
| E4 | 写验收报告，更新 spec 状态"已实现(日期)" | E1-E3 | `specs/S084-选股池战法解耦/验收报告.md` | 报告归档 |

---

## 依赖图（关键路径）

```
A1→A2→A3→A4→A5
         ↓
A6(gene)        A8(derived)
A7(zt_pool)     ↓
   ↓          A12(diagnosis 塞 3 子对象)
   └──────────→ A13(build_indicator_set 透传)
                  ↓
                A14(funnel 采集 2 source + 塞入)
                  ↓
                A15(单测) → B1(match_strategies card 参数)
                            ↓
                  B2(9战法) B3(弱转强) B4(形态反包) → B5(StrategyMatcher)
                                                       ↓
                                                     B6(单测) → C1(candidates.ts 类型)
                                                                ↓
                                                              C2(Tab)→C3(选股池视图)→C4(冒烟)
                                                                                          ↓
                                                            D1(回归) → E1-E4(验收)
```

- A 阶段是地基（models → sources → diagnosis → funnel）。
- B 依赖 A14（funnel 产 card 才能测 match 从 card 读）；B3/B4 card=None 走 fallback（B2 决议）。
- C 依赖 A1-A5（类型对齐后端）；C3 选股池 Tab 独立于 PreMarketBriefing（H1，不复用 CandidateFunnelEmbed）。
- D 不改代码，仅回归验证（Q3=C）。
- 关键路径：A1→A4→A6→A7→A12→A14→A15→B1→B6→C1→C3→C4→E1。

---

## 执行规则

1. **一次一任务**：按 ID 顺序，完成一条跑其验收方式再开下一条。
2. **B2 保留 fallback**（B3/B4 必须标注）：match_strategies card=None 时保留既有 S070 自取数/kline_rebuild 调用路径不删（Q3=C pre_market_workflow 不传 card 走 fallback 行为不变）；card 非空时 override 从 card 读。
3. **AC5a-d 不在 tasks 范围**：market_context/seat_detail/派生因子/催化因子已移 backlog，本 spec 不实现。
4. **数据走 em_get**：A7 复用 `first_board_filter.fetch_zt_pool`（走 em_get + 24h 缓存）；不裸调 requests。
5. **T-1 昨日边界**：A8 derived 取 `get_snapshots_by_code(code, yesterday_date)`（Q2=B，非今日）；A14 yesterday_date 用 `is_trading_day` 回溯（vr_paths.py:63）。
6. **不臆造**：3 子对象各自管理缺失（gene_score=None/pool_item=None/derived=None），各标原因。
7. **H1 不复用 CandidateFunnelEmbed**：C3 选股池 Tab 用 FunnelLayers + SelectionPipeline（CandidateFunnelEmbed 是 PreMarketBriefing 局部函数不可复用）。
8. **commit 引用**：commit message 带 S084 + 任务 ID（如 `S084-A6 gene.py 扩展存完整 GeneScore`）。
