# 技术方案 · S070 intraday 采集管道（封单 trajectory + 资金流 intraday + 战法因子派生）

> 对应 spec：`specs/S070-intraday采集管道/spec.md`（扩展版含 R1-R8，2026-08-18）
> 性质：技术实现方案（spec 草案，本文件进入文件/函数级设计，受 `CLAUDE.md` §0 SDD 约束）
> 作者：Fixer ｜ 日期：2026-08-18

---

## 0. 依据与复用清单

| spec 要求 | 复用的现有能力（不重造） | 备注 |
|---|---|---|
| R1 封单 trajectory（delta/max/min/slope） | `seal_intraday_collector.get_snapshots_by_code(code, date)` line 120 返回时序列表；纯函数派生，零新 fetch | trajectory 从既有 snapshots 导出，最廉先做 |
| R2 资金流 intraday 采集 | `astock.em_get`（东财统一限流+熔断+代理探测，eastmoney.py 内部已封装）；`data.sources.eastmoney` 新增 fflow intraday 端点 | 探端点可行性，不可行则 defer，不阻塞 R1/R3/R6/R7 |
| R3 持久化 + 日积 | `seal_intraday_collector.save_snapshots(rows)` line 90 批量写入范式；`scheduled_tasks._execute_seal_intraday_collect` line 822 executor 已注册，扩之 | 新建 `intraday_features` 表（R1/R2 trajectory + 资金流因子） |
| R4 盘后 §44 60日复验窗口 | 复用 sector_heat_validation 口径（热/冷分位 + Wilson CI + lift）；`tools/financial_rigor.py` 复算 | ~30 日后数据积累才跑，当前标"探索性"跑通 |
| R5 诚实标注 | `seal_intraday_collector` 既有 `data_status=ok/missing/degraded` 范式 | 未满 30 日标探索性；<2x 标未 validated 不阻断接入 |
| R6 分时低点采集 | `astock.tencent_quote(codes: list[str]) -> dict[str, dict]`（门面，re-export 自 `data.sources.tencent.fetch_raw`），返回 raw dict 含 `low` 字段（vals[34]）；`collect_once` line 168 既有涨停池循环 | 复用既有腾讯源（不封 IP，60s TTL 缓存），不新增数据源 |
| R7 战法因子派生 | `get_snapshots_by_code` 返回时序列表（纯函数输入）；`data/mappers.py:546` 证实涨停池 raw 有 `zdp` 字段（涨幅%）可推算涨停价 | 派生是纯函数，不依赖网络 |
| R8 S081 门禁 | 无复用，纯流程门（R7 落地通知 S081） | S081 spec 标"数据层未就绪"直到 R7 落地 |

**新增**：`intraday_features` 表 + `seal_derived_features` 表（或合并）+ `strategies/intraday_features.py`（trajectory + 派生计算）+ `collect_once` 扩 low_price 采集 + 2 个迁移 + `scheduled_tasks` 扩 executor + 测试。

**不新增**：数据源（R6 复用 tencent_quote）、通知系统、状态机持久化、新路由（本期纯数据管道，无 HTTP 出口）。

> **前提修正记录**（spec 核实阶段）：
> - spec R6 称"tencent_quote 接受个股代码（带前缀映射），返回 quote dict"——**核实成立**。`astock.tencent_quote` 是 `data.sources.tencent.fetch_raw` 的门面（astock.py:29 re-export），返回 raw dict 含 `low=vals[34]`（分时最低价）。`collect_once` line 191-192 注释提到的 `tencent_quote` 即此门面，但当前 `collect_once` 实际只用了 `index_raw()` 取指数（line 195），未用个股 quote。R6 需在涨停池循环里对每只股调 `tencent_quote` 取 low。
> - spec R7 称"涨停价从 first_seal_time 对应的 price 或涨停池 zdp 字段推算"——**核实 zdp 字段存在但 collect_once 未存**。`data/mappers.py:546 limit_pct=_numf(raw.get("zdp"))` 证实涨停池 raw 有 `zdp`（涨幅%），但 `collect_once` line 209-231 当前只存 `p`（最新价）不存 `zdp`。**实现决策**：R6 迁移同时补存 `limit_pct`（zdp 原值），R7 用 `limit_price = price / (1 + limit_pct/100)` 反推涨停价（首封时刻 price≈涨停价，更稳），避免依赖 first_seal_time 的 price 采样精度。
> - spec §3.2 R6.3 称"与 S055 既有 data_status=degraded 一致"——**核实成立**。`collect_once` line 188 `data_status="degraded"` 已是既有范式。

