# Plan: S015 — 配置与基础设施技术方案

> 对应 `spec.md`。细化 config 拆分、infra 收口、cache_response 修、路由自动发现。

## 1. config 拆分

- `config.py` 通知 30+ 配置 → `config/notification.py`（飞书/钉钉/邮件/discord/slack/telegram… 各 sender 配置）
- `PUSH_CHANNELS`/`PUSH_QUIET_HOURS` 去重（当前定义两遍）
- 类型校验：
```python
def _parse_bool(key, default=False) -> bool:
    v = os.getenv(key)
    if v is None: return default
    if v.lower() in ("true","1","yes"): return True
    if v.lower() in ("false","0","no"): return False
    logging.warning("无效 bool %s=%s，用默认 %s", key, v, default); return default
```
- `config.py` 留核心（API key/CORS/数据源/AI 兜底），通知拆出

## 2. infra/cache.py（统一 TTL 缓存）

```python
def ttl_cache(key: str, ttl: float, factory: Callable, *, cache_empty=False):
    """TTL 缓存；cache_empty=False 时空结果不缓存（保留 market 行为）"""
```
- 收口 `astock._ztb_cache`(24h)/`market._CACHE`(5min)/`fallback` 文件缓存
- 空结果不缓存（数据源故障下次重试）；线程安全（Lock）

## 3. infra/resilience.py（统一熔断+限流+降级）

```python
def breaker(name: str) -> Breaker: ...        # 收编 circuit_breaker
def rate_limit(qps: float): ...              # 收编 em_get 限流
def with_fallback(primary, fallback_fn): ... # 收编 fallback.get_with_fallback 降级语义
```
- `em_get`（S008 拆到 data/transport）用 `breaker("eastmoney")`+`rate_limit(2)`+`with_fallback`
- **保留 fallback 降级语义**：主源失败取回退值（非纯缓存）
- `circuit_breaker.py`/`fallback.py` 并入后删，或保留薄 re-export 过渡

## 4. cache_response 修 key

```python
cache_key = hashlib.md5(json.dumps({
    "path": request.url.path,
    "params": sorted(request.query_params.multi_items()),
    "kwargs": kwargs
}, default=str, sort_keys=True).encode()).hexdigest()
```
- 含 path + query params + kwargs；不同 code 不撞

## 5. 路由自动发现

```python
import pkgutil, importlib, pathlib
def _register_routers(app):
    for _, name, _ in pkgutil.iter_modules([str(pathlib.Path(routers.__path__[0]))]):
        if name.startswith("_"): continue
        mod = importlib.import_module(f"routers.{name}")
        if hasattr(mod, "router"): app.include_router(mod.router)
```
- `value_funnel` 半成品 try/except 保留；替手工 `app.py:42-43` 26+ include_router

## 6. metrics tier 配置化

```python
TIER_MAP = [("/api/limitup","compute"),("/api/recommendation","compute"),("/api/strategy","compute"),
            ("/api/metrics","api_response")]
def _tier(path): return next((t for pfx,t in TIER_MAP if path.startswith(pfx)), "data_fetch")
```

## 7. 实现步骤
1. config/notification.py 拆分 + 去重 + 类型校验
2. infra/cache.py + 各处改用
3. infra/resilience.py + circuit_breaker/fallback 并入
4. cache_response key 修 + 单测
5. 路由自动发现
6. metrics tier 配置化
7. `pytest -m "not live"` + :8900 冒烟

## 8. 风险点
- 缓存/熔断合并改动面广 → 旧接口薄 re-export 过渡
- fallback 降级语义丢失 → with_fallback 单测锁住
- 路由自动发现挂半成品 → `_` 前缀跳过 + value_funnel try/except

## 9. infra/cache.py 设计草案（R3 — 仅设计不实现，待审批）

> 状态：**草案，未实现**。本节为收口 4+ 套 TTL 缓存为统一接口的设计提案，
> 不改动现有代码。审批后再按迁移顺序实施。

### 9.1 现状对照（已审计的实际代码）

| # | 现存缓存 | 文件:行 | TTL | 键 | 空结果是否缓存 | 备注 |
|---|---|---|---|---|---|---|
| C1 | `data/sources/eastmoney.py:_ztb_cache` | 127-153 | 24h (86400) | `(endpoint, date, sort)` tuple | **否**（line 153 存空 list 后仍写入，故障下次重试） | 涨停板原始池 |
| C2 | `market.py:_CACHE` | 17-30 | 5min (300) | str key | **否**（`valid` 谓词判否不写） | 全站共享，省数据源压力 |
| C3 | `fallback.py:_MEM_CACHE` + 文件缓存 | 16-58 | 1h (3600) | str key | **是**（save_cache 直接写） | 降级缓存：故障值也写，作为下次兜底 |
| C4 | `app.py:_RESPONSE_CACHE`（cache_response） | 210-233 | 默认 300s | md5(func + args + kwargs / path+query) | **是** | 路由级响应缓存（R5 已修 key） |
| C5 | `routers/stock_data.py`/`stock_financial.py` `_DC_CACHE/_PCT_CACHE/_ANN_CACHE/_FIN_CACHE` | stock_data 23-113 | 内联 TTL | str/tuple | 是 | 端点内本地缓存 |
| C6 | `routers/risk.py:_DASHBOARD_CACHE` | 16-28 | 120s | str | 是 | 因 app 导入早于 cache_response 定义，本地兜底 |
| C7 | `limitup_screener/service.py:_CACHE`/`_RESOLVED_DATE_CACHE` | 33-74 | 12h (43200) | str | 是 | 涨停筛选结果 |
| C8 | `sector_divergence.py:_DIVERGENCE_CACHE` | 235-248 | 内联 | str | 是 | 板块发散 |
| C9 | `extreme_market_detector.py:_EXTREME_CACHE` | 161-174 | 内联 | str | 是 | 极端市场 |
| C10 | `routers/limitup/metrics.py:_METRICS_CACHE` | 16-80 | 10min (600) | str | 是 | 涨停指标 |
| C11 | `value_funnel/quality.py:_ABSTRACT_CACHE` | 20-79 | 5min (300) | code | 是（含空 list） | 摘要缓存 |
| C12 | `auction_screener.py:_CACHE` / `daily_review.py:_CACHE` | auction 52, dr 34 | 12h | str | 是 | |

