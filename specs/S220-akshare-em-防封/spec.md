# Spec: S220 — akshare_src stock_news / individual_info 迁 em_get 防封

> 状态：草案
> 作者：Backend Architect  日期：2026-09-20
> 关联：v2 审查 C2 CRITICAL；S008 akshare_src；S114 chip_distribution（em_get 先例）；fund_flow.py:313 `_industry_of`（push2delay+ut 先例）

## 1. 问题 / 目标

`akshare_src.stock_news` / `individual_info` 调 `ak.stock_news_em` / `ak.stock_individual_info_em`，
akshare 内部用 `curl_cffi.requests` / 裸 `requests` 直连东财 host，**绕过 `em_get` 熔断器 +
0.3s 限流 + 直连/代理探测**——已致 eastmoney push2 outage。其中 `individual_info` 命中
`push2.eastmoney.com/api/qt/stock/get` **不带 ut token**，被 `predict/features/fund_flow.py:313`
`_industry_of` docstring 实测确认会断连（`fund_flow._industry_of` 已改走 push2delay+ut）。

目标：两函数改走 `em_get`（`data.transport.eastmoney_get`），保留原返回 shape（中文键 dict /
list[dict]），熔断时诚实降级返空。

## 2. 背景

**事实更正（核于 venv akshare 源码 2026-09-20）**：任务背景称两端点为 HTML（
`so.eastmoney.com/news/s?keyword=CODE` / `quote.eastmoney.com/concept/shCODE.html`），
**实际 akshare 源码用的是 JSON/JSONP，非 HTML**：

- `akshare/news/news_stock.py::stock_news_em` → `https://search-api-web.eastmoney.com/search/jsonp`
  （JSONP：响应是 `jQuery<digits>(<json>)` 文本，剥 callback 包壳后 `json.loads`，
  取 `result.cmsArticleWebOld` list）。host 含 `eastmoney` 不含 `datacenter` → `eastmoney` breaker。
- `akshare/stock/stock_info_em.py::stock_individual_info_em` → `https://push2.eastmoney.com/api/qt/stock/get`
  （JSON：`r.json()["data"]` 是 f-code → value 的 dict）。**不带 ut** → 断连根因。

故无需 HTML 解析（pandas.read_html/BS4），改走 JSON 解析，更简单稳健。

**先例（同 codebase）**：
- `akshare_src._fetch_cyq_klines`（S114）：`from data.transport import eastmoney_get as em_get`
  + `em_get(url, params, headers, timeout=8)` + `r.json()` 解析，熔断 OPEN raise → try 兜底返 None。
- `fund_flow._industry_of`：`push2delay.eastmoney.com/api/qt/stock/get` + `ut=_EM_PUSH2_UT` + em_get，
  已验证 push2 主 host 断连时 delay host + ut 可达。

**`em_get` 签名**（`data/transport.py:96`）：`eastmoney_get(url, params=None, headers=None,
timeout=15, *, json=None, method="GET")` → `requests.Response`；breaker `allow_request()=False`
时 raise `RuntimeError`；URL host 选 breaker 分组（`_select_breaker_name`）。

## 3. 需求清单

- [ ] R1 `stock_news(code, limit)` 改走 `em_get` 拉 `search-api-web.eastmoney.com/search/jsonp`
  JSONP，剥 callback 包壳 + `json.loads` 取 `result.cmsArticleWebOld`，返 list[dict] 含中文键
  `关键词/新闻标题/新闻内容/发布时间/文章来源/新闻链接`（保原 shape，对齐 `models/news.py` +
  `data/mappers.news_from_raw`），`[:limit]` 截断，`<em>` 标签清洗。
- [ ] R2 `individual_info(code)` 改走 `em_get` 拉 `push2delay.eastmoney.com/api/qt/stock/get`
  + `ut` token（对齐 `fund_flow._industry_of` 验证过的防断连 host+token），请求 9 个 f-code
  （f57/f58/f84/f85/f127/f116/f117/f189/f43），`r.json()["data"]` dict 映射中文键
  `股票代码/股票简称/总股本/流通股/行业/总市值/流通市值/上市时间/最新`（保原 shape，对齐
  `data/mappers.company_info_from_individual_info` 读 `行业`/`上市时间`）。
- [ ] R3 熔断 OPEN（`em_get` raise `RuntimeError`）/ 请求异常 / JSON 解析失败 / 无 data →
  `stock_news` 返 `[]`、`individual_info` 返 `{}`（诚实降级，不臆造、不抛）。
