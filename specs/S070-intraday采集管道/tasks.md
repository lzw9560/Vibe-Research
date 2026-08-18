# 任务拆分 · S070 intraday 采集管道

> 对应：`spec.md`（AC1-AC8）+ `plan.md`（技术方案，618 行）
> 粒度：原子任务（独立可验，1-2h/条）。每条含：依赖、改动文件、验收方式、映射 AC。
> 规则：每条完成即跑对应单测；不臆造（缺数据标 None）；派生是纯函数；R6 tencent_quote 批量复用 60s 缓存。

---

## 阶段 A · 表迁移（AC1/AC5/AC6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | R6.1 迁移：`ALTER TABLE seal_intraday_snapshots ADD COLUMN low_price REAL` + `limit_pct REAL` | — | `backend/migrations/seal_intraday/20260818-001_add_low_price_limit_pct.sql` | SQL 语法正确；ALTER 后 PRAGMA table_info 含两列 |
| A2 | R3 迁移：`CREATE TABLE intraday_features`（date/code 主键 UNIQUE + trajectory 列）| — | `backend/migrations/seal_intraday/20260818-002_create_intraday_features.sql` | 两表创建；UNIQUE(date,code) 约束生效 |
| A3 | R3 迁移：`CREATE TABLE seal_derived_features`（date/code 主键 + last_lock_time/broken_duration_min/max_drop_pct/limit_price/granularity_note 列）| — | 同 A2 文件 | 表创建；granularity_note DEFAULT '60s粒度近似' |
| A4 | `run_migrations()` 注册新迁移：扩 migrations 列表加 v2（add_low_price_limit_pct）+ v3（create_intraday_features）| A1,A2 | `backend/risk/seal_intraday_collector.py`（line 47-50）| `run_migrations()` 二次调用幂等不报错 |
| A5 | 单测：迁移幂等 + 既有数据行 low_price/limit_pct 为 NULL（不臆造历史）| A4 | `backend/tests/test_s055_seal_intraday_collector.py`（扩）| `pytest backend/tests/test_s055_seal_intraday_collector.py -m "not live" -k migration` 过；AC5 |

---

## 阶段 B · 采集扩展（AC5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | `save_snapshots(rows)` 字段表扩 `low_price` + `limit_pct`（fields 列表 + INSERT SQL 同步加两列）| A4 | `backend/risk/seal_intraday_collector.py`（line 90-117）| rows 含两字段可写入；缺字段填 None 不报错 |
| B2 | `collect_once` 加 tencent_quote 批量取 low：涨停池循环前一次请求全池 codes（60s TTL 缓存复用）| B1 | `backend/risk/seal_intraday_collector.py`（line 168-234）| tencent_quote 失败→low_price=None 不抛；一次批量请求非逐只 |
| B3 | `collect_once` 涨停池循环取 `limit_pct=item.get("zdp")` + `low_price=quotes.get(code,{}).get("low")`，写入 rows | B2 | 同上 | limit_pct 从 zdp 正确落库；low_price 从 tencent low 正确落库 |
| B4 | 单测：tencent_quote mock 返 low→落库正确；tencent_quote 返空→low_price=None；tencent_quote 失败→降级不臆造 | B3 | `backend/tests/test_seal_intraday_collector_low_price.py`（新）| `pytest backend/tests/test_seal_intraday_collector_low_price.py -m "not live"` 过；AC5 |
| B5 | 既有 test_s055 测试补 low_price/limit_pct 字段断言（mock tencent_quote 返回 low）| B4 | `backend/tests/test_s055_seal_intraday_collector.py`（扩）| 既有测试全过，无回归 |

---

## 阶段 C · 派生计算纯函数（AC1/AC6/AC7）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | 建模块骨架：`strategies/intraday_features.py` + docstring（R1/R7 纯函数说明 + 不臆造 + 60s 粒度近似标注）| — | `backend/strategies/intraday_features.py`（新）| `python -c "from strategies.intraday_features import compute_trajectory"` 不报错 |
| C2 | R1 `_linear_regression_slope(ys)`：简单线性回归 slope（y=a+bx，返 b），n<2 返 0.0 | C1 | 同上 | 手算 [1,2,3]→slope=1.0；[3,2,1]→-1.0；[5]→0.0 |
| C3 | R1 `compute_trajectory(snapshots)`：seal_delta（末-首）/seal_max/seal_min/seal_slope/snapshot_count/data_status | C2 | 同上 | 空时序→data_status=missing 各因子 None；单点→slope=0,degraded；10 点→ok |
| C4 | R1 `persist_trajectory(date,code,name,traj,conn)`：UPSERT 写 intraday_features | A2,C3 | 同上 | 同 date/code 二次写入不报错、覆盖；AC1 |
| C5 | R7 `compute_derived_features(snapshots)`：`last_lock_time`（最后一个 open_count==0 的 ts）| C1 | 同上 | 全程封死→末 ts；全程炸板→None；中间炸→最后封死 ts |
| C6 | R7 `compute_derived_features`：`broken_duration_min`（count(open_count>0)×1 分钟，标"60s粒度近似"）| C5 | 同上 | 全程封死→0；全程炸板→全程分钟数；AC7 粒度标注 |
| C7 | R7 `compute_derived_features`：`max_drop_pct`（limit_price=price/(1+limit_pct/100) 反推 → (limit_price-min(low_price))/limit_price*100）| C6 | 同上 | limit_pct 缺→退回首价标 degraded；low_price 全缺→max_drop_pct=None；手算涨停价10/min_low9.5→5.0 |
| C8 | R7 `persist_derived_features(date,code,name,derived,conn)`：INSERT OR REPLACE 写 seal_derived_features | A3,C7 | 同上 | 同 date/code 二次写入不报错、覆盖；granularity_note 固定"60s粒度近似"；AC6 |
| C9 | 单测：trajectory + 派生三因子算法正确性（空/单点/正常/全程封死/全程炸板/中间炸/缺 low_price/缺 limit_pct 全场景）| C4,C8 | `backend/tests/test_intraday_features.py`（新）| `pytest backend/tests/test_intraday_features.py -m "not live"` 过；AC1/AC6/AC7 |

