# Spec: S015 — 配置与基础设施（config 拆分 + infra 收口 + 路由自动发现）

> 状态：草案
> 作者：Claude  日期：2026-07-29
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 9 步）、`../S008`（data/transport 建 em_get 拆分，本 spec 建 infra 收口缓存/熔断）、`../S011`（app.py lifespan 在 S011）、`../../ARCHITECTURE.md`

---

## 1. 问题 / 目标

`config.py`(244) 通知 30+ 配置集中，`PUSH_CHANNELS`/`PUSH_QUIET_HOURS` 重复定义，类型转换静默失败无校验。4+ 套缓存/限流/熔断并存（`astock._ztb_cache` 24h、`market._CACHE` 5min、`fallback.py` 内存+文件双缓存、`circuit_breaker` 全局注册表、`risk_models` 又用 `get_with_fallback`），键/TTL/失效策略各不同，无统一接口。`app.py` `cache_response` 的 key 未含 query params（不同 code 撞缓存）；`_metrics_middleware` tier 分类硬编码；26+ router 手工 `include_router`。

**目标**：config 拆分 + 类型校验；`infra/cache.py`+`infra/resilience.py` 收口 4+ 套缓存/限流/熔断为单一抽象（保留 fallback 降级语义）；修 cache_response key；metrics tier 配置化；路由自动发现。

## 2. 背景

- `circuit_breaker.get_breaker("eastmoney")` 全局注册表；`em_get` 限流/熔断/代理三合一（S008 拆到 `data/transport.py`）。
- `fallback.py` 的 `get_with_fallback` 是"降级取回退值"语义，非纯 TTL 缓存——合并须保留该语义。
- `app.py:42-43` 手工 import 26+ router + include_router。

## 3. 需求清单

- [ ] R1 `config.py` 通知 30+ 配置拆到 `config/notification.py`；`PUSH_CHANNELS`/`PUSH_QUIET_HOURS` 去重
- [ ] R2 类型转换加校验（`_parse_bool`/`_parse_int` 失败告警，不静默）
- [ ] R3 建 `backend/infra/cache.py`：统一 TTL 缓存接口（收口 `astock._ztb_cache`/`market._CACHE`/`fallback` 文件缓存）
- [ ] R4 建 `backend/infra/resilience.py`：统一熔断+限流+降级抽象（收口 `circuit_breaker` + `em_get` 限流/代理 + `fallback` 的 get_with_fallback 降级语义）
- [ ] R5 🩹修 `app.py cache_response` key：含 path + query params + kwargs
- [ ] R6 `_metrics_middleware` tier 分类配置化（tier 映射表）
- [ ] R7 路由自动发现：`pkgutil.iter_modules(routers)` 自动 include 有 `router` 属性的模块，替手工 `include_router`
- [ ] R8 `fallback.py` 合并到 infra 后删除（保留 get_with_fallback 语义在 resilience）
- [ ] R9 数据源故障的空结果不缓存（保留 market 现有行为）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/config.py` | ✏️拆分+去重+类型校验 |
| ➕`backend/config/notification.py` | ➕通知配置 |
| ➕`backend/infra/cache.py`/`infra/resilience.py` | ➕统一缓存/熔断/限流/降级 |
| `backend/circuit_breaker.py` | ✏️/🗑️并入 infra/resilience |
| `backend/fallback.py` | 🗑️并入 infra（保留降级语义） |
| `backend/astock.py`/`market.py`/`risk_models.py` | ✏️改用 infra 抽象（S008 已动，本 spec 换缓存实现） |
| `backend/app.py` | ✏️🩹cache_response key+metrics 配置化+路由自动发现 |

## 5. 设计方案

- **infra/cache.py**：`ttl_cache(key, ttl, factory)` 装饰器/函数，统一 TTL + 空结果不缓存语义；`astock._ztb_cache`/`market._CACHE` 改用它。
- **infra/resilience.py**：`breaker(name)` 熔断 + `rate_limit(qps)` 限流 + `with_fallback(primary, fallback)` 降级取回退值。`em_get`（S008 拆到 transport）用这套；`fallback.get_with_fallback` 的降级语义并入 `with_fallback`。
- **路由自动发现**：`pkgutil.iter_modules` 遍历 `routers/`，有 `router` 属性即 include；`value_funnel` 半成品 try/except 保留。
- **取舍**：不引入第三方缓存库（Redis 等），内存缓存够用；保留 circuit_breaker 全局注册表语义在 resilience。

## 6. 验收标准

- [ ] A1 `config.py` 通知配置拆到 `config/notification.py`；无重复定义；类型转换失败有告警
- [ ] A2 `infra/cache.py` 统一 TTL 缓存；`astock`/`market`/`risk_models` 改用之；空结果不缓存
- [ ] A3 `infra/resilience.py` 统一熔断+限流+降级；`fallback.get_with_fallback` 语义保留
- [ ] A4 `circuit_breaker.py`/`fallback.py` 已并入 infra（或保留薄封装）
- [ ] A5 `cache_response` key 含 path+query params；不同 code 不撞缓存（单测）
- [ ] A6 `_metrics_middleware` tier 配置化
- [ ] A7 路由自动发现：新增 router 无需改 app.py 即挂载
- [ ] A8 `pytest -m "not live"` 全过；:8900 端点行为不变
- [ ] A9 限流语义不变（QPS≤2、直连优先失败降级代理、熔断快速失败）

## 7. 合规自查（按新 CLAUDE.md §1）

- [ ] 缓存/熔断/降级不引入方向性判断
- [ ] 路由自动发现不影响合规端点
- [ ] 配置拆分不涉及私有数据（通知 webhook URL 仍不日志、不进仓）
- [ ] 东财端点仍走 em_get（经 infra/resilience）

## 8. 测试计划

- 单测：test_cache（TTL/空结果不缓存）、test_resilience（熔断开闭/限流/降级取回退）、test_cache_response_key（不同 code 不撞）、test_route_autodiscover
- `pytest -m "not live"` 全量
- live：:8900 路由全挂载、限流/熔断行为

## 9. 风险与回滚

- 🟡 合并缓存/熔断改动面广（astock/market/risk_models）：保留旧接口薄封装过渡
- 🟡 fallback 降级语义丢失风险：`with_fallback` 单测锁住"主源失败取回退值"
- 🟡 路由自动发现可能挂载半成品：`value_funnel` try/except 保留；新增 `_` 前缀模块跳过
- 🟢 回滚：恢复各套独立缓存/circuit_breaker