- [ ] R4 不裸调 `requests`/`curl_cffi`，不经 akshare（删 `_akshare()` 委派）；`disclosure` /
  `financials` / `valuation_percentile` / `profit_forecast` 不动（不在 scope）。
- [ ] R5 `individual_info` 用 push2delay + ut（非 push2 主 host），根因消除 push2 outage 触发源。
- [ ] R6 中文键 shape 与原 `akshare_src.stock_news` / `individual_info` 逐字一致（防下游
  `data/mappers.py` / `models/news.py` / `models/financials.py` 静默退化）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/akshare_src.py` | 重写 `stock_news` / `individual_info` 走 em_get + JSON 解析；不动其余函数 |
| `backend/tests/test_akshare_em_migration.py` | 新增 TDD：mock em_get 验走 em_get + 熔断降级 + shape 保真 |
| `specs/S220-akshare-em-防封/spec.md` | 本 spec |

## 5. 设计方案

**stock_news**（JSONP → JSON）：
1. `from data.transport import eastmoney_get as em_get`（惰性，对齐 `_fetch_cyq_klines` 先例）。
2. `url = "https://search-api-web.eastmoney.com/search/jsonp"`；params：
   - `cb`: 固定 JSONP callback 名（`jQuery_cb_` + 随机后缀，任何合法名都行，服务端原样包壳）。
   - `param`: 内层 JSON（`type=["cmsArticleWebOld"]`, `client="web"`, `param.cmsArticleWebOld`
     `{sort,pageIndex:1,pageSize:10,preTag/postTag}`）`json.dumps(ensure_ascii=False)`。
   - `_`: 当前毫秒时间戳（cache-buster，akshare 硬编码旧值，动态更稳）。
3. headers：`{"Referer": "https://so.eastmoney.com/", "Accept": "*/*"}`（UA 由 em_get 注入，
   akshare 的 cookie/sec-ch-ua 实测对 search API 非必需，精简）。
4. `r = em_get(url, params, headers, timeout=10)`；`text = r.text`。
5. 剥 JSONP 包壳：`json.loads(text[text.index("(")+1 : text.rindex(")")])`（通用，不写死
   callback 名）。取 `data["result"]["cmsArticleWebOld"]`（list[dict]）。
6. 逐项映射中文键 + 清 `<em>` 标签 + 拼 `新闻链接 = http://finance.eastmoney.com/a/{code}.html`，
   保 6 列顺序 `关键词/新闻标题/新闻内容/发布时间/文章来源/新闻链接`。
7. `return rows[:limit]`（对齐原 `df.head(limit)`）。
8. try 兜底：em_get raise / 解析异常 / `result` 缺 → `[]`。

**individual_info**（push2delay + ut → JSON）：
1. `url = "https://push2delay.eastmoney.com/api/qt/stock/get"`（delay host，对齐 `_industry_of`）。
2. params：`secid=f"{1 if code.startswith('6') else 0}.{code}"`、
   `fields="f57,f58,f84,f85,f127,f116,f117,f189,f43"`（9 个映射 f-code，subset of akshare 原长列表）、
   `ut=_EM_PUSH2_UT`（`"fa5fd1943c7b386f172d6893dbbd1"`，与 `fund_flow._EM_PUSH2_UT` 同值公开 token；
   akshare 原调用缺 ut = 断连根因）。`fltt=2`、`invt=2`（保 akshare 原参数）。
3. headers：`{"Referer": "https://quote.eastmoney.com/"}`。
4. `r = em_get(url, params, headers, timeout=8)`；`data = r.json().get("data") or {}`。
5. `code_name_map = {f57:股票代码, f58:股票简称, f84:总股本, f85:流通股, f127:行业,
   f116:总市值, f117:流通市值, f189:上市时间, f43:最新}`；
   `return {name: data[code] for code, name in code_name_map.items() if code in data}`（复刻
   akshare `pd.DataFrame(data_json)` + reset_index + map + notna filter 的净效果，无 pandas 绕路）。
6. try 兜底：em_get raise / `data` 非 dict / 解析异常 → `{}`。

**取舍**：
- **不用 push2 主 host**：`fund_flow.py:313` 实测 push2 stock/get 缺 ut 断连；走 push2delay+ut
  是同 codebase 已验证的安全形态（R5）。代价：`总市值/流通市值/最新` 是延时~15min 镜像值，
  对 `individual_info`（基本面静态属性 + 慢变量）可接受；实时行情不在此函数 scope。
- **不双 host 降级**（push2→push2delay）：最小改动；push2delay 单 host + em_get breaker 已够，
  双 host 是 `sector_fund_flow` 的 over-engineering，YAGNI。