---

## 阶段 D · 持久化 + executor（AC1/AC6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | `_execute_seal_intraday_collect` 扩：collect_once 成功后对每只票调 compute_trajectory + persist_trajectory + compute_derived_features + persist_derived_features | B4,C9 | `backend/scheduled_tasks.py`（line 822-866）| collect_once 成功→trajectory_written/derived_written>0；失败→不跑派生 |
| D2 | executor 异常隔离：派生计算/落库失败 catch 不阻塞主流程（warning + 继续返 result）| D1 | 同上 | 派生抛异常→主 result 仍返，trajectory_written=0，logger.warning |
| D3 | 单测：executor 集成（mock collect_once + mock tencent_quote）→ trajectory/derived 落库可查 | D2 | `backend/tests/test_task_executor.py`（扩）| `pytest backend/tests/test_task_executor.py -m "not live" -k seal_intraday` 过；AC1/AC6 |

---

## 阶段 E · §44 验证占位（AC3/AC4，日历阻塞）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | R4 占位：`tools/intraday_edge_validation.py` docstring 标"日历阻塞，30 日数据积累后实现" + TODO | C9 | `backend/tools/intraday_edge_validation.py`（新）| 文件存在 + docstring 标"探索性/未 validated" |
| E2 | R5 诚实标注确认：intraday_features/seal_derived_features 的 data_status 字段在所有缺数据场景正确标 degraded/missing（非 ok）| C9,D3 | — | 单测断言 data_status≠ok 场景全过；AC4 |

> ⚠️ E 阶段本期不实现验证逻辑（日历阻塞，~30 日后补）。R2 资金流 intraday 同样 defer（plan §2 已声明，不阻塞管道）。

---

## 阶段 F · 门禁（AC8）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| F1 | R8 S081 依赖门禁：R7 落地后通知 S081 spec 可进实现（"数据层未就绪"→"已就绪"）| C9 | `specs/S081-*/spec.md`（依赖字段）| S081 spec 依赖字段翻"已就绪（S070 R7 落地）"；AC8 |

---

## 阶段 G · 验收（全 AC）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| G1 | 逐条核对 AC1-AC8 → plan 实现步骤映射 | A5,B4,C9,D3,E1,F1 | — | AC checklist 全绿（见下表）|
| G2 | `financial_rigor.py` 复算派生三因子（compute_derived_features 纯函数输入输出确定）| C9 | — | 复算结果与函数输出一致；AC6 可复现 |
| G3 | 合规自查（spec §7）：不臆造/私有数据隔离/防封/foundation 非战法层 | 全部 | — | 自查表全绿 |
| G4 | `pytest -m "not live"` 全过 | A5,B4,B5,C9,D3 | — | 全绿 |
| G5 | 写验收报告，更新 spec 状态 | G1-G4 | `specs/S070-*/验收报告.md` | 报告归档 |

### AC checklist（G1 用）

| AC | 要求 | 映射 task | 状态 |
|---|---|---|---|
| AC1 | R1 trajectory 算出 + 持久化 | C3,C4,D1 | ☐ |
| AC2 | R2 资金流 intraday（若可行）| —（defer，日历阻塞）| ☐ deferred |
| AC3 | ~30 日后 §44 60日复验窗口 | E1（占位）| ☐ 日历阻塞 |
| AC4 | 诚实：未满 30 探索性；不臆造 | E2 | ☐ |
| AC5 | R6 low_price 字段 + collect_once 采集 | A1,B3,B4 | ☐ |
| AC6 | R7 派生三因子正确 + 可复算 | C5-C8,G2 | ☐ |
| AC7 | R7 broken_duration_min 60s 粒度标注 | C6,C8 | ☐ |
| AC8 | R8 S081 门禁 | F1 | ☐ |

---

## 依赖图（关键路径）

```
A1→A4→B1→B2→B3→B4→D1→D3→G4
A2→A4                  ↑
A3→A4                  C9→D1
C1→C2→C3→C4→C9
C1→C5→C6→C7→C8→C9
                C9→E1→G1
                C9→F1→G1
                C9→G2→G1
```

- A 阶段迁移是地基，B/C 依赖 A。
- B（采集）和 C（派生纯函数）可并行（B 改 collector，C 新建模块互不冲突）。
- D 依赖 B+C（executor 串采集与派生）。
- E/F 是占位/流程门，依赖 C9（R7 落地）。
- G 依赖全部。
- 关键路径：A1→A4→B3→B4→C9→D1→D3→G4。

---

## 执行规则

1. **一次一任务**：按 ID 顺序，完成一条跑其验收方式再开下一条。
2. **不臆造**：low_price/limit_pct/max_drop_pct/seal_delta 缺失时 None，不补默认值（AC4）。
3. **派生是纯函数**：compute_trajectory/compute_derived_features 输入 snapshots 列表确定→输出确定，不依赖网络（AC6 可复现）。
4. **60s 粒度近似**：broken_duration_min 标 granularity_note="60s粒度近似"（AC7）。
5. **tencent_quote 批量**：B2 一次请求全池 codes（60s TTL 缓存），不逐只请求。
6. **R2 defer**：资金流 intraday 端点待探，本期占位 deferred，不阻塞管道（AC2 标 deferred）。
7. **commit 引用**：commit message 带 S070 + 任务 ID（如 `S070-A1 add low_price_limit_pct migration`）。
