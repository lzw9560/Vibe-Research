# Tasks: S015 — 配置与基础设施

## 任务清单

| ID | 任务 | 依赖 | 验收 |
|---|---|---|---|
| T1 | `config/notification.py` 拆分（通知 30+ 配置） | — | **仅评估未实现**（R1 大改，留给后续 spec；现状评估见 plan.md §9） |
| T2 | `PUSH_CHANNELS`/`PUSH_QUIET_HOURS` 去重 | T1 | **仅评估未实现**（现状：`config.py` 无重复定义——`PUSH_CHANNELS` line 98 / `PUSH_QUIET_HOURS` line 131 各定义一次，仅 30+ 通知字段散落 AssistantDefaultConfig 内，拆分价值在归集非去重） |
| T3 | `_parse_bool`/`_parse_int` 类型校验（失败告警） | T1 | ✅ 完成（`config.py` 加 `_parse_bool`/`_parse_int`/`_parse_float`，失败 `logging.warning` 不静默；`load_config` 改用之；单测 `test_s015_config_validation.py` 9 例过） |
| T4 | 建 `infra/cache.py`（`ttl_cache`，空结果不缓存） | — | **仅设计未实现**（设计草案见 plan.md §9，待审批） |
| T5 | `astock._ztb_cache`/`market._CACHE` 改用 infra/cache | T4 | 未实施（依赖 T4） |
| T6 | 建 `infra/resilience.py`（breaker/rate_limit/with_fallback） | — | 未实施（本任务范围外） |
| T7 | `circuit_breaker.py` 并入 infra/resilience | T6 | 未实施 |
| T8 | `fallback.py` 并入 infra（保留降级语义），删旧文件 | T6 | 未实施 |
| T9 | `em_get`（data/transport）用 breaker+rate_limit+with_fallback | T6,T7,T8 | 未实施 |
| T10 | 🩹修 `app.py cache_response` key（含 path+query params+kwargs） | — | ✅ 完成（`app.py:_cache_key` 新建，含 args+kwargs 稳定 md5 键；有 Request 时用 path+sorted query；单测 `test_s015_cache_response_key.py` 5 例过） |
| T11 | `_metrics_middleware` tier 配置化（TIER_MAP） | — | **仅评估未实现**（当前 app.py:137-148 硬编码 `path.startswith` 链；低风险但本任务范围外，留后续小改） |
| T12 | 路由自动发现（pkgutil.iter_modules） | — | **仅评估未实现**（26+ router 手工 include，重构高回归，仅评估写进 plan；保留 value_funnel try/except 模式） |
| T13 | 单测：cache/resilience/cache_response_key/route_autodiscover | T4-T12 | ✅ 部分完成（cache_response_key + config validation 已写；resilience/route_autodiscover 待 T6/T12 实施后补） |
| T14 | `pytest -m "not live"` + :8900 冒烟 | T13 | ✅ 局部通过（新测 + s003/fixes/market 共 51 例绿；全量 :8900 冒烟留后续） |

## 依赖图
```
T1 ─ T2,T3
T4 ─ T5; T6 ─ T7,T8 ─ T9
T10,T11,T12(并行)
T1-T12 ─ T13 ─ T14
```

## 合规检查点
- 缓存/熔断/降级不引入方向性判断
- 通知 webhook URL 不日志/不进仓
- em_get 仍限流不裸调
