# Spec: S065 — weather_history 持久化

> 状态：已实现（2026-08-13）— R1-R6 全落地：迁移幂等（import 即建表）+ weather_history.py 读写（UPSERT 幂等）+ compute_weather_snapshot 纯函数（复用 _calculate_*_for_date，无行 missing 不臆造）+ 盘后 _execute_sti_post_market 写入（失败不阻断）+ backfill 脚本（8 行实跑幂等）+ 端点 GET /api/sentiment/weather/history + 9 单测 passed。回填产出：2026-07-21~08-13 共 8 行（晴天5/阴天2）。
> 作者：Claude  日期：2026-08-13
> 级别：medium（跨层，零外部数据源——纯本地 DB 计算）
> 关联：`../../docs/workflows/short-term-win-rate-optimization-workflow.md` §3 W1（证据层前置）、`../S063-情绪管线贯通与盘中辅助决策/spec.md`（sti_timeline + sti_intraday 迁移范式）、`../S056-天气熔断三铁律补全/spec.md`（weather_state 消费方）

## 1. 问题 / 目标

WR-Workflow W1 证据层要求按 weather 四态分层出"phase × 次日收益"证据表，验收门"闸门状态可回放复现"。但 weather_state 目前只有实时计算（`get_weather_latest()` 五因子加权），**无历史持久化**——`get_weather_timeline()` 虽能从 sti_timeline dimensions 重算历史天气，但无快照、不可回放，五因子明细也不落库。

目标：建 weather_history 持久化——每日盘后落 weather_state 快照 + 五因子明细，为 W1-W4 提供可回放的真地基。本 spec 只建基础设施，不硬凑证据（样本积累需时间：sti_timeline 8 行 → n≥30/档 至少到 9 月中）。

## 2. 背景

- `_calculate_weather_state(sti_score, risk, sector, capital, public)` 五因子加权 → 晴天/阴天/极端反弹/暴风雨，已有（`routers/sentiment_weather.py:27`）。
- `_calculate_{risk,sector_continuity,capital_momentum,public_sentiment}_for_date(date)` 四个历史函数已有（只读 sti_timeline dimensions，无 em_get）——可复用做历史快照计算。
- sti_timeline 仅 8 行（2026-07-21 起）；scatter.json 5267 行跨 2026-01-05~08-10 但无 weather 字段——历史天气不可臆造回填（emotion 历史不可得，诚实边界）。
- sti_timeline.db 已有 sti_intraday 表迁移范式（`migrations/sti/20260813-001/002` + `limitup_sti/__init__.py` import 时接线），可镜像。

## 3. 需求清单

- [ ] R1 weather_history 表迁移（date PK + weather_state + 五因子明细 + phase + confidence + computed_at），幂等
- [ ] R2 读写模块 `weather_history.py`：save_snapshot（UPSERT）/ get_by_date / get_history
- [ ] R3 `compute_weather_snapshot(date)` 纯函数：复用现有 `_calculate_*_for_date` + `_calculate_weather_state`，sti 无行 → missing 不臆造
- [ ] R4 盘后写入：`_execute_sti_post_market` 成功后落当日快照，失败不阻断 STI 主流程
- [ ] R5 回填脚本：遍历 sti_timeline 存量日期幂等回填（零 em_get）
- [ ] R6 查询端点 `GET /api/sentiment/weather/history?days=`

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/migrations/sti/20260813-003_create_weather_history.sql` | R1 建表 |
| ➕`backend/weather_history.py` | R2 读写函数 |
| `backend/routers/sentiment_weather.py` | R3 compute_weather_snapshot + R6 端点 |
| `backend/limitup_sti/__init__.py` | R1 迁移接线（import 时 upgrade） |
| `backend/scheduled_tasks.py` | R4 盘后写入接线 |
| ➕`backend/scripts/backfill_weather_history.py` | R5 回填入口 |
| ➕`backend/tests/test_weather_history.py` | R1-R6 测试 |

## 5. 设计方案

- **纯函数化现有重算逻辑**：`compute_weather_snapshot(date)` = 四个 `_calculate_*_for_date` + sti_timeline 当日 score/phase → `_calculate_weather_state`。不新造计算口径，复用既有。
- **UPSERT 落库**：`INSERT OR REPLACE` by date，幂等可重跑。
- **盘后写入不阻断主流程**：STI 计算成功后 try/except 落快照，失败只记 warning。
- **不启动自动回填**：避免每次启动扫描；手动脚本回填存量 8 行。
- **诚实边界**：sti_timeline 无该日行 → `data_status=missing`，不臆造 weather；历史天气（emotion 不可得）只从 sti_timeline 覆盖日起积累。

## 6. 验收标准

- [ ] A1 迁移幂等（fresh DB import 即建表）
- [ ] A2 盘后任务跑完 weather_history 落当日行
- [ ] A3 回填脚本幂等（跑两遍行数不变）
- [ ] A4 端点返回快照 + 五因子字段
- [ ] A5 `pytest -m "not live"` 全绿

## 7. 合规与工程底线自查

- [ ] 零 em_get（纯本地 DB 计算，`_calculate_*_for_date` 只读 sti_timeline）
- [ ] 不臆造（sti 无行 → missing）
- [ ] 快照落 .gitignored DB（sti_timeline.db，私有数据不进 git）
- [ ] 不涉及方向性判断/推荐

## 8. 测试计划

- 单测 `test_weather_history.py`：迁移幂等 + save/get round-trip + UPSERT 幂等 + compute_weather_snapshot（有行/无行）+ 端点 + 盘后写入
- 全量 `pytest -m "not live"`

## 9. 风险与回滚

- 盘后写入异常阻断 STI → 已守 try/except 不阻断
- 迁移失败 → 已守 try/except warning（不影响主流程，limitup_sti/__init__ 范式）
- 回滚：删迁移 + weather_history.py + 端点；表保留无副作用
