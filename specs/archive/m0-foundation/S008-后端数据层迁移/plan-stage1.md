# S008 阶段1续设计：数据总线（无状态）+ 异构接口 + 五源 + astock 门面

> 对应 `spec.md`、`plan.md`。本文件细化阶段1（T7 五源 + T8 astock 门面）的实现方案。
> 编写于 2026-07-30，基于 Explore 实证。

## 背景

阶段0 bug 修复已提交（683 测试绿），`data/transport.py`(T6) 与 `data/mappers.py`(T11 部分) 已建。下一步迁 `astock.py`（795 行）取数逻辑到 `data/sources/*`。

**核心风险**：astock 被 46 文件、159 处引用，返 `dict`。若走 `raw→Quote→legacy_dict` 往返迁移会**丢字段**。Explore 实证丢失字段有活跃消费：

| 丢字段 | 消费者 | 后果 |
|---|---|---|
| `last_close` | `bidding_monitor.py:111` | `open_premium` 算式分母=0 → 塌成 0 |
| `open` | `bidding_monitor.py:112` | 同上，竞价快照退化 |
| `vol_ratio` | `bidding_monitor.py:114`、`candidate_funnel/sources/activity.py:36` | volume_ratio=0；funnel 全标「行情字段未取得」 |
| `high/low/pe_static` | 无 | 可安全丢（但 legacy 仍保留） |

另：`/api/quote`、`/api/stock/<code>`、`chat.query_quote` 把完整 dict 原样透传给前端/LLM，有损往返会静默丢字段。

## 解法：数据总线 + 异构接口（无状态纯 dispatch）

用户拍板（2026-07-30）：总线**不带跨调用缓存**——盘中实时行情对 staleness 敏感，缓存留在现有路由级 `cache_response(ttl)` / 涨停四池 24h 缓存。

- **raw 解析 = 唯一事实源**（全字段，不丢）。
- **legacy 投影 = raw 原样**（旧消费者拿全字段 dict）。
- **model 投影 = `mappers.*_from_dict(raw) -> Quote/...`**（新消费者）。
- 两条投影都从 raw 直接派生，**不互相往返**。

```
data/sources/<src>.fetch_raw()  ──→ raw dict（唯一事实源，全字段）
        ├─ legacy：astock.<fn> 直接返 raw（28 消费者不改）
        └─ model：mappers.<src>_from_dict(raw) → Quote/...（新消费者，后续轮）
```

## 目标架构

```
data/
├─ transport.py        (T6 已建，eastmoney_get 限流/熔断/代理)
├─ mappers.py          (T11 已建，raw→模型投影)
├─ __init__.py
└─ sources/
   ├─ __init__.py
   ├─ _common.py       UA / DependencyMissing
   ├─ tencent.py       urllib 行情底座
   ├─ eastmoney.py     em_get 系 + 直 requests 研报/公告/热门概念
   ├─ akshare_src.py   6 个 akshare 惰性函数
   ├─ mootdx_src.py    kline / finance
   └─ cninfo.py        investor_qa
```

> **plan.md §2 订正**：原列 `sina.py`（财报三表/公告）在 astock.py 中**不存在**——`financials` 走 akshare、`disclosure` 走 akshare 的 cninfo 包装、`investor_qa` 直连 cninfo。故第五源改为 `cninfo.py`。tasks.md 的 "sina" 字样同步订正。

## 各源模块（从 astock.py 迁出，取数逻辑不改）

### `sources/_common.py`
`UA`（共享 UA 串）、`DependencyMissing(RuntimeError)`。

### `sources/tencent.py`（urllib，不封 IP）
迁入 `get_prefix`、`_fetch_gtimg`、`_parse_gtimg`、`A_INDICES`。新公开 `fetch_raw(codes)->dict[str,dict]`（= 旧 `tencent_quote`，返全字段含 `last_close/open/high/low/vol_ratio/pe_static`）、`index_raw()->list[dict]`（= 旧 `index_quote`）。

### `sources/eastmoney.py`（走 `data.transport.eastmoney_get` + 少量直 requests）
- em_get 系：`em_zt_topic_pool`、`market_turnover_rank`、`eastmoney_datacenter` + 8 下游（`margin_trading`、`block_trade`、`holder_num_change`、`dividend_history`、`stock_fund_flow_120d`、`dragon_tiger_board`、`lockup_expiry`、`concept_blocks`、`industry_comparison`）
- 直 requests 系：`_report_session`、`eastmoney_reports`、`eastmoney_industry_reports`、`pdf_url`、`announcements`、`hot_concepts`
- 迁入常量/helper：`_REPORT_API`、`_PDF_TPL`、`_DATACENTER_URL`、`_ZTB_UT`、`_ZTB_CACHE_TTL`、`_ztb_cache`、`_numf`
- 用 `from data.transport import eastmoney_get`（防封底线）

### `sources/akshare_src.py`（惰性 import akshare）
`_akshare`、`profit_forecast`、`stock_news`、`individual_info`、`disclosure`、`financials`、`valuation_percentile`。

### `sources/mootdx_src.py`（惰性 import mootdx）
`_mootdx_client`、`kline`、`finance`。

### `sources/cninfo.py`（直 requests 巨潮互动易）
`investor_qa`。

## astock.py 门面化（T8）

- 删迁出函数体 → 薄封装/re-export，**公开签名与返回 shape 一字不改**（仍返 raw dict）。
- 留下：`calc_peg`、`pe_digestion`（纯计算）、`full_valuation`（组合编排，内部调 `sources.tencent.fetch_raw` + `sources.akshare_src.profit_forecast` + calc）。
- `em_get` → `from data.transport import eastmoney_get as em_get`（re-export）。
- 保留被外部直访的名字（`astock._akshare` 等）作门面。

## mappers.py 修正（T11 补）

删 `legacy_quote_dict(quote)`：当前是 `Quote→dict`（有损往返方向，与总线设计相悖）。legacy 消费者直接吃 `sources.*.fetch_raw`（raw 即 legacy）。确认无调用者后删。

## 测试（匹配 `test_s008_*.py` 风格）

- `test_s008_sources_tencent.py`：monkeypatch `_fetch_gtimg` 返固定 gtimg 串 → 断言 `fetch_raw` 返**全字段**，特别 assert `last_close/open/vol_ratio/pe_static` 存在（锁无字段丢失）。
- `test_s008_sources_facade.py`：`astock.tencent_quote is sources.tencent.fetch_raw`；逐 public 名 callable 返 raw dict；`astock.em_get is data.transport.eastmoney_get`。
- `test_s008_sources_eastmoney.py`：monkeypatch `eastmoney_get` → 锁 `market_turnover_rank`/`stock_fund_flow_120d` 委派不改行为。
- 非回归：`bidding_monitor`/`activity` 拿到的 dict 含 `vol_ratio`。

## 合规自查（弱合规·工程底线）

- [x] 不臆造：只迁取数逻辑，测试 monkeypatch 固定串。
- [x] 私有数据隔离：本轮不涉及。
- [x] 防封：东财走 `data.transport.eastmoney_get`；`_report_session` 走 requests 是 reportapi（非封 IP 域，原 astock 即如此）。
- [x] `lianban_stocks`：本轮不动 `market._emotion` 原始出口，`Emotion` mapper 已剥离——零变更。

## 不在本轮

T1/T12/T13 消费者迁模型、T9 gstock 扁平化、T10 market 模型化、T15 删 legacy、T16 删 data_provider、T17/T18 基线回放。
