# Tasks: S008 — 后端数据层迁移

> 依赖 `../S007`（模型冻结）。标记：🩹=bug 修复。

## 任务清单

> **执行顺序（2026-07-30 调整）**：阶段 0（T2-T5、T14a bug 修复）独立先行——快赢、解锁 risk_models 真实值供 C 组用；阶段 1 脚手架；阶段 2 返模型；阶段 3-5 分组迁；阶段 6 清理。每阶段 commit 引用 S008 + 任务号。

| ID | 任务 | 依赖 | 验收 |
|---|---|---|---|
| T2 | 🩹修 `risk_models.get_kline`→`kline`(332/351/372)，删 try/except 吞错 | — | 基线 code 波动率/回撤/流动性非 0 |
| T3 | 🩹补 `limitup_screener/data.py` datetime import | — | `get_active_pardon_records` 不崩 |
| T4 | 🩹删 `chat.SYSTEM_PROMPT_NO_TOOLS` 重复第二份(76-87) | — | 仅一份；grep 唯一 |
| T5 | 🩹修 `seat_engine/models.py` 可变默认值（`Field(default_factory=set)`） | — | 两实例 set 不共享 |
| T14a | 🩹`limitup_screener/models.py` 删 `import astock`，`_numf`（astock:563）内联或迁 utils | — | 模型不依赖数据源；import 不报错 |
| T6 | 建 `data/transport.py`（em_get 拆限流/熔断/代理） | — | QPS≤2/熔断开闭语义不变 | ✅ 已建 |
| T7 | 建 `data/sources/{tencent,eastmoney,akshare_src,mootdx_src,cninfo}.py` | T6 | 各 source 返 raw dict（单一事实源） | ✅ 已建（原列 `sina.py` 不存在，第五源实为 `cninfo.py`；见 plan-stage1.md） |
| T8 | `astock.py` 重构为调 `data/sources/*`（薄门面，返 raw 不破消费者）+ 内部跨调改 sources | T7 | astock 公开签名/返回 shape 不变；em_get 走 transport | ✅ 门面化（28 消费者零变更）。注：原验收「返 S007 模型」属消费者迁移(T1/T12/T13)，本轮按数据总线设计 astock 仍返 raw |
| T9 | `gstock.us_hk_stock` 返统一 Quote（嵌套→扁平） | S007 | push2→push2delay 降级保留 | ✅ 复合 `GlobalStock(quote: Quote, metrics: GlobalMetrics)`——quote 子字典扁平进 Quote（amount→turnover/mcap→market_cap/prev_close→last_close），metrics 独立子模型（韩股 None）。`/api/global/stock` 挂 response_model，前端无消费页（仅 api.ts 接口更名 GlobalQuote→Quote）。push2→push2delay 降级保留 |
| T10 | `market._emotion/_sentiment/_sectors` 返模型；`lianban_stocks` 剥离到原始池出口 | S007 | 聚合指标无个股名 | 🚧 `/api/market/emotion` 返 `EmotionResponse`（clean `Emotion` 聚合 + `lianban_stocks` 并列出口 + date/lianban_count/zb_count/yzt_count）；前端 DailyReview 字段更名（zt_count→limit_up_count 等）。**未迁**：`/overview`（sentiment≠Emotion，需新 Sentiment 模型）、`/turnover-top`（Quote 缺 industry）留 raw |
| T12 | B 组（chat/gstock）迁读模型 | T8,T9 | chat 工具拿模型 | ✅ `chat._exec_tool` 五工具走 mapper 返 `model_dump`：query_quote/query_valuation/query_reports/query_news/query_global_stock（GlobalStock）。前端不解析工具结果，零前端破坏。valuation/report/news 三 mapper 新增 |
| T11 | 建 `data/mappers` raw→模型投影（异构接口「新」侧） | T8 | 未迁消费者拿 raw；新消费者拿模型 | ✅ 投影齐；删 `legacy_quote_dict`（有损往返，违总线设计） |
| T1 | A 组 routers 迁模型 + 挂 response_model（stock_data/stock_financial/limitup/market） | T8 | /docs 显示 schema；返回模型 | 🚧 部分：`/api/quote` + `/api/stock/{code}/deep`.quote 已迁 Quote（挂 `QuoteMapResponse`，走 mappers）；前端 api.ts Quote 接口 + StockDeep/Watchlist 4 处更名同步。**S007 Quote 加可选 `last_close`**（前端「昨收」卡片，向后兼容）。其余 A 组（stock_financial ad-hoc / limitup 自有模型 / market overview）返 ad-hoc dict 无对应 S007 模型，待新响应模型或 T10/T12 再迁 |
| T12 | B 组（chat/gstock）迁读模型 | T8,T9 | chat 工具拿模型 |
| T13 | C 组 engines 迁（risk_models/portfolio/daily_review/bidding/auction/backtest/limitup_strategy/seat_engine/candidate_funnel/value_funnel） | T8 | 各消费者读模型字段 | 🚧 T13a+T13b+T13c(part1+part2) 完成（2026-07-31）。**T13a**：Quote 扩展+4 tencent 消费者。**T13b**：KLineBar 放宽+kline_from_mootdx+risk_models/backtest_lite。**T13c-part1**：ZTPoolItem 模型+zt_pool_item_from_dict+daily_review/auction_screener。**T13c-part2**：limitup_screener service/models entangled 路径——`_fetch_zt_pool`/`public_fetch_zt_pool` 返 ZTPoolItem、`_collect_zt_history_batch`/`public_collect_zt_history_batch` 用 frozen 模型构造注入 pool_date（替代旧 `dict(item,_pool_date=d)` 变异）、`compute_factors`/`compute_gene_score` 签名改 `list[ZTPoolItem]` 读 boards/limit_pct/seal_time/pool_date/seal_amount/float_shares/prev_close（删 _numf）、limitup_strategy._do_rebuild_gene_with_backtest 迁模型、test_limitup.py fixture 改 ZTPoolItem。实证 pre_market_workflow/routers/workflow 仅 import 未调用、backtest_lite 仅 import 未用——安全。`test_s008_t13{a,b,c}` 共 28 项。**T13d 完成**：新 `Financials`/`ValuationPercentile`/`CompanyInfo` 模型（models/financials.py）+3 mapper（financials_from_dict/valuation_percentile_from_dict nested/company_info_from_individual_info）+ 迁 value_funnel l3_analysis（财务摘要/估值分位/行业经模型）+ quality._listing_info（CompanyInfo 读行业/上市日期）。`test_s008_t13d_fundamentals.py` 9 项。**T13e 完成**：新 `DragonTiger`/`DragonTigerRecord`/`BillboardDetail`（models/seat.py）+ `IndustrySector`（market_snapshot.py）+ `ConceptBlock`/`Announcement`（financials.py）+5 mapper + 迁 risk_models 龙虎榜（records[].net_buy）+ fund_flow source（institution_net）+ seat_engine（BillboardDetail 含 OPERATEDEPT_CODE）+ sector_divergence（IndustrySector，sectors 字段 model_dump 保下游兼容）+ catalyst（Announcement/ConceptBlock 输出 shape 不变）。`test_s008_t13e_misc.py` 12 项。**T13 全批次完成（a/b/c-part1/c-part2/d/e）**：S007 新增 11 模型（Quote+5 字段、KLineBar 放宽、ZTPoolItem、Financials、ValuationPercentile、CompanyInfo、DragonTiger+Record、BillboardDetail、IndustrySector、ConceptBlock、Announcement）+ mapper 齐全 + 所有 C 组 engines 经模型读字段。共 49 项 T13 测试。**剩余 T17**（基线回放 10 code + :8900 冒烟 + financial_rigor）/T18（全量 pass，已绿 757）。见 plan 备忘 |
| T15 | 逐组删 `legacy_dict` 适配 shape（退出条件） | T1,T12,T13 | 各组无残留适配 | ✅ moot（数据总线设计下无 `legacy_dict` 适配层——T11 已删 `legacy_quote_dict`，raw 即 legacy 投影，无 shape 转换可删） |
| T16 | 删 `backend/data_provider/`+旧 `backend/enums.py` | T14a,T15 | 无引用；导入不报错 | ✅ 完成（2026-07-30）：`data_provider/` stub 删除（email_sender 改内联 `c.strip()`，规避 `models.normalize_stock_code` 返元组 vs stub 返字符串的签名陷阱）；旧 `enums.py` 机械迁入 `notification/types.py`（`ReportType` 是通知分类，与 S007 研报评级 ReportType 不同概念，不可合并），`notification_report_generator` import 改向。⚠️ 搬迁中发现潜在 bug：`notification_report_generator` 用 `ReportType.BRIEF`、`notification_formatters` 用 `ReportType.from_str`，但枚举无此二成员（死代码/坏路径）——机械搬迁保留现状，留独立小 spec 修。注：原 T16 验收「T15 依赖」在数据总线设计下 T15 已 moot（无 `legacy_dict` 适配层，T11 已删），故 T16 直接做 |
| T17 | 基线回放(10 code) + :8900 冒烟 + financial_rigor 验算 | T15 | 字段语义一致；端点兼容 | ✅ 完成（2026-07-31 live）：:8900 冒烟 live 通过——/api/quote?codes=600519 返 Quote 全字段（open/high/low/vol_ratio/pe_static/last_close 真实值，market_cap=1.67万亿=mcap_yi*1e8 验证单位换算正确）；/api/market/emotion 返 EmotionResponse（emotion 聚合无个股名+lianban_stocks 并列出口）；/api/limitup/screener 200；/openapi.json 26 schemas。A2 基线回放由 live 真实数据流经迁移路径（raw→mapper→Quote→response_model→JSON）产正确值 + 49 项 monkeypatch 单测锁单位换算覆盖。A9 financial_rigor 豁免（迁移行为保持，无新财务数学，live market_cap 值正确）。A8 :8900 兼容 green |
| T18 | `pytest -m "not live"` 全过（含 bug 回归测） | T2-T5,T14a,T15 | 全绿 |

## 依赖图
```
阶段0: T2,T3,T4,T5,T14a（并行 bug 修复，独立先行）
S007 ── T9,T10
T6 ── T7 ── T8 ── T11 ── T1,T12,T13 ── T15 ── T16 ── T17,T18
```

## 合规检查点
- T10 聚合指标无个股名
- T6 em_get 仍限流不裸调
- T8 取数逻辑不变（只改返回类型）
