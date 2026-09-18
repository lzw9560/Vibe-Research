# Spec: S191 — 每日全量拉取数据基建（RB-3）

> 状态：草案
> 作者：Claude  日期：2026-09-12
> 关联：[[../S185-Turso多源数据湖/spec.md]]、[[../S190-scheduler框架评估/spec.md]] R5、RB-3、用户原话"每日全量拉取不同数据源交易数据，尤其盘中数据，供后期调试盘中策略做数据沉淀"

## 1. 问题 / 目标

用户原话（2026-09-11）："有些必要的数据源，应该每日使用异步框架全量拉取，作为项目数据基建支撑" + "关于 turso 数据库，我的建议是 全量拉取不同数据源交易数据，尤其是盘中数据，供后期调试盘中策略做数据沉淀"。

**现状缺口**：
- S185 turso_sync 只 sync 4 表到云（write-only，无读回）——不是"全量拉取沉淀"
- kline_refresh 增量刷新 baostock（newest→今日，不回溯历史）
- seal_intraday_collect 每分钟采 tencent 五档（live，不补历史）
- ofi_collect 每 3min 拉五档（live，S188 RB-2 刚修接线）
- **缺一个"每日盘后全量拉取 + 沉淀到本地数据湖"的统一机制**——供后期盘中策略调试回放

**目标**：每日盘后全量拉取各源当日数据（K 线/涨停池/分笔/五档/财务），沉淀到本地数据湖（.vibe-research/datalake/），供后期盘中策略调试回放。

## 2. 背景

**数据源 + 沉淀能力现状**：
| 源 | 数据 | 拉取方式 | 沉淀 | 历史 |
|---|---|---|---|---|
| baostock | 日K/5min | kline_refresh 增量 | baostock_kline_cache.json | 174 天 |
| mootdx | 实时五档 + 历史分笔 | ofi_collect live / Quotes.transactions 手动 | intraday_ofi_snapshots（live） | 分笔可回溯（S188 B） |
| tencent | 实时五档 | seal_intraday_collect 每分钟 | seal_intraday_snapshots_YYYYMM | 6 天 |
| ths | 涨停池 | ths_limit_up_pool | zt_history.db（P0-2 fallback） | 42 天 |
| hithink | 涨停池 | limit_up_pool | zt_history.db fallback | 2024-06 回溯 |
| stoke | 研报/新闻/涨停归因/PE-PB | stoke_src.py（S188 接入） | 未沉淀（按需调） | — |

**缺口**：
1. stoke 的研报/新闻/涨停归因/PE-PB **没每日沉淀**（按需调，不存）
2. mootdx 历史分笔（OFI proxy 用）**没每日自动拉**（手动脚本 S188 B 跑过 370 日，不 cron）
3. 数据湖目录分散（baostock_kline_cache.json / seal_intraday_*.db / zt_history.db 各处），无统一 datalake 视图

## 3. 需求清单

- [ ] R1：每日盘后全量拉取 cron——统一 task `daily_full_pull`，盘后 17:35 跑（晚 journal 17:30），拉各源当日数据沉淀。
- [ ] R2：stoke 数据每日沉淀——研报/新闻/涨停归因/PE-PB 存 `.vibe-research/datalake/stoke_YYYYMM.db`（按月分表）。
- [ ] R3：mootdx 当日分笔沉淀——每日拉当日全首板分笔（OFI proxy 用），存 `datalake/ticks_YYYYMM.db`。
- [ ] R4：datalake 统一目录——`.vibe-research/datalake/` 下按源+月分库（baostock/ticks/stoke/seal），统一 resolve_data_dir 管理。
- [ ] R5：回放引擎读回路径——`datalake/replay.py` 按日期+code 从 datalake 拉历史数据回放（模拟实时，供盘中策略调试）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduler/executors/data_ops.py` | 加 `daily_full_pull` executor（调 stoke_src/mootdx_tick_ofi_proxy） |
| `backend/scheduler/seed.py` | seed `daily_full_pull` cron 17:35 + depends_on=trade_journal_daily |
| `backend/data/datalake/` | **新增**——datalake 统一目录 + 各源按月分库 |
| `backend/data/sources/stoke_src.py` | 加沉淀函数（研报/新闻/涨停归因 → datalake/stoke_YYYYMM.db） |
| `backend/tools/mootdx_tick_ofi_proxy.py` | 加当日全首板分笔批量拉取模式（cron 用） |
| `backend/data/datalake/replay.py` | **新增**——读回路径（按日期+code 拉历史数据回放） |

## 5. 设计方案

**每日盘后全量拉取（R1）**：`daily_full_pull` executor 盘后 17:35 跑（晚 journal 17:30 + depends_on=trade_journal_daily 硬门控），拉：
- stoke 当日研报/新闻/涨停归因/PE-PB（R2）
- mootdx 当日全首板分笔（R3，首板 universe 取 zt_history 当日）
- 现有 kline_refresh/seal_intraday/ofi_collect 已 live 采，不重复（depends_on 保证顺序）

**datalake 统一目录（R4）**：`.vibe-research/datalake/` 下：
- `baostock_kline.json`（现有，移或软链）
- `ticks_YYYYMM.db`（mootdx 分笔）
- `stoke_YYYYMM.db`（研报/新闻/归因）
- `seal_intraday_YYYYMM.db`（现有，移或软链）
统一 `resolve_data_dir() / "datalake"` 管理（用户要求唯一 db 存储目录）。

**回放引擎（R5）**：`datalake/replay.py` 按 (date, code) 从各库拉数据，按时间戳排序回放，供盘中策略调试（用户"模拟实时交易"意图）。这是 Turso 读回路径的本地版（Turso 是云端备份，datalake 是本地回放）。

**为何不只靠 Turso**：Turso 是 write-only 云备份（无读回），且用户"数据源湖共后期测试开发使用，分开设计"——datalake 是本地回放层，Turso 是云灾备层，物理分离。

## 6. 验收标准

- [ ] A1：`daily_full_pull` cron 每日跑，沉淀 stoke + mootdx 分笔到 datalake。
- [ ] A2：datalake 各库按月分表，统一 resolve_data_dir 管理。
- [ ] A3：`replay.py` 按 (date, code) 拉历史数据回放，供盘中策略调试。
- [ ] A4：`pytest -m "not live" --deselect` 全绿。

## 7. 合规与工程底线自查

- [x] 盘中数据 live 采（不臆造历史，seal_time 墙已验）。
- [x] datalake 在 .vibe-research/（私有数据隔离，不进 git）。
- [x] mootdx/tencent/stoke 不走东财 em_get，无防封。
- [x] 回放引擎只读回放，不代客决策。

## 8. 测试计划

- daily_full_pull executor 单测（mock stoke/mootdx）。
- replay.py 按 (date,code) 拉数据回放集成测。
- 离线 pytest not live。

## 9. 风险与回滚

- mootdx 分笔全首板拉取量大（~75 股 × 4000 笔/日）→ 限当日首板 ~50 股 + 按需扩。
- stake 限流（akshare 5s/腾讯 3s）→ daily_full_pull 串行 + 间隔。
- 回滚：daily_full_pull 是新 task 不破坏现有 cron；datalake 新目录不影响现有 store。
