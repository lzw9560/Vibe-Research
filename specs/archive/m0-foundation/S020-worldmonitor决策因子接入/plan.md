# Plan: S020 — worldmonitor 决策因子接入

> 状态：草案 → 实施 plan（待启动；非阻塞 S008/S017 主线）
> 作者：Claude  日期：2026-07-31
> 关联：`spec.md`、`../S019-macro-Fred-API/`（Fred 主源，本 spec 交叉验证）、`../S018-多源特征工程/`、`../S008-后端数据层迁移/`

---

## 1. 目标重述

把 worldmonitor 远程 MCP（已挂 local scope，59 工具，endpoint `https://worldmonitor.app/mcp`）作为**互补另类数据层**接入：全球宏观/地缘/另类维度（CII、商品、关税、航运、资讯聚类、热点升级），丰富 newsradar/market/特征栈决策因子。**不替代** Fred（S019）美债/DXY 主源，仅交叉验证。定位后续优化、非阻塞。

## 2. 设计方案（锁定）

### 2.1 独立通道 + 熔断（R2）
- worldmonitor 属国外源，**不混入 `em_get`**，与 S019 Fred 同构：`data/sources/worldmonitor.py` 内用 `requests`/`httpx` 直接 POST JSON-RPC 到 `https://worldmonitor.app/mcp`。
- 复用 `circuit_breaker.get_breaker("worldmonitor")`（5 失败 OPEN / 60s 恢复）；读 `VR_HTTP_PROXY` 走代理。失败/无 key 返 None，不臆造。
- 传输层改动：`data/transport.py` 若 breaker 工厂已通用（`get_breaker(name)` 按 name 隔离），则无需改 transport，只在 worldmonitor.py 调 `get_breaker("worldmonitor")`。**T1 先确认 `circuit_breaker.get_breaker` 是否按 name 隔离**（若是，transport 零改动）。

### 2.2 MCP JSON-RPC 客户端 + jmespath 投影（R1, R8）
- `_post_mcp(tool, arguments, jmespath=None) -> dict | None`：构造 `{jsonrpc:"2.0", id, method:"tools/call", params:{name:tool, arguments:{**arguments, jmespath:jmespath}}}`（jmespath 嵌入 arguments，服务端投影，80–95% token 缩减）。
- 11 个 fetcher（薄封装）：`fetch_market_data / fetch_country_risk / fetch_news_intelligence / fetch_news_clusters / fetch_economic_data_china / fetch_country_macro / fetch_tariff_trends / fetch_supply_chain / fetch_energy_intelligence / fetch_china_decision_signals / fetch_hotspot_escalation`。每个接 `jmespath` 参数。
- **纯解析函数**（无 I/O，可单测）：`parse_market_data / parse_country_risk / parse_news_clusters / parse_news_intelligence / parse_hotspot_escalation / parse_supply_chain` 等，入参 JSON → 出参结构化 dict/list。合成分标注 `source="worldmonitor_composite"`，只作输入之一。

### 2.3 缓存 TTL（R3）
- `worldmonitor.py` 内模块级缓存（对齐 `market._cached` 语义）：CII/热点/地缘 24h；market_data 5min；资讯聚类 1h。**空结果不缓存**（valid 判否重试）。
- 实现一个 `_cached_wm(key, ttl, fn)` 薄包装（仿 `market._cached`）。

### 2.4 newsradar 全球情报赛道（R4）
- `newsradar.py` `fetch_radar` 返回 `industries: [{key, name, accent, items}]`。**新增并列赛道**「全球情报」（不把 worldmonitor 当第 109 个 RSS——它是结构化情报）。
- 输出 item 同构：`{title, summary, source:"worldmonitor", category, ts}`，时间倒序，**守零个股字段、客观措辞**。AI 提炼仍走 `/api/chat`（本模块不做）。
- 取舍：worldmonitor 赛道单独 fetched 后 merge 进 `industries`，复用现有排序/缓存。

