# Spec: S103 — 涨停池缓存承重切片（盘中陈旧快照根因治理）

> 状态：草案
> 作者：lzw9560  日期：2026-08-29
> 级别：large（碰数据源缓存策略，影响盘中采集命脉）
> 分支：`feature/S103-zt-pool-cache`（off develop）
> 关联：S055（盘中封单时序采集）/ S070（intraday 采集管道）/ S078（涨停历史 snapshot 数据地基）/ grill「坚实数据底座」第 1 层承重切片

## 1. 问题 / 目标

`em_zt_topic_pool`（`backend/data/sources/eastmoney.py:142`）的缓存策略对盘中场景致命：

1. **24h TTL + 空结果缓存**（`:139` `_ZTB_CACHE_TTL=86400` + `:161-164` 成功失败都写缓存）：一次瞬态失败（网络抖动 / 熔断器 `circuit_breaker("eastmoney")` OPEN 时 `em_get` raise）→ `_ztb_cache[key]=(now, [])` 空缓存 24h。breaker 恢复后不自愈。
2. **盘中 60s 采集命中 24h 缓存**（`risk/seal_intraday_collector.py:390`）：S055 每 60s 调 `em_zt_topic_pool("getTopicZTPool", today, "fbt:asc")`，cache_key 固定 `(getTopicZTPool, 今日YYYYMMDD, fbt:asc)`。首次 09:25 缓存后，**接下来 24h 所有 60s 轮询命中缓存返首帧陈旧数据**——封单时序、炸板次数、首封时间全天不更新。**盘中采集实质上在用 09:25 快照跑全天**。

涨停池是打板工作流（first_board_filter / limitup_screener / seal_intraday / market._emotion）、情绪产线、STI 评分的共同根数据源。盘中陈旧 = 这三条产线在用错误数据跑决策。

**目标**：缓存策略改为「空结果不缓存 + TTL 分级（盘中短/盘后中/历史长）」，根除盘中陈旧 + 失败空毒。复用 `market._cached(key, fn, valid=bool)`（`backend/market.py:21`）的「空结果不缓存」范式。

## 2. 背景

- `em_zt_topic_pool` 返东财 push2ex 涨停/炸板/跌停/昨涨停原始池，走 `em_get`（限流 + 熔断 + 代理探测，防封底线）。
- 消费方 7+：`seal_intraday_collector`（盘中 60s）、`routers/limitup/metrics`（按需）、`routers/topology`（按需 ladder）、`routers/intraday_sentiment`（复用 board_ladder TTL 缓存，非直调）、`tools/first_board_*`（离线工具）。
- `market.py:21` `_cached(key, fn, valid=bool)` 已有「valid 判否不缓存，下次请求直接重试」范式，本 spec 复用此模式。
- `vr_paths.is_trading_day` / `last_trading_date_str` 已有交易日判断基础设施。

## 3. 需求清单

- [ ] R1 空结果不缓存：`em_get` 失败/熔断返空时**不写空缓存**，下次请求直接重试（根除"一次失败空 24h"）
- [ ] R2 TTL 分级：非交易日一律 24h；交易日今日盘中 60s / 今日盘后 1h / 历史日 24h
- [ ] R3 盘中 60s 采集不再命中陈旧首帧：seal_intraday 连续两次调用（间隔≥60s）能拿到最新 pool（当 pool 变化时）
- [ ] R4 7+ 现有调用方签名/行为不回归（不改 `em_zt_topic_pool` 签名）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/eastmoney.py` | `em_zt_topic_pool` 缓存分级 + 空不缓存；新增 `_ztb_cache_ttl(date)` |
| `backend/vr_paths.py` | 新增 `is_intraday_time()` + `INTRADAY_PERIODS` 常量 |
| `backend/risk/seal_intraday_collector.py` | `is_intraday_trading_time` 改 re-export `vr_paths.is_intraday_time`（向后兼容） |

## 5. 设计方案

### 5.1 TTL 分级逻辑（`_ztb_cache_ttl`）

先判非交易日（一律 24h），再判今日盘中/盘后/历史日：

```python
_ZTB_CACHE_TTL_INTRADAY = 60      # 盘中 60s（保新鲜，对齐 S055 采集节奏）
_ZTB_CACHE_TTL_POSTMARKET = 3600  # 今日盘后 1h（定盘后稳定）
_ZTB_CACHE_TTL_HISTORY = 86400    # 历史日 / 非交易日 24h

