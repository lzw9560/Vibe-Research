# Spec: S104 — hithink 作结构性缺口唯一源（PS/PCF + 异动/飙升/热股榜）

> 状态：已实现(2026-08-30)
> 作者：lzw9560  日期：2026-08-30
> 级别：large（新增外部数据源，subprocess 调 node CLI）
> 分支：`feature/S104-hithink-source`（off develop，squash-merge）
> 关联：grill「坚实数据底座」第 4 层批 1 / 四路审查（财务+特色 P0 结构性零源）

## 1. 问题 / 目标

四路审查 + 实测对账确认：项目有 6 类数据**东财/新浪/腾讯结构性零供给**：
- 估值 PS_TTM / PCF_TTM（`full_valuation` 5 只股实测全 None）
- 异动 / 飞升榜 / 热股榜（后端从无独立源，审查 P0）
- 龙虎榜维度不同（hithink 个股+概念 vs 东财席位明细），**不在本 spec**

hithink-finance CLI（v0.1.7，API Key 已认证）能补且**口径与东财一致**（实测 PE/PB 两源数值一致到小数点后两位：5.20 vs 5.20212、19.92 vs 19.916204）。本 spec 接「东财零供给 + hithink 独家」字段作**唯一源**——唯一源无需 cross_validate 仲裁（无第二源可对比）。PE/PB 两源都有的字段等 cross_validate 接线（第 3 层孤儿）后才接。

## 2. 背景

- hithink 集成形态：node CLI subprocess（非 Python 库）。按需调用冷启动 ~1s（实测 5 只估值批量 1.03s），低频按需源可接受。DuckDB 批量同步路线已否决（全量重下 172M 非增量）。
- 实测：`valuation snapshot --thscodes` 返 PS/PCF 全有值（茅台 PS=9.36、PCF=13.62）；`special skyrocket/hot-stock` 各返 30 条（rank/heat/rank_change/rank_trend）；`anomaly-list` 盘后返空（item=0，正常）。
- thcode 体系：hithink 用 `600519.SH`（带后缀），项目内部用裸 6 位。复用 `data/sources/tencent.py:29` `get_prefix` 做映射。

## 3. 需求清单