### 2.5 market 全球宏观/地缘分块（R5）
- `market.py` 加 `get_global_macro() -> dict`：商品（金/油/铜）、外汇（DXY/USD-CNH）、CII、热点升级。复用 `_cached(key, fn, valid)` TTL 5min。
- **不与东财板块资金流混排**（不同语义），单独分块，前端可独立渲染。

### 2.6 alt 特征注册（R7, R10）
- `predict/features/alt.py`：FeatureSpec 注册 7 特征——`wm_cii_global / wm_hotspot_escalation / wm_dry_bulk_stress / wm_tariff_stress / wm_commodity_oil / wm_commodity_copper / wm_dxy`（cross-check Fred dxy，source=worldmonitor, category=alt）。
- `feature_interface.build_default_registry` 注册 alt；**live 冒烟前不入 `HEAD_FEATURE_SUBSETS`**（对齐 S019 R5 纪律）。`availability_offset` 待 live 冒烟后定（先标占位）。

### 2.7 chat 工具（R6，可选低优先）
- `chat.TOOLS` 加 `worldmonitor_query` 项 + `_exec_tool` 分支（透传 tool name + jmespath）。主要服务 `/api/chat` 自有 AI 层；远程 MCP 在新会话已可被 Claude Code 直调，故优先级低于 R4/R5。

## 3. 分阶段

| 阶段 | 内容 | 对应 R/A |
|---|---|---|
| P0 | 数据源层：`worldmonitor.py` MCP 客户端 + 11 fetcher + transport breaker 确认 | R1, R2, A1, A2 |
| P1 | 缓存 TTL：`_cached_wm` 24h/5min/1h，空不缓存 | R3, A2 |
| P2 | 纯解析函数 + 离线单测（mock JSON） | R8, A1, A8 |
| P3 | newsradar 全球情报赛道 | R4, A3 |
| P4 | market 全球宏观/地缘分块 | R5, A4 |
| P5 | alt.py 特征注册（不入 head 子集） | R7, A6, R10 |
| P6 | chat worldmonitor_query（可选） | R6, A5 |
| P7 | live 冒烟 + spec 收尾 | A7, A8 |

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/data/sources/worldmonitor.py` | MCP 客户端 + 11 fetcher + 纯解析 + 缓存 |
| `backend/data/transport.py` | （仅当 breaker 非 name 隔离时）通用化 `get_breaker` |
| ➕`backend/predict/features/alt.py` | 7 alt FeatureSpec |
| `backend/predict/feature_interface.py` | 注册 alt；live 冒烟前不入 head 子集 |
| `backend/newsradar.py` | 加「全球情报」赛道 |
| `backend/market.py` | 加 `get_global_macro` 分块 |
| `backend/chat.py` | （P6 可选）TOOLS 加 worldmonitor_query |
| ➕`backend/tests/test_s020_worldmonitor.py` | 离线解析单测 + live 冒烟 |

## 5. 退出条件

- A1 离线解析单测全绿；A2 熔断+限流+缓存 TTL 接入；A3 newsradar 全球情报赛道零个股字段；A4 market 分块复用 _cached；A6 alt 注册但 live 前不入 head 子集；A7 live 冒烟 ≥2 fetcher 返非空；A8 解析纯函数单测覆盖 + 合成分标注。
- live 冒烟通过后才把 alt 特征纳入可选子集（R10）。

## 6. 风险与回滚

- 🟡 限流/pro 门槛 → 退化为 R4+R5 最小集，R7 延后。
- 🟡 token 成本 → 强制 jmespath 投影 + 缓存；无 jmespath 的调用禁入 /api/chat。
- 🟢 回滚：worldmonitor.py/alt.py 独立文件，删之无副作用（live 前不入 head 子集，删特征不影响模型栈）。MCP 已在 local scope，`claude mcp remove worldmonitor` 净卸载。
