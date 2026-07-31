# Spec: S020 — worldmonitor 决策因子接入（全球宏观/地缘/另类数据）

> 状态：P0-P5 已实现（2026-07-31，31 离线单测绿）；P7 live 冒烟被网络阻断（worldmonitor.app 在公司网+远程 ecs 均不可达，fetcher 正确降级 None）；P6 chat/P7 纳子集待网络可用后补
> 作者：Claude  日期：2026-07-31
> 关联：`../S019-macro-Fred-API/spec.md`（美债/DXY 主源，本 spec 对其仅交叉验证）、`../S018-多源特征工程/spec.md`（特征注册表）、`../S017-A股涨跌预测模型栈/spec.md`（模型栈）、`../S008-后端数据层迁移/spec.md`（数据源层 transport/sources/mappers）、`../../CLAUDE.md` §1.2/§3
>
> 探路已验证：`worldmonitor` 远程 MCP 已挂入 local scope（`claude mcp add --transport http --scope local`），`claude mcp list` ✔ Connected，59 工具。endpoint `https://worldmonitor.app/mcp`，streamable HTTP，MCP 2025-06-18，server v1.15.0。每工具支持 `jmespath` 投影（80–95% token 缩减）。

## 1. 问题 / 目标

现有数据层以 A股/中文资讯为主：`newsradar.py` 抓 12 赛道 108 个 RSS（中文为主）、`astock.py` 东财通道、`gstock.py` 美港股。**缺全球宏观/地缘/另类维度**——美债/DXY 已由 S019 Fred API 补，但地缘风险（CII）、商品、关税、航运压力、全球资讯聚类、热点升级等仍空白。这些是港股/美股风险情绪与 A股大盘择时的外生因子。

worldmonitor（koala73/worldmonitor，AGPL-3.0，77.1k★）聚合 65+ 外部源、500+ 资讯、CII 31 国不稳定指数、Finance Radar（29 交易所/商品/加密/外汇）、跨源关联。其远程 MCP 已可直连。

**目标**：把 worldmonitor 作为**互补另类数据层**接入现有模块（newsradar/market/特征栈），丰富决策因子；**不替代** Fred（S019）对美债/DXY 的主源地位，仅作交叉验证。定位为后续优化，非阻塞当前 S008/S017 主线。

## 2. 背景

- **现有模块结构**（来自实测）：
  - `backend/newsradar.py`：12 赛道 108 RSS，纯标准库 + 线程池，零 key、零个股字段；`news_sources.json` 配置源，`.cache/radar.json` 缓存；AI「今日要点」走 `/api/chat` 不在本模块。
  - `backend/market.py`：市场情绪 + 板块资金流，`_cached(key, fn, valid)` TTL 5min 模式，依赖 `astock`/`gstock`。
  - `backend/chat.py`：`TOOLS`（line 76）+ `_exec_tool`（line 165），§3 三出口（API/MCP/CLI）共用，新增工具加项即同步。
  - `backend/data/transport.py`（S008）：`circuit_breaker.get_breaker(...)` + 限流/代理探测，东财走 `em_get`；国外源（Fred）走独立通道。
  - `backend/predict/features/`（S018）：`FeatureSpec` 注册表 + `feature_interface.py` 消费 + `HEAD_FEATURE_SUBSETS` 控制入头子集。
- **worldmonitor 探出的 59 工具中本项目相关 14 个**（见 `memory/worldmonitor-mcp-integration.md`）：`get_market_data` / `get_country_risk`(CII) / `get_news_intelligence`(GDELT) / `get_news_clusters` / `get_keyword_spikes` / `get_economic_data`(中国宏观 12 序列，PBoC/GACC 不可取) / `get_country_macro`(IMF WEO) / `get_company_intelligence`(SEC EDGAR) / `get_forecast_predictions`+`get_forecast_scorecard`(Brier/log 校准) / `get_tariff_trends` / `get_supply_chain_data`(干散货航运压力) / `get_energy_intelligence`(EIA) / `get_china_decision_signals` / `get_hotspot_escalation`。
- **合规定位**（CLAUDE.md §1.2 弱合规）：worldmonitor 输出宏观/地缘客观数据，不预置标的、不推荐，天然不触仪式红线；工程底线（可复现/私有隔离/防封）必过。AGPL-3.0：消费 API/SDK 不触发 copyleft，**勿 vendor 源码**。

## 3. 需求清单