---

## 1. 目录结构

### 1.1 后端新增/改动

```
backend/
├── risk/
│   └── seal_intraday_collector.py        # 【改动】collect_once 扩 low_price + limit_pct 采集；save_snapshots 字段表扩 2 列；run_migrations 注册新迁移
├── migrations/
│   └── seal_intraday/
│       ├── 20260811-001_create_seal_intraday_snapshots.sql  # 既有（不动）
│       ├── 20260818-001_add_low_price_limit_pct.sql          # 【新增】R6.1：ALTER TABLE 加 low_price + limit_pct
│       └── 20260818-002_create_intraday_features.sql          # 【新增】R3：CREATE TABLE intraday_features（trajectory + 资金流因子）+ seal_derived_features（R7 派生结果）
├── strategies/
│   └── intraday_features.py              # 【新增】R1 trajectory 计算（纯函数）+ R7 派生计算（last_lock_time/broken_duration_min/max_drop_pct，纯函数）+ R2 资金流 intraday fetch（若可行）
├── scheduled_tasks.py                    # 【改动】扩 _execute_seal_intraday_collect：采集后调 intraday_features.compute_and_persist(date)
├── data/
│   └── sources/
│       └── eastmoney.py                  # 【改动·条件】R2 若可行：新增 fflow intraday 端点（em_get 限流）；不可行则 defer，不动
└── tests/
    ├── test_intraday_features.py          # 【新增】R1 trajectory + R7 派生计算单测（纯函数，mock 时序输入）
    ├── test_seal_intraday_collector_low_price.py  # 【新增】R6 collect_once 扩 low_price 采集测试
    └── test_s055_seal_intraday_collector.py  # 【改动】既有测试补 low_price/limit_pct 字段断言
```

### 1.2 无前端改动

本期纯后端数据管道，无 HTTP 路由新增（R4 §44 验证走 `tools/` 离线脚本，不挂路由）。

---

## 2. 实现步骤（按 R1-R8 顺序）

> 依赖：R6（low_price 字段）是 R7（max_drop_pct 派生）的前置；R3（intraday_features 表）是 R1/R7 持久化的前置。实现顺序：**迁移（R6.1+R3）→ 采集扩（R6.2）→ 派生计算（R1+R7）→ executor 扩（R3 日积）→ §44 验证（R4）→ 诚实标注（R5）→ 门禁（R8）**。

### R6.1 表迁移：加 low_price + limit_pct 字段

**文件**：`backend/migrations/seal_intraday/20260818-001_add_low_price_limit_pct.sql`（新增）

```sql
-- S070 R6.1：seal_intraday_snapshots 加 low_price（分时最低价）+ limit_pct（涨停涨幅%，用于反推涨停价）
-- low_price：tencent_quote 的 low 字段（vals[34]），60s 粒度快照时的区间低点
-- limit_pct：em_zt_topic_pool 的 zdp 字段（涨幅%），用于 R7 反推涨停价 limit_price = price / (1 + limit_pct/100)
-- 缺失时 NULL，不臆造
ALTER TABLE seal_intraday_snapshots ADD COLUMN low_price REAL;
ALTER TABLE seal_intraday_snapshots ADD COLUMN limit_pct REAL;
```

**注册迁移**：`seal_intraday_collector.run_migrations()` line 47-50 扩 migrations 列表：

```python
migration_v2 = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "seal_intraday" / "20260818-001_add_low_price_limit_pct.sql"
).read_text(encoding="utf-8")
migrations = [
    {"version": "20260811-001", "name": "create_seal_intraday_snapshots", "sql": migration_v1},
    {"version": "20260818-001", "name": "add_low_price_limit_pct", "sql": migration_v2},
]
```

**单测要点**：
- 迁移幂等（二次调用不报错，ALTER TABLE IF NOT EXISTS 等价语义——SQLite ALTER TABLE 无 IF NOT EXISTS，靠 MigrationManager 版本去重）
- 迁移后 `PRAGMA table_info(seal_intraday_snapshots)` 含 low_price / limit_pct 列
- 既有数据行 low_price / limit_pct 为 NULL（不臆造历史）

