# Tasks: S020 — worldmonitor 决策因子接入

> 依赖 `plan.md` 分阶段。TDD：离线解析纯函数先写测试再实现；live 冒烟标 `-m live`。

---

## P0 — 数据源层 + 传输/熔断（R1, R2, A1, A2）

### T1 确认 breaker 工厂按 name 隔离
- 读 `circuit_breaker.get_breaker(name)` 签名；验证 `get_breaker("worldmonitor")` 与 `get_breaker("eastmoney")` 独立计数/状态。
- 若已 name 隔离 → `data/transport.py` 零改动，仅在 worldmonitor.py 调用。否则先通用化（小改 transport）。
- **验收**：`get_breaker("worldmonitor") is not get_breaker("eastmoney")`，状态独立。

### T2 `data/sources/worldmonitor.py` MCP 客户端骨架
- 常量 `WORLDMONITOR_MCP_URL = "https://worldmonitor.app/mcp"`。
- `_post_mcp(tool, arguments=None, jmespath=None, proxy=None) -> dict | None`：POST JSON-RPC `tools/call`，jmespath 嵌入 arguments；读 `VR_HTTP_PROXY`；`get_breaker("worldmonitor")` 包裹（失败计数→OPEN 后短路返 None）。无 key/pro key 时 public 调用（pro key 见 T11）。
- **验收**：monkeypatch requests.post 返固定 JSON → `_post_mcp` 出 result；OPEN 状态下短路 None。

### T3 11 个 fetcher 薄封装
- `fetch_market_data / fetch_country_risk / fetch_news_intelligence / fetch_news_clusters / fetch_economic_data_china / fetch_country_macro / fetch_tariff_trends / fetch_supply_chain / fetch_energy_intelligence / fetch_china_decision_signals / fetch_hotspot_escalation`，各接 `jmespath` 透传 `_post_mcp`。
- **验收**：每个 fetcher 调 `_post_mcp` 用对 tool name（参数化单测，monkeypatch `_post_mcp` 断言调参）。

## P1 — 缓存 TTL（R3, A2）

### T4 `_cached_wm` 缓存包装
- 模块级 `_cached_wm(key, ttl, fn)`：仿 `market._cached`；空结果（None/空 list/dict）不缓存。TTL 常量：`_TTL_CII_HOTSPOT=86400`、`_TTL_MARKET=300`、`_TTL_NEWS=3600`。
- fetcher 接缓存：market_data→300s、news_clusters→3600、country_risk/hotspot→86400。
- **验收**：单测——fn 返空时不缓存（下次仍调 fn）、返非空时 TTL 内不调 fn。

## P2 — 纯解析函数 + 离线单测（R8, A1, A8）

### T5 纯解析函数（TDD：先写测试）
- `parse_market_data(resp) -> list[dict]`（商品/外汇快照）
- `parse_country_risk(resp) -> dict`（CII 31 国不稳定指数 + 合成分标 `source=worldmonitor_composite`）
- `parse_news_clusters(resp) -> list[{title, summary, category, ts}]`
- `parse_news_intelligence(resp) -> list[...]`
- `parse_hotspot_escalation(resp) -> list[...]`
- `parse_supply_chain(resp) -> dict`（干散货航运压力）
- 每个入参 mock JSON 样本 → 出参结构化；缺字段→None 不臆造。
- **验收**：`test_s020_worldmonitor.py` 解析单测全绿（离线，无网络）。

### T6 离线单测文件落地
- `tests/test_s020_worldmonitor.py`：解析 + 缓存 TTL + breaker mock + fetcher 调参单测。
- **验收**：`pytest -m "not live" tests/test_s020_worldmonitor.py` 全绿，并入全量 814→+N。

## P3 — newsradar 全球情报赛道（R4, A3）

