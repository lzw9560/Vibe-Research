# 任务拆分 · S040 历史数据回填 90 天

> 对应：`spec.md`（需求）、`plan.md`（技术方案）
> 粒度：原子任务（独立可验，1-2h/条）。每条含依赖、改动文件、验收方式、映射 AC。
>
> 进度（2026-08-09）：阶段 A 免做（PK 已保证幂等）；阶段 B/C 离线实现完成（`feature/S040-backfill90`，测试 13/13）；阶段 D live 验收已完成。
> v2 更新（2026-08-09）：方向性转变——K线重建路线（R1-R9 全部完成，测试 57/57）；live smoke 通过（单日50只）；90天回填完成（2026-08-10）：DB 覆盖 149 个交易日（kline_rebuild 122天 + eastmoney_live 27天，共 5715 条），缺口 5/12~7/8 已补齐（40天成功 + 1天空池 6/19 确认无涨停股）。
> 回归基线：`pytest -m "not live"` 859 passed；5 个失败均为预存（2 环境性 + 3 S044 合并引入），与本 spec 无关（stash 对照验证）。

---

## 阶段 A · 幂等基础（R5）

> 侦察已确认（2026-08-09）：`gene_scores` 表已有 `PRIMARY KEY (date, code)`，`save_gene_scores` 已用 `INSERT OR REPLACE`——A1/A2 免做，A3 并入 `tests/test_s040_backfill.py`。

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | 检查 `limitup_screener/data.py` 的 `save_gene_scores` 写入方式（INSERT vs INSERT OR REPLACE） | — | —（只读） | 确认当前实现 | A3 |
| A2 | 若需补充：加 `UNIQUE(date, code)` 索引 + 改 INSERT OR REPLACE | A1 | `limitup_screener/data.py` | 重复插入同 date+code 不新增行 | A3 |
| A3 | 单测：幂等写入（mock DB，重复调 save_gene_scores，行数不变） | A2 | `tests/test_backfill_idempotent.py` | pytest 过 | A3 |

## 阶段 B · backtest_lite K 线缓存（R3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | `_calc_next_day_return` 改签名加 `kline_cache` 参数，有缓存走缓存、无缓存拉取后存入 | — | `backend/backtest_lite.py` | 单测 mock astock.kline 确认只调一次 | A5 |
| B2 | `run_backtest_async` 内创建 kline_cache dict（含 `_offset` 键）并传入 `_calc_next_day_return` | B1 | `backend/backtest_lite.py` | mock 90 天回测 kline 调用次数 = 唯一 code 数 | A5 |
| B3 | `generate_scatter_data` 同 B2 | B1 | `backend/backtest_lite.py` | 同上 | A5 |
| B4 | 单测：K 线缓存不破坏现有回测结果 | B2,B3 | `tests/test_backtest_lite_cache.py` | pytest -m "not live" 全过 | A6 |

## 阶段 C · 回填脚本（R1/R2/R4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | `backfill_history.py` 骨架：argparse（--days/--start/--end/--batch-size/--dry-run/--no-confirm） | — | `backend/backfill_history.py` | `--help` 输出参数说明 | A1 |
| C2 | 交易日推算：从 today 前推 N 个交易日（复用 _next_trading_day 日历逻辑反向） | C1 | `backend/backfill_history.py` | `--days 10` 输出 10 个日期跳过周末 | A1 |
| C3 | 逐日回填核心：调 `get_screener_result(date)` 写 DB（正式模式）/ 只打印（--dry-run） | C2,A2 | `backend/backfill_history.py` | `--days 1 --dry-run` 打印请求结果 | A1 |
| C4 | 分批逻辑：按 --batch-size 分批，批间打印成功率/耗时/熔断器状态，--no-confirm 跳过交互 | C3 | `backend/backfill_history.py` | `--days 20 --batch-size 10` 分两批，批间暂停 | A1 |
| C5 | 熔断器感知：捕获 CircuitBreaker RuntimeError，sleep 65s 重试，连续 3 次中止 | C3 | `backend/backfill_history.py` | mock 熔断异常 -> 打印等待 -> 重试 | A7 |
| C6 | `grep -rn "em_get\|eastmoney_get" backfill_history.py` 确认无直接调用 | C3 | — | grep 无输出 | A7 |

## 阶段 D · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| D1 | pytest -m "not live" 全绿 | A3,B4 | — | 全过 | A6 |
| D2 | `--dry-run --days 10`：10 天请求成功率 >= 90%，熔断器不 OPEN | C5 | — | live 冒烟 | A1 |
| D3 | `--days 10`（正式）：DB 行数增加，覆盖范围扩展 | D2 | — | `SELECT COUNT(*), MIN(date), MAX(date)` 确认 | A2 |
| D4 | 重复回填同一天：行数不变 | D3 | — | 再跑 --days 1 确认幂等 | A3 |
| D5 | `--days 90`（分批确认后）：DB 覆盖 >= 90 交易日 | D3 | — | SELECT 确认 | A4 |
| D6 | backtest_lite 跑 90 天回测：K 线请求次数 <= 唯一 code 数 | B2,D5 | — | 日志确认或 mock 计数 | A5 |
| D7 | 合规自查：回填走限流层、数据属公开榜单 | — | — | grep 无直接 em_get | A7 |