**关键差异**：
- **空结果策略**：C2（market）显式不缓存空结果（故障重试），C3（fallback）显式缓存空/失败值（作为降级兜底）。两者语义**相反**，收口时必须保留各自语义。
- **键结构**：tuple / str / md5 混用。
- **线程安全**：均无锁（GIL 兜底，但并发写同一 dict 有竞态窗口）。
- **失效**：仅 C4 有大小淘汰（>1024 清一半），其余无界增长。

### 9.2 统一接口设计

```python
# backend/infra/cache.py（草案）
from __future__ import annotations
import hashlib, json, threading, time
from typing import Any, Callable

class TTLCache:
    """统一内存 TTL 缓存。

    - ``cache_empty=False``：空/失败结果不写入（market 语义：故障下次重试）。
    - ``cache_empty=True``：写入任意返回值（fallback 降级语义：故障值作兜底）。
    - 线程安全（Lock）；无界增长由可选 ``maxsize`` 淘汰（LRU 近似：超限清一半）。
    """
    def __init__(self, ttl: float, *, cache_empty: bool = False,
                 maxsize: int | None = None, valid: Callable[[Any], bool] = bool):
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl
        self._cache_empty = cache_empty
        self._maxsize = maxsize
        self._valid = valid
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...
    def get_or_set(self, key: str, factory: Callable[[], Any]) -> Any:
        """TTL 命中返回缓存；未命中调 factory，按 cache_empty/valid 决定是否写入。"""

def make_key(*parts: Any) -> str:
    """稳定缓存键：md5(json.dumps(parts, default=str, sort_keys=True))。"""
```

### 9.3 迁移顺序（保留旧接口薄封装过渡，可回滚）

1. **建 `infra/cache.py` + 单测**（TTL/空结果不缓存/线程安全/maxsize 淘汰）。不动现有代码。
2. **收口 C2 market**（语义一致：`cache_empty=False, valid=bool, ttl=300`）：
   - `market._CACHE` 改为 `_CACHE = TTLCache(300, cache_empty=False)`；
   - 保留 `_cached` 函数签名作为薄封装，调用方不改。
3. **收口 C1 eastmoney `_ztb_cache`**（`cache_empty=True` 以保留"故障存空 list"现行行为，或改 `False` 让故障重试——需产品确认；草案默认 `True` 保持现状）。
4. **收口 C3 fallback `_MEM_CACHE`**（`cache_empty=True`，保留降级语义）；**文件缓存**层暂不动（涉及磁盘 I/O，单独评估）。
5. **收口 C4 app `_RESPONSE_CACHE`**（`cache_empty=True, maxsize=1024`）——cache_response 已是唯一调用点。
6. **收口 C5-C11** 端点本地缓存（低优先，逐个验证语义）。
7. **全量回归** `pytest -m "not live"` + :8900 冒烟。

### 9.4 回归风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 空结果语义翻转 | market 原本不缓存空结果，误改后故障被缓存→用户看到旧空结果 | `cache_empty` 参数显式化；market 用 `False`，单测锁住"故障不写缓存" |
| fallback 降级丢失 | 主源失败不取回退值 | `with_fallback` 单测锁住"主源失败→返回缓存兜底"语义 |
| 线程安全引入锁开销 | 高频路径（market 5min 缓存）加锁 | 仅 get/set 加细粒度锁；factory 调用在锁外执行（避免持锁调用网络） |
| 键序列化不兼容 | tuple/str 键改 md5 后旧缓存失效（首次启动冷缓存） | 迁移即冷启动，无持久化缓存，无数据丢失 |
| 范围蔓延 | 一次改 12 处缓存回归面大 | 分批迁移（C2→C1→C3→C4→其余），每批跑回归，保留旧 `_cached` 薄封装 |

### 9.5 不引入

- 不引入 Redis/第三方缓存库（内存够用，自托管单机）。
- 不引入持久化（重启清空可接受，所有缓存可重建）。
- 不合并 fallback 文件缓存层（涉及磁盘 I/O，单列后续 spec）。