- [ ] R1 新增 `backend/data/sources/worldmonitor.py`：封装 worldmonitor HTTP MCP 调用为 fetcher 函数（market_data / country_risk / news_intelligence / news_clusters / economic_data_china / country_macro / tariff_trends / supply_chain / energy / china_decision_signals / hotspot_escalation）。每个 fetcher 支持 `jmespath` 投影降 token。
- [ ] R2 传输层：worldmonitor 走**独立通道**（非 `em_get`，与 S019 Fred 同构），复用 `backend/data/transport.py` 的 `get_breaker("worldmonitor")` 熔断 + 限流；失败/无 key 返 None，不臆造。
- [ ] R3 缓存：CII/热点/地缘 24h（慢变）；market_data 5min（对齐 `market.py` `_TTL`）；资讯聚类 1h。空结果不缓存（对齐 `market._cached` 的 `valid` 判否重试）。
- [ ] R4 接入 `newsradar.py`：新增「全球情报」赛道，聚合 worldmonitor `get_news_intelligence` + `get_news_clusters`（GDELT + 跨源信号），与现有 108 RSS 并列分组输出；**守零个股字段、客观措辞**，AI 提炼仍走 `/api/chat`。
- [ ] R5 接入 `market.py`：在市场总览加「全球宏观/地缘」分块——商品(金/油/铜)、外汇(DXY/USD-CNH)、CII、热点升级；复用 `_cached` TTL 模式；不与东财板块资金流混排。
- [ ] R6 接入 `chat.TOOLS`（§3 三出口同步）：加 `worldmonitor_query` 工具项 + `_exec_tool` 分支（透传 tool name + jmespath）；API/MCP/CLI 自动获得。**注**：远程 MCP `worldmonitor` 在新会话已自动可被 Claude Code 直调，此项主要服务 `/api/chat` 自有 AI 层，优先级低于 R4/R5。
- [ ] R7 特征注册（S018）：`backend/predict/features/alt.py`（或扩 macro.py）注册 worldmonitor 派生特征——`wm_cii_global`、`wm_hotspot_escalation`、`wm_dry_bulk_stress`、`wm_tariff_stress`、`wm_commodity_oil`、`wm_commodity_copper`、`wm_dxy`（**交叉验证 Fred 的 `dxy`**，不作主源）。FeatureSpec 标 `source=worldmonitor, category=alt`，`availability_offset` 待 live 冒烟后定。
- [ ] R8 可复现底线：fetcher 返回**原始公开 feed**（价格/事件/指标值）为主；CII/合成分/forecast 标注 `source=worldmonitor_composite`，只作输入之一，不作唯一依据。解析为纯函数（入参 JSON → 出参 dict），可单测。
- [ ] R9 私有隔离：pro key（`search_intel_history`/`get_intel_timeline`/`get_similar_events` 标 Pro）若启用，存 `VR_DATA_DIR/.vibe-research/worldmonitor_api_key`，env 读，绝不进 git、不打日志。
- [ ] R10 live 冒烟通过前，worldmonitor 派生特征**不加入** `HEAD_FEATURE_SUBSETS`（对齐 S019 R5 纪律）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/data/sources/worldmonitor.py` | MCP fetcher + 纯解析函数 + jmespath 投影 |
| ➕`backend/tests/test_s020_worldmonitor.py` | 解析单测（离线，mock JSON）+ live 冒烟（`-m live`）|
| `backend/data/transport.py` | 加 `get_breaker("worldmonitor")` + 限流配置（若未通用化）|
| `backend/newsradar.py` | 加「全球情报」赛道：聚合 worldmonitor 资讯聚类，并入分组输出 |
| `backend/news_sources.json` | （如走赛道配置）加 worldmonitor 赛道元数据 |
| `backend/market.py` | 加「全球宏观/地缘」分块：商品/外汇/CII/热点，复用 `_cached` |
| `backend/chat.py` | `TOOLS` 加 `worldmonitor_query` 项 + `_exec_tool` 分支（R6，可选）|
| ➕`backend/predict/features/alt.py` | worldmonitor 派生特征 FeatureSpec 注册（R7）|
| `backend/predict/feature_interface.py` | live 冒烟通过后才把 alt 特征纳入可选子集（R10）|

## 5. 设计方案

- **独立通道 + 熔断**：worldmonitor 属国外源，不混入 `em_get`，与 S019 Fred 同构——直接 `requests`/`httpx` POST JSON-RPC 到 `https://worldmonitor.app/mcp`，可读 `VR_HTTP_PROXY` 走代理；`get_breaker("worldmonitor")` 熔断防封。失败降级返 None。
- **jmespath 投影**：每次调用按需传 `jmespath` 只取必要字段，服务端 80–95% token 缩减（成本友好，借鉴 worldmonitor 自身设计）。
- **newsradar 集成取舍**：不把 worldmonitor 当第 109 个 RSS 源（它是结构化情报非 RSS），而是新增并列的「全球情报」分组，输出 `[{title, summary, source:worldmonitor, category, ts}]`，与 12 赛道同构分组、时间倒序。守零个股字段。
- **market 集成取舍**：不与东财板块资金流混排（不同语义），单独「全球宏观/地缘」分块，前端可独立渲染。
- **不选方案**：①不 vendor worldmonitor 源码（AGPL 风险 + 体积）；②不 fork（无意义）；③美债/DXY 不作主源（S019 Fred 已主，worldmonitor 仅 cross-check）。
- **备选**：若 worldmonitor 限流严或 pro 门槛高，退化为「只接 R4 资讯 + R5 商品/CII」最小集，R7 特征栈延后。