---

### R3 表迁移：建 intraday_features + seal_derived_features 表

**文件**：`backend/migrations/seal_intraday/20260818-002_create_intraday_features.sql`（新增）

```sql
-- S070 R3：intraday 因子持久化（trajectory + 派生结果）
-- 设计：trajectory（R1，盘中实时可算）与派生（R7，盘后/日终算）分表，因计算时机不同
--   - intraday_features：R1 trajectory（盘中每轮可更新，UPSERT）
--   - seal_derived_features：R7 派生（日终一次性算，INSERT OR REPLACE）

-- R1：封单 trajectory 因子表（date/code 主键，盘中可多次 UPSERT）
CREATE TABLE IF NOT EXISTS intraday_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                   -- 交易日 YYYY-MM-DD
    code TEXT NOT NULL,
    name TEXT,
    -- 封单 trajectory（从 seal_intraday_snapshots 时序派生）
    seal_delta REAL,                       -- 日内封单 delta（末值 - 首值）
    seal_max REAL,                         -- 日内封单峰值
    seal_min REAL,                         -- 日内封单谷值
    seal_slope REAL,                       -- 封单斜率（线性回归 slope）
    snapshot_count INTEGER,                -- 快照数（数据完整性参考）
    computed_at TEXT NOT NULL,             -- ISO8601 计算时间戳
    data_status TEXT DEFAULT 'ok',         -- ok/missing/degraded
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, code)
);
CREATE INDEX IF NOT EXISTS idx_intraday_features_date ON intraday_features(date);
CREATE INDEX IF NOT EXISTS idx_intraday_features_code ON intraday_features(code);

-- R7：战法因子派生表（date/code 主键，日终一次性算）
CREATE TABLE IF NOT EXISTS seal_derived_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    last_lock_time TEXT,                   -- 最后封死时刻（ISO8601，open_count 最后一次=0 的 ts）
    broken_duration_min REAL,             -- 炸板累计时长（分钟，60s 粒度近似）
    max_drop_pct REAL,                     -- 炸板后回撤幅度（(涨停价-min(low_price))/涨停价*100）
    limit_price REAL,                      -- 涨停价（反推：price/(1+limit_pct/100)）
    granularity_note TEXT DEFAULT '60s粒度近似',  -- 粒度限制标注（A7）
    computed_at TEXT NOT NULL,
    data_status TEXT DEFAULT 'ok',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, code)
);
CREATE INDEX IF NOT EXISTS idx_seal_derived_date ON seal_derived_features(date);
CREATE INDEX IF NOT EXISTS idx_seal_derived_code ON seal_derived_features(code);
```

**注册迁移**：`run_migrations()` 再扩一条：

```python
migration_v3 = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "seal_intraday" / "20260818-002_create_intraday_features.sql"
).read_text(encoding="utf-8")
migrations = [
    ...,
    {"version": "20260818-002", "name": "create_intraday_features", "sql": migration_v3},
]
```

**单测要点**：
- 两表创建 + 迁移幂等
- UNIQUE(date, code) 约束生效（重复插入走 UPSERT 不报错）

---

### R6.2 collect_once 扩 low_price + limit_pct 采集

**文件**：`backend/risk/seal_intraday_collector.py`（改动）

**改动点 1**：`save_snapshots(rows)` line 90-117 字段表扩 2 列：

```python
fields = ["ts", "date", "code", "name", "pool", "price", "seal_amount",
          "open_count", "first_seal_time", "consec_boards", "sector",
          "float_market_cap", "index_5min_change",
          "low_price", "limit_pct"]  # 新增 2 列
```

INSERT SQL 同步加 `:low_price, :limit_pct`。

**改动点 2**：`collect_once(date_str)` line 168-234 涨停池循环里加 tencent_quote 批量取 low：