def _ztb_cache_ttl(date: str) -> int:
    """根据 date + 当前时刻选 TTL。

    判定顺序（grill 第 4 轮锁定）：
    1. 非交易日（date.today() 非交易日）→ 24h（不管查什么 date，都稳定）
    2. date != 今日交易日紧凑日期 → 历史日 24h
    3. date == 今日 + 当前盘中 → 60s
    4. date == 今日 + 当前盘后 → 1h
    """
    from vr_paths import is_trading_day, last_trading_date_str, is_intraday_time
    if not is_trading_day():           # 当前非交易日 → 一律 24h
        return _ZTB_CACHE_TTL_HISTORY
    if date != last_trading_date_str().replace("-", ""):
        return _ZTB_CACHE_TTL_HISTORY  # 历史日 24h
    if is_intraday_time():
        return _ZTB_CACHE_TTL_INTRADAY
    return _ZTB_CACHE_TTL_POSTMARKET
```

**grill 要点记录**：
- 非交易日用 `is_trading_day(date.today())` 判（非 `last_trading_date_str`）——否则周六查周五数据被错判"今日盘后"用 1h（grill 第 4 轮）。
- 15:05 时点翻转（盘中 60s → 盘后 1h）：15:04 写的 60s 缓存会在 15:05:59 过期，期间盘后调用可能命中 1 分钟陈旧的盘中快照。**自愈**（60s 后过期重打），1 分钟陈旧可接受。

### 5.2 空结果不缓存（`em_zt_topic_pool` 改动）

```python
def em_zt_topic_pool(endpoint, date, sort="fbt:asc"):
    cache_key = (endpoint, date, sort)
    now = time.time()
    ttl = _ztb_cache_ttl(date)
    cached = _ztb_cache.get(cache_key)
    if cached and now - cached[0] < ttl:
        return cached[1]

    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": _ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": sort, "date": date}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        result = (r.json().get("data") or {}).get("pool") or []
        if result:              # ← R1：空结果不缓存（失败/真空都走此分支不写）
            _ztb_cache[cache_key] = (now, result)
        return result
    except Exception:
        return []               # ← R1：失败不写空缓存（删除原 _ztb_cache[key]=(now,[])）
```

**grill 要点记录（判据设计）**：
- 原计划用 `"pool" in data` 判 response 完整性区分"成功真空 vs 失败"。**实测证伪**（2026-08-29 非盘中跑三场景：今日/非交易日/历史日，push2ex response 恒 `data.keys()=['tc','qdate','pool']`、`pool` len=82 非空、`'pool' in data` 恒 True）。东财 push2ex 对非交易日 date 参数**静默返最近交易日数据**，不返健康真空。
- 退回 `if result:` 判定——与当前非盘中实测吻合（成功恒非空→缓存，失败 except 返 `[]`→不缓存）。
- **盘中 09:25-09:30 竞价撮合期 `pool` 是否可能为 `[]` 未实测**（非盘中无法测）。若为真，`if result:` 不缓存导致 seal_intraday 每 60s 重打东财——可接受（seal_intraday 本就要新鲜，且不放大：唯一盘中固定频率调用方）。**验收阶段盘中补测此盲区**。

### 5.3 盘中时段判断下沉到 vr_paths

`vr_paths.py` 新增（复用现有 `_time` / `_dt` / `is_trading_day`）：

```python
#: A 股盘中交易时段（S103 下沉自 seal_intraday_collector，供 data/sources 复用避免循环 import）
INTRADAY_PERIODS = [(_time(9, 25), _time(11, 30)), (_time(13, 1), _time(15, 5))]

def is_intraday_time(now: _dt | None = None) -> bool:
    """是否在盘中交易时段（交易日 + 09:25-11:30 / 13:01-15:05）。

    组合 is_trading_day(当前日期) + 当前时刻在 INTRADAY_PERIODS 内。
    供 em_zt_topic_pool 缓存 TTL 判定 + seal_intraday_collector 复用。
    """
    now = now or _dt.now()
    if not is_trading_day(now.date()):
        return False
    t = now.time()
    return any(s <= t <= e for s, e in INTRADAY_PERIODS)