- **不保留 akshare pandas 绕路**：原 `pd.DataFrame(data_json)` + reset_index + map + notna 是
  DataFrame 体操，净效果就是 f-code→中文名映射，直 dict 推导更清晰（DRY）。
- **不写死 JSONP callback 名**：用 `index("(")/rindex(")")` 通用剥壳，akshare 硬编码 `jQuery351...`
  脆弱（akshare 升级换名即崩）。

## 6. 验收标准

- [ ] A1 `tests/test_akshare_em_migration.py` 全 green：mock em_get 验两函数真走 em_get
  （URL 含 eastmoney host）+ shape 保真（中文键）+ breaker raise→空 + `<em>` 清洗 + `data:null`→`{}`。
- [ ] A2 `pytest -m "not live" --tb=no -q` 全 green（非回归：`test_s008_sources_facade` /
  `test_s008_t13d_fundamentals` / `test_s008_t12_chat_tools` mock 在 astock 层，不受实现变更影响）。
- [ ] A3 `akshare_src.stock_news` / `individual_info` 不再 import 或调 `akshare`（grep 零命中
  `ak.stock_news_em` / `ak.stock_individual_info_em` in this file's two functions）。
- [ ] A4 中文键 shape 与 `data/mappers.news_from_raw` / `company_info_from_individual_info` 对齐。

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机：本改动纯数据层防封迁移，不涉及研判输出，无需挂风险提醒。
- [x] 判断可复现：不臆造数据——熔断/请求失败返空 `[]`/`{}`（诚实 falsy，下游走 missing 标记，
  与 `chip_distribution` 返 `{}` 同范式），不补默认值。
- [x] 涨停四池/连板股榜：不涉及。
- [x] 用户私有数据：不涉及（无持仓/key/研报）。
- [x] **新增东财端点走 `em_get()` 限流**：本 spec 核心——`stock_news`/`individual_info` 由裸调
  akshare（绕 em_get）迁入 em_get（breaker + 0.3s 限流 + 代理探测），工程底线满足。

## 8. 测试计划

`tests/test_akshare_em_migration.py`（TDD RED→GREEN）：
1. `test_stock_news_routes_through_em_get` — fake em_get 记 URL，断言含 `search-api-web.eastmoney.com`。
2. `test_stock_news_preserves_chinese_keys_and_cleans_em_tags` — JSONP 响应含 `<em>` 标签 →
   返 list[dict] 键 `关键词/新闻标题/新闻内容/发布时间/文章来源/新闻链接`，标签已清。
3. `test_stock_news_breaker_open_returns_empty` — em_get raise RuntimeError → `[]`。
4. `test_stock_news_limit_truncates` — 响应 10 条 + `limit=3` → 返 3 条。
5. `test_individual_info_routes_through_em_get_push2delay` — 断言 URL 含 `push2delay.eastmoney.com`
   且 params 含 `ut` + `secid`。
6. `test_individual_info_preserves_chinese_keys` — 返 dict 键 `股票代码/股票简称/总股本/流通股/
   行业/总市值/流通市值/上市时间/最新`。
7. `test_individual_info_breaker_open_returns_empty_dict` — em_get raise → `{}`。
8. `test_individual_info_data_none_returns_empty_dict` — 响应 `{"data": null}` → `{}`。

mock 方式：`monkeypatch.setattr("data.transport.eastmoney_get", fake)`（函数内惰性 `from
data.transport import eastmoney_get as em_get`，patch 源模块属性即生效，对齐 `_fetch_cyq_klines`
惰性导入形态）。`_FakeResp` 带 `.text` / `.json()`。

离线 `pytest -m "not live"` 全 green；live 验证（手动）后端 `/api/stock/news` /基本面接口返数据。

## 9. 风险与回滚

- **风险 1：search-api-web JSONP 端点对 em_get 的 requests session（无 TLS 指纹）可能返挑战页**。
  缓解：测试 mock 不验 live；live 失败时 em_get breaker 5 次失败 OPEN → 返 `[]`（诚实降级，
  不崩）；后续可加 curl_cffi session 但超出本 spec scope（YAGNI，先验证再扩展）。
- **风险 2：push2delay 缺某些 f-code（如 f189 上市时间）返 null**。缓解：`if code in data` filter，
  缺则该键不出现（与 akshare 原行为一致——akshare `pd.notna` filter 也丢缺失项）。
- **回滚**：`git revert <commit>`；两函数纯局部改动，无 schema/契约变更，零下游影响。