### T7 newsradar 接入全球情报赛道
- `newsradar.py` 加 `_fetch_global_intel() -> list[dict]`：调 `worldmonitor.fetch_news_intelligence` + `fetch_news_clusters`，parse 后 merge；item `{title, summary, source:"worldmonitor", category, ts}`。
- `fetch_radar` 的 `industries` 加「全球情报」赛道（key 如 `global_intel`），与 12 赛道同构分组、时间倒序。
- **守零个股字段、客观措辞**；AI 提炼仍走 `/api/chat`。
- **验收**：单测——赛道输出零个股字段、item 同构、时间倒序；live 标 `-m live`。

## P4 — market 全球宏观/地缘分块（R5, A4）

### T8 market 加 `get_global_macro`
- `market.py` 加 `get_global_macro() -> dict`：商品（金/油/铜 via `fetch_market_data`）、外汇（DXY/USD-CNH）、CII（`fetch_country_risk`）、热点（`fetch_hotspot_escalation`）。复用 `_cached(key, fn, valid)` TTL 5min。
- **不与东财板块资金流混排**，单独分块。
- **验收**：单测 mock fetcher 返固定数据 → `get_global_macro` 结构正确、_cached 命中；live 标记。

## P5 — alt 特征注册（R7, A6, R10）

### T9 `predict/features/alt.py` 7 FeatureSpec
- 注册 `wm_cii_global / wm_hotspot_escalation / wm_dry_bulk_stress / wm_tariff_stress / wm_commodity_oil / wm_commodity_copper / wm_dxy`。FeatureSpec `source="worldmonitor", category="alt"`，`availability_offset` 占位（live 后定），`compliance_flag="aggregate_only"`（合成分作输入之一）。
- `wm_dxy` 标注「cross-check Fred dxy，非主源」。
- **验收**：FeatureSpec 构造合法（registry 校验过）；单测注册数=7。

### T10 feature_interface 注册 alt，不入 head 子集
- `build_default_registry` 调 `register_alt`；`HEAD_FEATURE_SUBSETS` **不加** alt 特征（R10）。
- **验收**：alt 特征在 registry 可查；`short_sector`/`mid_long` 子集不含 wm_*。

## P6 — chat 工具（R6, A5，可选低优先）

### T11 chat worldmonitor_query + pro key 隔离
- [x] `chat.TOOLS` 加 `worldmonitor_query` 项 + `_exec_tool` 分支（透传 tool name + jmespath）。API/MCP/CLI 三出口同步。
- [x] pro key（`search_intel_history`/`get_intel_timeline`/`get_similar_events` 标 Pro）若启用：存 `VR_DATA_DIR/.vibe-research/worldmonitor_api_key`，env 读，绝不进 git/日志。
- [x] **验收**：离线降级路径通过（2026-08-01，见 `reports/acceptance/S020-2026-08-01-offline-pass.md`）；pro key 不进 git（grep 验证）。
- **优先级**：低于 P3/P4；远程 MCP 新会话已可直调，本任务主要服务自有 AI 层。

## P7 — live 冒烟 + spec 收尾（A7, A8）

### T12 live 冒烟
- `pytest -m live tests/test_s020_worldmonitor.py`：`fetch_market_data` + `fetch_country_risk` + `fetch_news_intelligence` 至少 2 个返非空；`fetch_economic_data_china` 中国宏观确认 PBoC/GACC 仍不可取（诚实记缺口）。
- **验收**：≥2 fetcher 非空；缺口诚实标注。

### T13 live 后纳子集（R10 解除）
- live 冒烟通过 + 评估后，把 alt 特征加入可选 `HEAD_FEATURE_SUBSETS` 子集（仿 S019 R5 流程）；定 `availability_offset`。
- **验收**：子集更新 + 全量回归绿。

### T14 spec 收尾
- `spec.md` R1–R10 / A1–A8 勾选；状态行"草案"→"已实现（P0–P7 完成日期）"。
- **验收**：spec 无未勾选实现项。