```python
def collect_once(date_str: str | None = None) -> dict[str, Any]:
    # ... 既有 1-2 步不变（涨停池 + 指数）...

    # 2.5 批量取涨停池个股 tencent_quote（R6：分时低点 + 限流复用 60s 缓存）
    #    tencent_quote 返回 raw dict，含 low=vals[34]（分时最低价）
    #    一次请求全池 codes（60s 缓存，同周期内复用，不重复请求）
    codes = [str(item.get("c", "")) for item in zt_pool if item.get("c")]
    quotes: dict[str, dict] = {}
    if codes:
        try:
            quotes = astock.tencent_quote(codes) or {}
        except Exception as exc:
            _logger.warning("[seal_intraday] tencent_quote 失败: %s", exc)
            quotes = {}  # 降级：low_price 留 None，不臆造

    # 3. 候选股流通市值 + R6 low_price + limit_pct
    rows: list[dict[str, Any]] = []
    for item in zt_pool:
        code = str(item.get("c", ""))
        if not code:
            continue
        float_cap = item.get("ltsz")
        price = item.get("p") or item.get("zje") or 0
        seal_amount = item.get("fund")
        # R6：分时低点（tencent_quote 的 low 字段，缺失时 None）
        q = quotes.get(code) or {}
        low_price = q.get("low")  # vals[34]，分时最低价
        # R7 前置：涨停涨幅%（zdp，用于反推涨停价）
        limit_pct = item.get("zdp")
        rows.append({
            "ts": ts, "date": date_str, "code": code, "name": item.get("n"),
            "pool": "zt", "price": price, "seal_amount": seal_amount,
            "open_count": item.get("zbc"), "first_seal_time": item.get("fbt"),
            "consec_boards": item.get("lbc"), "sector": item.get("hybk"),
            "float_market_cap": float_cap, "index_5min_change": index_5min_change,
            "low_price": low_price, "limit_pct": limit_pct,  # 新增
        })

    written = save_snapshots(rows)
    return {"written": written, "skipped": 0, "data_status": "ok" if written else "empty"}
```

**关键约束**：
- `tencent_quote` 一次批量请求全池 codes（复用 60s TTL 缓存，不逐只请求）
- `low_price` 缺失（tencent_quote 返 `{}` 或 `low=0.0`）时留 None，不臆造
- `limit_pct` 从涨停池 raw 的 `zdp` 直接取（em_zt_topic_pool 已含此字段，零额外请求）

**单测要点**（`test_seal_intraday_collector_low_price.py` 新增）：
- 涨停池 + tencent_quote mock 返回 low → 落库 low_price 正确
- tencent_quote 失败 → low_price=None，data_status 不降级（仍 ok，因涨停池主数据成功）
- tencent_quote 返空 dict → low_price=None，不臆造
- limit_pct 从 zdp 正确落库
- 既有 test_s055 测试补 low_price/limit_pct 断言（mock tencent_quote 返回 low）

---

### R1 封单 trajectory 计算（纯函数）

**文件**：`backend/strategies/intraday_features.py`（新增）

```python
# backend/strategies/intraday_features.py
# -*- coding: utf-8 -*-
"""S070：intraday 因子计算层。

R1：封单 trajectory（从 seal_intraday_snapshots 时序派生，纯函数，零新 fetch）
R7：战法因子派生（last_lock_time / broken_duration_min / max_drop_pct，纯函数）
R2：资金流 intraday fetch（若可行，em_get 限流；不可行 defer）

工程底线：
- 派生是纯函数，输入是 get_snapshots_by_code 返回的时序列表，不依赖网络
- 缺数据标 None，不臆造（data_status=missing/degraded）
- 60s 粒度近似标注（broken_duration_min 可能漏 <60s 短时炸板）
"""
from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger(__name__)


def compute_trajectory(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """R1：从封单时序派生 trajectory 因子。

    输入：get_snapshots_by_code(code, date) 返回的时序列表（按 ts 升序）。
    输出：{seal_delta, seal_max, seal_min, seal_slope, snapshot_count, data_status}

    算法：
    - seal_delta = seal_amount[末] - seal_amount[首]（日内封单变化）
    - seal_max / seal_min = 全时序 seal_amount 的 max / min
    - seal_slope = 线性回归 slope（x=快照序号 0..n-1, y=seal_amount），
      正值=封单增强，负值=封单衰减
    - snapshot_count = len(snapshots)（数据完整性参考，<N 标 degraded）
    - 空/单点时序 → data_status=missing，各因子 None
    """
    if not snapshots:
        return {"seal_delta": None, "seal_max": None, "seal_min": None,
                "seal_slope": None, "snapshot_count": 0, "data_status": "missing"}

    amounts = [s.get("seal_amount") for s in snapshots if s.get("seal_amount") is not None]
    if not amounts:
        return {"seal_delta": None, "seal_max": None, "seal_min": None,
                "seal_slope": None, "snapshot_count": len(snapshots), "data_status": "missing"}

    seal_delta = amounts[-1] - amounts[0] if len(amounts) >= 2 else 0.0
    seal_max = max(amounts)
    seal_min = min(amounts)
    seal_slope = _linear_regression_slope(amounts)
    data_status = "ok" if len(snapshots) >= 10 else "degraded"  # <10 快照标 degraded

    return {"seal_delta": seal_delta, "seal_max": seal_max, "seal_min": seal_min,
            "seal_slope": seal_slope, "snapshot_count": len(snapshots),
            "data_status": data_status}


def _linear_regression_slope(ys: list[float]) -> float:
    """简单线性回归 slope（y = a + b*x，返 b）。n<2 返 0.0。"""
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    return numerator / denominator if denominator else 0.0


def persist_trajectory(date: str, code: str, name: str | None,
                       traj: dict[str, Any], conn) -> None:
    """R1：trajectory 写入 intraday_features 表（UPSERT）。"""
    from datetime import datetime
    conn.execute(
        """INSERT OR REPLACE INTO intraday_features
        (date, code, name, seal_delta, seal_max, seal_min, seal_slope,
         snapshot_count, computed_at, data_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (date, code, name, traj["seal_delta"], traj["seal_max"], traj["seal_min"],
         traj["seal_slope"], traj["snapshot_count"], datetime.now().isoformat(),
         traj["data_status"]),
    )
```