```

`risk/seal_intraday_collector.py:76` `is_intraday_trading_time` 改 re-export（保 7+ 调用方签名不变）：

```python
from vr_paths import is_intraday_time as is_intraday_trading_time  # noqa: F401
```

（`_TRADING_PERIODS` 原常量保留或改 re-export `INTRADAY_PERIODS`，视该文件其他引用定——实现时核实）。

### 5.4 盘中 TTL 60s 的语义边界（grill 第 3 轮锁定）

盘中 TTL=60s **对 seal_intraday 自己零价值**（它每 60s 调，缓存正好过期，每次 miss 拿新鲜——这是设计意图，盘中要新鲜）。其唯一作用是**防并发放大**：同 60s 窗口内多个调用方（seal_intraday + metrics + topology 并发）只打一次东财，其余命中缓存。

按需调用方（metrics/topology）命中盘中缓存可能拿到≤60s 陈旧数据——盘中涨停池本就在动，前端展示迟 60s 可接受。spec 显式承认此陈旧。

## 6. 验收标准

- [ ] A1 `em_get` 成功返数据 → 缓存写入 + TTL 内命中（秒回）
- [ ] A2 `em_get` 失败/熔断 → 返 `[]` 且 `_ztb_cache` **不写入空**（key 不在缓存或未更新）——下次请求重试
- [ ] A3 非交易日 TTL=24h；交易日今日盘中 60s / 今日盘后 1h / 历史日 24h
- [ ] A4 seal_intraday 盘中连续两次调用（间隔≥60s）不命中旧缓存——拿到最新 pool（当 pool 变化时）
- [ ] A5 `vr_paths.is_intraday_time` 行为：周六返 False / 交易日 10:00 返 True / 交易日 12:00 返 False / 交易日 15:06 返 False
- [ ] A6 `seal_intraday_collector.is_intraday_trading_time` re-export 后行为不变（7+ 调用方不回归）
- [ ] A7 盘中 09:25-09:30 竞价期 `pool` 是否可能为 `[]`（验收阶段盘中补测盲区）——若为真，确认 seal_intraday 每 60s 重打可接受

## 7. 合规与工程底线自查

- [x] 不臆造：空结果返 `[]` 不缓存，诚实缺失，下次重试（非毒缓存）
- [x] 私有数据隔离：无新增数据落盘，缓存是内存 dict
- [x] em_get 防封：不变（仍走 em_get + 熔断），只改缓存策略；盘中 TTL=60s 防并发放大不放大请求
- [x] §44 口径：本 spec 不出 winrate/r/verdict，纯缓存治理无 §44 门

## 8. 测试计划

- **单测**（新建 `backend/tests/test_s103_zt_pool_cache.py`）：
  - mock `em_get` 成功返 `{"data":{"pool":[{...}]}}` → 缓存写入 + TTL 内命中
  - mock `em_get` raise → 返 `[]` 且 `_ztb_cache` 不写入空（断言 key 不在或值未变）
  - mock `is_trading_day`/`is_intraday_time` → TTL 取值正确（非交易日 24h / 盘中 60s / 盘后 1h / 历史日 24h）
  - mock 60s 内 pool 变化 → 盘中不命中旧缓存
- **回归**：`pytest backend/tests/test_s055_seal_intraday_collector.py backend/tests/test_s070_seal_intraday_executor.py -q`（seal_intraday 不回归）
- **全量 gate**：`pytest -m "not live" --deselect tests/test_newsradar* --deselect tests/test_s032_refresh_loop.py`（按 memory：newsradar 联网 + s032 timing flaky）
- **盘中补测**（A7 盲区）：交易日 09:25-09:30 跑 `seal_intraday.collect_once` 两次（间隔 60s），确认 pool 行为 + 是否重打东财

## 9. 风险与回滚

- **风险**：盘中 TTL 24h→60s 后，seal_intraday 每次 miss 重打东财——但本就每 60s 调一次，不放大；其他盘中调用方（intraday_sentiment 复用 board_ladder 缓存不直调）不放大。已核实调用方频率。
- **风险**：盘中 09:25-09:30 `pool=[]` 盲区未实测，若为真则早盘 seal_intraday 每 60s 重打——可接受（要新鲜），验收补测。
- **回滚**：`_ZTB_CACHE_TTL_INTRADAY` 调回 86400 即退回旧行为；或 revert 3 文件改动。

## 10. 冲突审查表

| 旧 spec R-item | 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S078 R6 | 零风险只读采集，**不改现有涨停四池 24h 缓存** | 本 spec 改 24h 缓存为分级 TTL + 空不缓存 | **修订 S078 R6 设计意图** | S078 的 history DB 是独立表（`zt_history`，`zt_history_store.py`），不依赖 `em_zt_topic_pool` 内存缓存。改内存缓存策略不影响 S078 每日盘后 snapshot（仍调 `em_zt_topic_pool` 取数据写 DB，缓存策略变了但取数结果不变）。S078 R6 的"不改"是当时隔离风险意图，现四路审查揭示 24h 缓存是 bug 根因，修订此意图是修 bug 非破坏 S078。 |
| S055 / S070 | seal_intraday 60s 调 em_zt_topic_pool 写 snapshots | 不变（消费方不改） | 共存 | seal_intraday 调用签名不变，行为改善（拿新鲜数据非陈旧）。 |
| S086 | 战法 pipeline 统一，不碰缓存 | 不变 | 共存 | 无冲突。 |

## 11. 不在本 spec 范围（后续承重切片）

- 源注册表 + 缓存统一治理全铺（datacenter 1800s 空缓存、tencent 60s 负缓存等）——本 spec 只切涨停池，跑通模式后扩
- 孤儿模块接线（新浪三表 / anomaly / cross_validate）——第 3 层
- hithink 作结构性缺口正式第二源——第 4 层
- 美港股 K线/估值、worldmonitor 宏观 MCP 握手——另立 spec
