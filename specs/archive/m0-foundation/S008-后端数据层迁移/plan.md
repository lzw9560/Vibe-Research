# Plan: S008 — 后端数据层迁移技术方案

> 对应 `spec.md`。本 plan 细化消费者分组、文件拆分、bug 修复点、适配层退出条件。

## 1. 消费者分组迁移（A→B→C，每组迁完即删该组适配 shape）

### A 组：routers（先迁，挂 response_model）
- `routers/stock_data.py`、`routers/stock_financial.py`、`routers/limitup/{metrics,analysis,screener,auction,seats}.py`、`routers/market.py`
- 迁后挂 `response_model=Quote`/`Valuation`/...；FastAPI `/docs` 显示 schema（S009 codegen 前置就绪）

### B 组：chat/mcp（工具出口）
- `chat._exec_tool`（迁 S010 registry，但本 spec 让 astock 返模型，chat 直接拿模型）
- `gstock`（本身是数据层，与 astock 一起迁）

### C 组：engines（计算层）
- `risk_models`、`portfolio`、`daily_review`、`bidding_monitor`、`auction_screener`、`backtest_lite`、`limitup_strategy`、`limitup_screener/{models,service,data}`、`seat_engine/service`、`candidate_funnel/sources/*`（6 源）、`value_funnel/*`
- `limitup_screener/models.py` 移除 `import astock`，`_numf` 内联或迁 `lib/_numf.py`

**退出条件**：每组消费者全迁完 → 删该组 `to_dict()` shape 转换；不残留。

## 2. 文件拆分

### `data/sources/`（替 astock.py 862 行）
- `tencent.py`（腾讯行情底座）、`eastmoney.py`（研报/龙虎榜/解禁/融资融券/涨停四池/个股新闻，走 `em_get`）、`akshare_src.py`/`mootdx_src.py`（惰性 import）、`sina.py`（财报三表/公告）
- 各 source 函数返回 S007 模型

### `data/transport.py`（替 `em_get` 三合一）
- `em_get(url, ...)`：限流（QPS≤2+抖动）+ 熔断（`get_breaker("eastmoney")`）+ 直连/代理探测（auto/force）三职责拆为组合：`with_rate_limit`+`with_breaker`+`with_proxy_fallback`
- 保留 Session Keep-Alive、`trust_env=False`、短超时 8s 不重试、 latch 整进程

## 3. Bug 修复点（4 个静默失效）

| 位置 | bug | 修法 | 单测 |
|---|---|---|---|
| `risk_models.py:332,351,372` | `astock.get_kline`（实为 `kline`）→ 波动率/回撤/流动性恒 0.0 | 改 `astock.kline(code, ...)`，删 try/except 吞错 | `test_risk_models_kline`：基线 code 返回非 0 |
| `limitup_screener/data.py:178` | 缺 `from datetime import datetime` | 补 import | `test_data_datetime` |
| `chat.py:62-87` | `SYSTEM_PROMPT_NO_TOOLS` 定义两遍（第一份死代码） | 删第一份 | `test_chat_prompt_no_dup` |
| `seat_engine/models.py:38-42` | `_stocks_traded: set = set()` 类变量共享 | `Field(default_factory=set)` | `test_seat_engine_defaults`：两实例不共享 |

## 4. 适配层设计

- `Model.to_dict() -> dict`（或 `data/mappers.legacy_dict(model)` helper）：返回旧 dict 形状（含 `mcap_yi`/`change_pct`/`amount_wan` 等旧名+旧单位），**仅对未迁消费者**保留
- 按 A/B/C 组分别提供 shape，组迁完即删
- 不搞一个 `to_dict` 通吃 32 消费者（评审认定会膨胀）

### 4.1 字段对齐表（mappers 实现，raw→model）

| raw | model 字段 | 单位转换 |
|---|---|---|
| `mcap_yi`(tencent_quote/full_valuation) | `Quote.market_cap` | ×1e8 (亿→元) |
| `mcap`(market_turnover_rank/gstock) | `market_cap` | already 元 |
| `change_pct`/`pct` | `change_pct` | — |
| `float_mcap_yi` | `float_market_cap` | ×1e8 |
| `turnover_pct` | `turnover_rate` | rename |
| `amplitude_pct` | `amplitude` | rename |
| `limit_up`/`limit_down` | `limit_up_price`/`limit_down_price` | — |
| `super_net` | `super_large_net` | — |
| `mid_net` | `medium_net` | — |
| `amount_wan` | `turnover` | ×1e4 (万→元) |
| `lianban_stocks` | （drop，不进 Emotion） | 设计选择剥离 |

### 4.2 设计选择（lianban_stocks 剥离）

`market._emotion()` 现返回 `lianban_stocks`（含 code/name/price/pct）。新口径下连板股榜属公开榜单客观事实，可如实呈现个股 code/name；剥离属设计选择（聚合指标 vs 客观榜单分层，非硬约束）。`Emotion` 模型已省略该字段；mapper 显式丢弃 `lianban_stocks`。若 routers/market 需连板股榜，走 `astock.em_zt_topic_pool` 原始池出口作客观榜单（不含聚合指标）——**用户已确认采用此剥离方案（2026-07-30）**。

## 5. 删除项
- `backend/data_provider/`（空壳，`normalize_stock_code` 已在 S007 `models/normalize.py`）
- `backend/enums.py`（旧 13 行 `ReportType`，已收编到 `models/enums.py`）

## 6. 实现步骤
1. A 组 routers 迁模型 + 挂 response_model（先，供 S009）
2. 修 4 bug + 补单测
3. `data/sources/*` + `data/transport.py` 拆分
4. B 组（chat/gstock）迁
5. C 组 engines 迁（含 limitup_screener/models 移除 import astock）
6. 逐组删 `to_dict` 适配 shape
7. 删 `data_provider/` + 旧 `enums.py`
8. 基线回放 + `pytest -m "not live"` + :8900 冒烟

## 7. 风险点
- 32 消费者迁移期长 → 契约已冻结（S007）+ 分组 + 每消费者迁完即测
- `em_get` 拆 transport 改变调用路径 → 保留限流/熔断语义不变，单测锁住 QPS≤2/熔断开闭
- `risk_models` 删 try/except 后可能暴露其他取数失败 → 基线 code 验证非 0 真实值