**单测要点**（`test_intraday_features.py`）：
- 空时序 → data_status=missing，各因子 None
- 单点时序 → seal_delta=0, seal_slope=0, data_status=degraded
- 正常时序（10 点）→ seal_delta/max/min/slope 正确，data_status=ok
- slope 正负值正确（递增>0，递减<0）
- persist_trajectory UPSERT 幂等（同 date/code 二次写入不报错、覆盖）

---

### R7 战法因子派生（纯函数）

**文件**：`backend/strategies/intraday_features.py`（同文件，续）

```python
def compute_derived_features(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """R7：从封单时序派生战法硬阈值因子（纯函数，不依赖网络）。

    输入：get_snapshots_by_code(code, date) 返回的时序列表（按 ts 升序）。
    输出：{last_lock_time, broken_duration_min, max_drop_pct, limit_price,
           granularity_note, data_status}

    算法：
    - last_lock_time：open_count 最后一次=0 的 ts（最后封死时刻）
      注意：open_count=0 表示当前未开板；找最后一次 open_count 从 >0 变 0 的 ts
      （即最后一个 open_count==0 的快照 ts）
    - broken_duration_min：所有 open_count>0 的快照数 × 60s / 60 = 分钟
      （60s 粒度近似，每个快照间隔 60s）
      ⚠️ 粒度限制：可能漏 <60s 短时炸板（A7 标注）
    - max_drop_pct：(涨停价 - min(low_price)) / 涨停价 * 100
      涨停价反推：limit_price = price / (1 + limit_pct/100)
      （首封时刻 price≈涨停价，但用 limit_pct 反推更稳，避免 price 采样精度问题）
    - 缺 low_price → max_drop_pct=None（不臆造）
    - 缺 limit_pct → 退回用首快照 price 作涨停价近似（标 degraded）
    """
    if not snapshots:
        return _empty_derived()

    # last_lock_time：最后一个 open_count==0 的 ts
    last_lock_time = None
    for s in snapshots:
        if (s.get("open_count") or 0) == 0:
            last_lock_time = s.get("ts")  # 不断覆盖，取最后一个

    # broken_duration_min：open_count>0 的快照数 × 1 分钟
    broken_count = sum(1 for s in snapshots if (s.get("open_count") or 0) > 0)
    broken_duration_min = float(broken_count)  # 60s 粒度：每快照 1 分钟

    # limit_price：优先用 limit_pct 反推，缺则用首快照 price 近似
    limit_pct = snapshots[0].get("limit_pct")
    first_price = snapshots[0].get("price")
    limit_price = None
    limit_price_source = None
    if limit_pct is not None and first_price:
        limit_price = first_price / (1 + limit_pct / 100)
        limit_price_source = "limit_pct"
    elif first_price:
        limit_price = first_price  # 退回首价近似
        limit_price_source = "first_price_degraded"

    # max_drop_pct：(涨停价 - min(low_price)) / 涨停价 * 100
    low_prices = [s.get("low_price") for s in snapshots if s.get("low_price") is not None]
    max_drop_pct = None
    if low_prices and limit_price and limit_price > 0:
        min_low = min(low_prices)
        max_drop_pct = (limit_price - min_low) / limit_price * 100

    # data_status
    data_status = "ok"
    if not low_prices:
        data_status = "degraded"  # 缺 low_price
    if limit_price_source == "first_price_degraded":
        data_status = "degraded"

    return {
        "last_lock_time": last_lock_time,
        "broken_duration_min": broken_duration_min,
        "max_drop_pct": max_drop_pct,
        "limit_price": limit_price,
        "granularity_note": "60s粒度近似",  # A7 标注
        "data_status": data_status,
    }


def _empty_derived() -> dict[str, Any]:
    return {"last_lock_time": None, "broken_duration_min": None,
            "max_drop_pct": None, "limit_price": None,
            "granularity_note": "60s粒度近似", "data_status": "missing"}


def persist_derived_features(date: str, code: str, name: str | None,
                             derived: dict[str, Any], conn) -> None:
    """R7：派生结果写入 seal_derived_features 表（INSERT OR REPLACE）。"""
    from datetime import datetime
    conn.execute(
        """INSERT OR REPLACE INTO seal_derived_features
        (date, code, name, last_lock_time, broken_duration_min, max_drop_pct,
         limit_price, granularity_note, computed_at, data_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (date, code, name, derived["last_lock_time"], derived["broken_duration_min"],
         derived["max_drop_pct"], derived["limit_price"], derived["granularity_note"],
         datetime.now().isoformat(), derived["data_status"]),
    )
```