- [x] R1 `hithink_src.py` 封装 subprocess 调用，剥 envelope（ok:false → 空不透传）
- [x] R2 thscode 映射（`_to_thscode`/`_strip_thscode`）复用 `get_prefix`
- [x] R3 熔断 `circuit_breaker("hithink")` + subprocess 超时
- [x] R4 `valuation_snapshot` 补 PS_TTM/PCF_TTM（5min TTL 缓存）
- [x] R5 `full_valuation` 调 hithink 补 PS/PCF，失败降级 None（不崩）
- [x] R6 飞升榜/热股榜/异动函数 + AI 工具注册 + 端点接线
- [x] R7 大结果落盘临时文件（`.vibe-research/`，私有数据隔离）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/hithink_src.py` | 新增（subprocess 封装 + thscode 映射 + ok 解析 + 熔断 + 5min 缓存） |
| `backend/astock.py` | `full_valuation` 补 PS_TTM/PCF_TTM（hithink_src 唯一源，失败降级 None） |
| `backend/ai/tools/stock_tools.py` | 新增 3 个 @register_tool（query_skyrocket/query_hot_stock/query_anomaly） |
| `backend/routers/market.py` | 新增 3 端点（/api/market/skyrocket, /hot-stock, /anomaly） |
| `backend/tests/test_s104_hithink_source.py` | 新增 26 用例 |

## 5. 设计方案

### 5.1 hithink_src.py 硬约束（grill 锁定）

1. **ok 字段解析**：hithink 错误是 JSON envelope `{"ok":false,"error":{...}}`，subprocess 退出码恒 0。`_run_cli` 解析 ok，`ok:false` → 返 None（调用方降级空结构），**不透传 error envelope**。
2. **thscode 映射**：`_to_thscode(code) = f"{code}.{get_prefix(code).upper()}"`（600519→600519.SH）；`_strip_thscode` 反映射还原裸 6 位 code。
3. **subprocess 超时**：估值 15s / 特色数据 30s。
4. **熔断**：`get_breaker("hithink")`，OPEN 快速失败不调 subprocess + record_failure。
5. **5min TTL 缓存**：valuation_snapshot 盘中估值不变，省 subprocess 冷启动。
6. **大结果落盘**：超 1000 行用 `--output` 落 `.vibe-research/hithink_cache/`（私有数据隔离）。

### 5.2 full_valuation 降级

`full_valuation` 调 `valuation_snapshot([code])` 补 PS/PCF。hithink 失败/熔断 → PS/PCF 仍 None（东财本来也 None，诚实缺失不崩）；PE/PB 仍走东财腾讯行情口径不变。`try/except` 包 hithink 调用，任何失败不阻塞估值主流程。

### 5.3 AI 工具 + 端点

异动/飞升/热股榜是新数据域（项目从零）：
- `@register_tool` 注册 → AI 三出口（chat/MCP/cli_runtime）自动获得（复用 `chat.TOOLS = registry.get_openai_tools()`）。
- `/api/market/skyrocket` 等端点返 `{"data":..., "source":"hithink"}`（显式标源，§44 口径诚实）。
- **不做前端页面**（YAGNI，前端另立 spec）。

## 6. 验收标准

- [x] A1 `valuation_snapshot(["600519","000001"])` 返 PS/PCF 非空（实测茅台 PS=9.36、PCF=13.62）
- [x] A2 thscode 映射：600519→SH / 000001→SZ / 830xxx→BJ（7 用例全过）
- [x] A3 hithink `ok:false` → 返空 dict/list，不透传 error envelope
- [x] A4 subprocess 超时 → 返空不崩 + record_failure；熔断 OPEN 快速失败不调 subprocess
- [x] A5 `full_valuation("600519")` 返 ps_ttm=9.36/pcf_ttm=13.62（hithink 补上），pe/pb 仍东财腾讯口径
- [x] A6 hithink 失败时 full_valuation 降级返 ps_ttm=None（不崩，东财本来也 None）
- [x] A7 `query_skyrocket`/`query_hot_stock`/`query_anomaly` 三工具注册（总工具数 9→12）
- [x] A8 `/api/market/skyrocket`(len=30)/`/hot-stock`(len=30)/`/anomaly`(len=0 盘后) 端点 200 返数据

## 7. 合规与工程底线自查

- [x] 不臆造：hithink 失败返空/None，诚实缺失
- [x] 私有数据隔离：大结果落盘 `.vibe-research/hithink_cache/`（不进 git）
- [x] em_get 防封：hithink 走自己熔断器 `get_breaker("hithink")`，不碰东财 em_get
- [x] §44 口径：PS/PCF 唯一源无需仲裁；端点显式标 `source:"hithink"`，不混口径
- [x] thscode 映射复用 get_prefix，不臆造后缀推断

## 8. 测试计划

- **单测** 26 用例全 PASS（thscode 映射 11 + _run_cli envelope 5 + valuation_snapshot 4 + 特色数据 3 + full_valuation 集成 2 + AI 工具注册 1）
- **真实冒烟**：valuation_snapshot(5 只) PS/PCF 全有值；skyrocket/hot-stock 各 30 条；full_valuation(600519) PS=9.36/PCF=13.62；3 端点 TestClient 200
- **全量 gate**：`pytest -m "not live" --deselect newsradar --deselect test_s032_refresh_loop`（待跑）

## 9. 风险与回滚

- **风险 1**：`full_valuation` 加 hithink subprocess ~1s 延迟。**缓解**：5min TTL 缓存。
- **风险 2**：hithink 远端断流。**缓解**：熔断器 + 降级返 None。
- **风险 3**：异动盘后返空。**诚实**：盘后异动本就少，返空正常。
- **回滚**：`full_valuation` 删 hithink_src 调用即退回（PS/PCF 回 None）；hithink_src.py 删文件不影响其他源。

## 10. 冲突审查表

无历史 spec 冲突。hithink 是新增数据源，不改现有东财/腾讯/新浪源逻辑（`full_valuation` 只增补 PS/PCF 两字段，PE/PB 走原口径不变）。

## 11. 不在本 spec 范围

- PE/PB 交叉验证（等 cross_validate 接线，第 3 层孤儿）
- 龙虎榜 hithink 集成（维度不同，互补不替代，另立评估）
- 异动/飞升/热股榜前端页面（前端 spec）
- 缓存治理全铺（datacenter/tencent，第 1 层后续切片）