## 6. 验收标准

- [ ] A1 `worldmonitor.py` fetcher + 纯解析函数齐，`pytest -m "not live" test_s020_worldmonitor.py` 全绿（解析单测，mock JSON）。
- [ ] A2 `get_breaker("worldmonitor")` 熔断 + 限流 + 缓存 TTL（24h/5min/1h）接入，空结果不缓存。
- [ ] A3 `newsradar.py` 「全球情报」赛道输出零个股字段、与现有赛道同构，单测过。
- [ ] A4 `market.py` 「全球宏观/地缘」分块复用 `_cached`，单测过。
- [ ] A5 `chat.TOOLS` 加 `worldmonitor_query`（R6 可选），`/api/chat` 工具列表含该项。
- [ ] A6 alt 特征 FeatureSpec 注册，但 live 冒烟前**不在** `HEAD_FEATURE_SUBSETS`（对齐 S019 R5）。
- [ ] A7 live 冒烟（`pytest -m live`，需网络）：`get_market_data`+`get_country_risk`+`get_news_intelligence` 至少 2 个返非空。
- [ ] A8 可复现：解析纯函数单测覆盖；合成分标注 `source=worldmonitor_composite`；`financial_rigor.py` 对涉及市值/估值的世界monitor 数据交叉验算（若用到）。

## 7. 合规自查（§1.2 弱合规——仅核查工程底线）

- [x] 工程底线·不臆造：fetcher 失败/无 key 返 None，不编造数据（R2/R8）
- [x] 工程底线·私有隔离：pro key 存 `VR_DATA_DIR`，env 读，不进 git、不打日志（R9）
- [x] 工程底线·防封：独立通道 + 熔断 + 限流 + 缓存，非裸调、非 em_get（R2/R3）
- [x] 工程底线·可复现：原始公开 feed 为主，合成分标注来源、作输入之一不作唯一依据（R8）
- [x] AGPL-3.0：只消费 API/SDK，不 vendor 源码
- [x] 仪式类（弱合规降级）：worldmonitor 出宏观/地缘客观数据，不预置标的/不推荐/不预测涨跌，天然不触红线
- [x] 涨停四池零个股名规则未被破坏（本 spec 不动四池）

## 8. 测试计划

- 离线快测：`cd backend && .venv/Scripts/python.exe -m pytest -m "not live" test_s020_worldmonitor.py`（解析纯函数 + 缓存 TTL + 熔断 mock）。
- live 冒烟（需网络 + 可选 pro key）：`pytest -m live`——`get_market_data`/`get_country_risk`/`get_news_intelligence` 返非空；`get_economic_data` 中国宏观确认 PBoC/GACC 仍不可取（诚实记录缺口）。
- 手动：前端「全球情报」赛道 + 「全球宏观/地缘」分块渲染核对；`/api/chat` 工具列表含 `worldmonitor_query`（R6）。

## 9. 风险与回滚

- **限流/pro 门槛**：worldmonitor.app 可能限流或部分工具需 pro key → 退化为 R4+R5 最小集，R7 延后。
- **token 成本**：59 工具响应大 → 强制 `jmespath` 投影 + 缓存控成本；不用 jmespath 的调用禁入 `/api/chat`。
- **AGPL 误用**：若有人误 vendor 源码 → code review 拦截（只消费 API）。
- **数据漂移**：worldmonitor server 升级（现 v1.15.0）可能改工具 schema → fetcher 解析容错（缺字段返 None）+ 单测固定样本。
- **回滚**：worldmonitor MCP 已在 local scope，`claude mcp remove worldmonitor` 即净卸载；`worldmonitor.py`/alt 特征独立文件，删之无副作用（live 冒烟前不入 HEAD_FEATURE_SUBSETS，删特征不影响模型栈）。

## 10. 状态与优先级

**草案。后续优化、非必须、非阻塞**——不抢 S008 T17 live / S017 T16 当前主线。待主线收敛后或决策因子扩展需求明确时再启动实现。探路成果（MCP 已挂、59 工具映射、记忆已记）已沉淀，启动成本极低。