**关键算法说明**（A6 复算口径）：

| 因子 | 公式 | 输入字段 | 缺失处置 |
|---|---|---|---|
| `last_lock_time` | 时序里最后一个 `open_count==0` 的 `ts` | `open_count`, `ts` | 全程开板（无 open_count==0）→ None |
| `broken_duration_min` | `count(open_count>0) × 1 分钟` | `open_count` | 60s 粒度近似（A7 标注） |
| `max_drop_pct` | `(limit_price - min(low_price)) / limit_price * 100` | `low_price`, `price`, `limit_pct` | 缺 low_price → None；缺 limit_pct → 退回首价近似标 degraded |
| `limit_price`（辅助） | `price / (1 + limit_pct/100)` | `price`, `limit_pct` | 缺 limit_pct → 用首快照 price 近似 |

**单测要点**（`test_intraday_features.py` 续）：
- 全程封死（open_count 全 0）→ last_lock_time=末 ts，broken_duration_min=0
- 中间炸板（open_count 0→1→0）→ last_lock_time=最后封死 ts，broken_duration_min=炸板区间分钟数
- 全程炸板（open_count 全 >0）→ last_lock_time=None，broken_duration_min=全程分钟数
- low_price 全缺失 → max_drop_pct=None, data_status=degraded
- limit_pct 缺失 → limit_price 退回首价，data_status=degraded
- max_drop_pct 计算正确性（手算对照：涨停价 10, min_low=9.5 → (10-9.5)/10*100=5.0）
- `financial_rigor.py` 可复算（纯函数输入输出确定）

---

### R2 资金流 intraday 采集（条件实现）

**文件**：`backend/data/sources/eastmoney.py`（条件改动）+ `backend/strategies/intraday_features.py`（续）

**实现策略**：先探端点可行性，不可行则 defer，不阻塞 R1/R3/R6/R7。

```python
# backend/strategies/intraday_features.py（续）

def fetch_intraday_fund_flow(codes: list[str]) -> dict[str, dict[str, Any]]:
    """R2：个股实时资金净流入（em_get 限流）。

    探 em_get fflow intraday 端点（push2.eastmoney.com/api/...）。
    可行 → 返 {code: {main_net_inflow, ...}}；不可行 → 返 {} 并 log defer 原因。

    ⚠️ 本期实现优先级低于 R1/R6/R7（R2 需探端点，R1/R6/R7 零新 fetch）。
    若端点不可行/限流重 → defer，标 R2=deferred 不阻塞管道跑通。
    """
    # TODO: 探端点后实现。当前占位返空，标 deferred。
    _logger.info("[intraday_features] R2 资金流 intraday 端点待探，deferred")
    return {}
```

**单测要点**：
- 端点不可行 → 返 {} 不抛
- 端点可行（mock）→ 返回 main_net_inflow 正确

---

### R3 日积：scheduled_tasks executor 扩

**文件**：`backend/scheduled_tasks.py`（改动 line 822-866 `_execute_seal_intraday_collect`）

**改动**：`collect_once` 成功后，对每只票跑 trajectory + 派生计算并落库：

```python
def _execute_seal_intraday_collect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    # ... 既有 prune + collect_once + 规则引擎不变 ...

    result = collect_once()
    result["pruned"] = pruned

    # 既有规则引擎不变 ...
    if result.get("written", 0) > 0:
        # ... 既有 check_all_rules / process_alerts ...

        # S070 新增：trajectory + 派生计算并落库（R3 日积）
        from strategies.intraday_features import (
            compute_trajectory, persist_trajectory,
            compute_derived_features, persist_derived_features,
        )
        from risk.seal_intraday_collector import _get_conn, _DB_LOCK
        import sqlite3
        date_str = result.get("date") or datetime.now().strftime("%Y-%m-%d")
        traj_written = 0
        derived_written = 0
        try:
            conn = _get_conn()
            with _DB_LOCK:
                for snap in latest_snaps:
                    code = snap.get("code")
                    name = snap.get("name") or code
                    if not code:
                        continue
                    snaps = get_snapshots_by_code(code, date_str)
                    # R1 trajectory
                    traj = compute_trajectory(snaps)
                    persist_trajectory(date_str, code, name, traj, conn)
                    traj_written += 1
                    # R7 派生
                    derived = compute_derived_features(snaps)
                    persist_derived_features(date_str, code, name, derived, conn)
                    derived_written += 1
                conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("[seal_intraday] trajectory/derived 计算落库失败: %s", exc)
        result["trajectory_written"] = traj_written
        result["derived_written"] = derived_written

    return result
```

**单测要点**（`test_task_executor.py` 扩）：
- collect_once 成功 → trajectory_written / derived_written > 0
- collect_once 失败 → 不跑派生（trajectory_written=0）
- 派生计算异常 → 不阻塞主流程（warning + 继续返 result）

---

### R4 盘后 §44 60日复验窗口（日历阻塞，本期占位）

**文件**：`backend/tools/intraday_edge_validation.py`（新增，占位）

```python
# backend/tools/intraday_edge_validation.py
# -*- coding: utf-8 -*-
"""S070 R4：§44 60日复验窗口验证 intraday 因子 → 次日涨停/溢价 lift。

⚠️ 日历阻塞：当前 intraday 数据近期-only（封单 ~2 日），不满 30 日无法出 validated 结论。
本期：管道接入跑通，标"未 validated/探索性"。
~30 日后：复用 sector_heat_validation 口径（热/冷分位 + Wilson CI + lift）验证。
"""
# TODO: 30 日数据积累后实现。当前占位。
```

**单测要点**：本期无（占位，30 日后补）。

---

### R5 诚实标注（贯穿所有 R）

**约束**（所有实现点强制）：
- 未满 30 日：`intraday_features.data_status` / `seal_derived_features.data_status` 标 `ok`/`degraded`/`missing`，但 §44 验证层标"探索性"（未 validated）
- 不臆造：`low_price` / `limit_pct` / `max_drop_pct` 缺失时 None，不补默认值
- 60s 粒度近似：`seal_derived_features.granularity_note` 固定标"60s粒度近似"（A7）

---

### R8 S081 门禁（流程门，无代码）

**动作**：
- R7 落地前：S081 spec 标"数据层未就绪（依赖 S070 R7）"
- R7 落地后（`compute_derived_features` + `seal_derived_features` 表可用）：通知 S081 可进实现

**验收**：S081 spec 的"依赖 S070 R7"字段从"未就绪"翻"已就绪"。

---

## 3. 验收对齐（spec AC1-AC8 → plan 实现步骤）

| spec AC | 要求 | plan 实现步骤 | 验证方式 |
|---|---|---|---|
| AC1（A1 R1） | 封单 trajectory 从 snapshots 算出 + 持久化 | R1 `compute_trajectory` + `persist_trajectory` → `intraday_features` 表 | 单测：trajectory 计算正确性 + UPSERT 落库；executor 集成测试 trajectory_written>0 |
| AC2（A2 R2） | 资金流 intraday 采集 + 持久化（若可行） | R2 `fetch_intraday_fund_flow`（占位 deferred，探端点后补） | 本期：端点不可行则 defer，不阻断；可行则单测 |
| AC3（A3 R4） | ~30 日后 §44 60日复验窗口验证 | R4 `tools/intraday_edge_validation.py`（占位） | 本期：日历阻塞，标探索性；30 日后补 |
| AC4（A4 R5） | 诚实：未满 30 探索性；不臆造 | R5 贯穿：data_status 标注 + low_price/limit_pct 缺失 None | 单测：缺失场景 data_status=degraded/missing |
| AC5（A5 R6） | seal_intraday_snapshots 加 low_price + collect_once 采集 | R6.1 迁移 + R6.2 collect_once 扩 tencent_quote | 单测：low_price 落库 + 缺失 None + tencent_quote 失败降级 |
| AC6（A6 R7） | 派生计算正确输出三因子，可复算 | R7 `compute_derived_features`（纯函数） | 单测：三因子算法正确性 + financial_rigor 复算 |
| AC7（A7 R7 粒度） | broken_duration_min 60s 粒度近似标注 | R7 `granularity_note="60s粒度近似"` 落库 | 单测：granularity_note 字段断言 |
| AC8（A8 R8 门禁） | S081 标"数据层未就绪"直到 R7 落地 | R8 流程门 | 验收：S081 spec 依赖字段翻"已就绪" |

---

## 4. 合规自查与技术约束

- **合规边界（CLAUDE.md §1.1）**：本期纯数据管道（foundation），无 HTTP 路由、无前端、无买卖方向/参考价位/收益预测/主观评分。`intraday_features` / `seal_derived_features` 仅存客观数据（trajectory 数值 + 派生数值 + data_status），不含方向结论。
- **不臆造**：`low_price` / `limit_pct` / `max_drop_pct` / `seal_delta` 等缺失时 None，不补默认值（AC4/A4）。
- **私有数据隔离**：`seal_intraday.db` 存 VR_DATA_DIR（不入 git），`intraday_features` / `seal_derived_features` 同库。
- **防封**：R6 tencent_quote 走腾讯源（不封 IP，60s TTL 缓存）；R2 fflow 若走 em_get 限流+熔断+代理探测（不裸调 requests）。
- **可复现**：`compute_trajectory` / `compute_derived_features` 是纯函数，输入 snapshots 列表确定 → 输出确定，`financial_rigor.py` 可复算（AC6）。
- **60s 粒度近似**：`broken_duration_min` 标注粒度限制（AC7），可能漏 <60s 短时炸板。
- **§13.0**：foundation 数据管道（找 edge 的数据采集），非新 alpha 战法层；edge 是 bonus（不成也有复盘值）。

---

## 5. 风险与回滚

- **tencent_quote 60s 缓存导致 low_price 不够新鲜**：盘中行情分钟级变化，60s TTL 是 trade-off（避免高频重复请求封 IP）。若需更新鲜，TTL 可调短（但当前 60s 与 seal_intraday 采集周期一致，同周期内取一次即可）。
- **limit_pct 反推涨停价精度**：`limit_price = price / (1 + limit_pct/100)` 依赖首快照 price≈涨停价。若首封时刻 price 偏离涨停价（如刚封板时成交价未达涨停），反推有误差。降级方案：退回首价近似标 degraded。
- **broken_duration_min 60s 粒度漏短时炸板**：<60s 的瞬炸瞬封会被漏计。标注 granularity_note，不阻塞接入（A7）。
- **R2 端点不可行 defer**：不阻塞 R1/R3/R6/R7，管道仍跑通。R2 deferred 时 `intraday_features` 无资金流因子列（表结构预留，值 None）。
- **回滚**：本期为既有表加 2 列 + 新建 2 表 + 1 新模块 + executor 扩。回滚=移除 `strategies/intraday_features.py`、删除 2 个迁移、还原 `collect_once`/`save_snapshots`/`_execute_seal_intraday_collect`、删 2 表（`DROP TABLE intraday_features; DROP TABLE seal_derived_features;`）。既有 S055 采集 + 规则引擎不受影响。
