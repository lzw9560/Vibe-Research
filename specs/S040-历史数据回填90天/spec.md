# Spec: S040 — 历史涨停池数据 K 线重建 + 双轨累积（v2）

> 状态：R1-R9 代码完成（`feature/S040-backfill90` / 817becd+8f9e1b9+4d3bc2f+a0e46bb，测试 57/57）；live smoke 通过（单日重建50只涨停股，data_source/missing_factors 标注正确）；90天后台回填执行中（nohup PID 79124）
> 作者：Codex  日期：2026-08-09
> 关联：`backend/limitup_screener/models.py`（compute_factors/calc_total_score/ZTPoolItem）、
> `backend/limitup_screener/service.py`（get_screener_result/save_gene_scores）、
> `backend/limitup_screener/data.py`（gene_scores DB PK+INSERT OR REPLACE）、
> `backend/backtest_lite.py`（S040 已合 kline_cache）、`../S043-次日溢价率单因子分析/spec.md`（连板率因子）、
> `../../../daily-stock-analysis/daily_stock_analysis/data_provider/tickflow_fetcher.py`（_round_limit_price 参考）
>
> 级别：**large**（新增 K 线重建引擎 + 因子降级标注 + 双轨 + DB schema 扩展 + 测试）

## 0. 方向性转变说明（v1→v2）

v1 假设"调东财涨停池 API 回填 90 天"。live 冒烟实测推翻该假设：push2ex 是滚动快照接口，历史窗口仅约 4 周，DB 已全覆盖 API 存量。纯免费现成源（akshare stock_zt_pool_em）经实测同窗口。Tushare limit_list_d 需 5000+ 积分（当前 token 不够）。

grill 共识（2026-08-09）：改走**K 线重建路线**——从日 K 线推导历史涨停池 + 基因分（诚实降级），保留增量轨双轨并行，结果准确性随增量数据逐日收敛。引入 TickFlow 作为 K 线源 + `_round_limit_price` 涨停价精度逻辑参考。

**用户根本前提**：打造可靠的投研助手，不为实现而实现。降级数据必须诚实标注，不造假。

## 1. 问题 / 目标

1. 用日 K 线重建历史涨停池（90+ 交易日）：从 K 线判定涨停日 + 连板数，构造等价 ZTPoolItem 喂给 `compute_factors`
2. 只算 K 线能准确推导的 3 因子（连板率/红盘率/涨停频次），2 个不可推因子（封板率/炸板后溢价）标注 `unavailable`
3. total_score 用 3 因子加权重算（权重重定，非原 5 因子权重）
4. DB 记录标注 `data_source`（`kline_rebuild` / `eastmoney_live`）+ `missing_factors`，下游自行判断采信
5. 增量轨保留：`limitup_precompute` cron（back_days 3→10），完整 5 因子数据占比逐日提升
6. TickFlow 引入为 K 线源（mootdx 备用 + 涨停价精度逻辑参考）

## 2. K 线可推性矩阵

| ZTPoolItem 字段 | K 线可推？ | 推导方式 | 对应因子 |
|---|---|---|---|
| code | ✓ | K 线自带 | — |
| name | △ | K 线通常不含名称，从其他源补或留空 | — |
| boards（连板数） | ✓ | 连续日涨停天数（close ≥ 涨停价） | 次日溢价率 |
| limit_pct（涨幅） | ✓ | (close - prev_close) / prev_close * 100 | 红盘率 |
| pool_date | ✓ | K 线日期 | 涨停频次 |
| prev_close | ✓ | 前一日 close | — |
| limit_price | ✓ | `validate_limit_up_price(prev_close, code)` | — |
| seal_time（封板时间） | ❌ | K 线无盘中数据 | 封板率 |
| broken_count（炸板次数） | ❌ | K 线无盘中数据 | 炸板后溢价 |
| seal_amount（封单额） | ❌ | K 线无 | —（非因子） |
| float_shares（流通盘） | ❌ | K 线无 | —（非因子） |

**结论**：3/5 因子可准确推导（连板率/红盘率/涨停频次），2/5 不可推（封板率/炸板后溢价）。

## 3. 需求清单

- [ ] R1 新模块 `backend/limitup_screener/kline_rebuild.py`：给定日期范围，从日 K 线判定涨停股 + 连板数，构造 ZTPoolItem 列表，调 `compute_factors` + `calc_total_score`（3 因子权重）生成 GeneScore
- [ ] R2 涨停判定：`close ≈ validate_limit_up_price(prev_close, code)` 容差内（参考 tickflow_fetcher._round_limit_price 精度逻辑）；主板 ±10% / 创业板科创板 ±20% / ST ±5%
- [ ] R3 连板数推导：连续日涨停天数（boards = 连续 close 达涨停价的天数）
- [ ] R4 因子降级：不可推因子（封板率/炸板后溢价）值设为 `None`（非 0），factors dict 中标注；total_score 用 3 因子重算权重（次日溢价率 0.40 + 红盘率 0.40 + 涨停频次 0.20）
- [ ] R5 DB schema 扩展：gene_scores 表加 `data_source TEXT DEFAULT 'eastmoney_live'` + `missing_factors TEXT`（JSON 数组或空）；旧数据默认 `eastmoney_live` + 空 missing
- [ ] R6 回填脚本 `backfill_history.py` 加 `--source kline` 模式：调 kline_rebuild 模块重建历史日期，写 DB 标注 `kline_rebuild` + `missing_factors=["封板率","炸板后溢价"]`
- [ ] R7 增量轨：`limitup_precompute` seed task 的 back_days 3→10
- [ ] R8 TickFlow 引入：新增 `backend/data/sources/tickflow.py` fetcher（K 线 + 涨停价精度），mootdx 为主、TickFlow 兜底
- [ ] R9 下游消费方适配：`backtest_lite` / `strategy_backtest` 读 `data_source` 字段，`kline_rebuild` 数据在分析结果中标注"重建数据，缺失封板率/炸板后溢价"

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/limitup_screener/kline_rebuild.py`（新） | R1/R2/R3 K 线重建引擎 |
| `backend/limitup_screener/models.py` | R4 calc_total_score 加 3 因子模式（参数 `weights="rebuild"`） |
| `backend/limitup_screener/data.py` | R5 schema 扩展 + save/load 兼容新字段 |
| `backend/migrations/limitup_screener/` | R5 新迁移 SQL |
| `backend/backfill_history.py` | R6 加 `--source kline` 模式 |
| `backend/scheduled_tasks.py` | R7 back_days 3→10 |
| `backend/data/sources/tickflow.py`（新） | R8 TickFlow fetcher |
| `backend/backtest_lite.py` | R9 读取 data_source 标注 |
| `backend/strategies/strategy_backtest.py` | R9 同上 |

## 5. 设计方案

### D1 K 线重建引擎（kline_rebuild.py）

```
async def rebuild_date(date: str, kline_source="mootdx") -> list[GeneScore]:
    1. 获取全市场当日涨停股：
       - 方案 a：从 K 线扫全市场（太慢，需扫 ~5000 只）
       - 方案 b：用东财涨停池 API（窗口内）或 K 线扫当日涨幅榜前 N
       → 选方案 b：先试 em_zt_topic_pool（窗口内有效），窗口外用 K 线补扫当日涨幅榜
    2. 对每只涨停股，取其过去 LOOKBACK_DAYS 日 K 线
    3. 逐日判定涨停 + 连板数：close ≈ validate_limit_up_price(prev_close, code)
    4. 构造 ZTPoolItem（boards/limit_pct/pool_date/prev_close/limit_price 有值，seal_time/broken_count=None）
    5. 调 compute_factors(history, yzt=[], zb=[]) —— yzt/zb 无法重建，炸板后溢价=0 标 unavailable
    6. calc_total_score(factors, weights="rebuild") —— 3 因子权重
    7. 返回 GeneScore 列表，factors 中封板率/炸板后溢价=None
```

### D2 3 因子权重重定

| 因子 | 原权重 | 重建权重 | 理由 |
|---|---|---|---|
| 次日溢价率（连板率） | 0.25 | **0.40** | 核心因子，S043 已验证预测力，可准确推 |
| 红盘率 | 0.25 | **0.40** | 可准确推，与连板率互补 |
| 涨停频次 | 0.10 | **0.20** | 可准确推，原权重偏低提升 |
| 封板率 | 0.25 | 0（unavailable） | K 线不可推 |
| 炸板后溢价 | 0.15 | 0（unavailable） | K 线不可推 |

### D3 TickFlow fetcher

- API：`https://api.tickflow.org/v1/...`（待探实际端点），key 从 `.env` 读 `TICKFLOW_API_KEY`
- 能力：日 K 线（730 天回溯）+ `_round_limit_price` 涨停价精度逻辑
- 定位：mootdx 为主 K 线源，TickFlow 兜底（mootdx 失败时 fallback）

### D4 收敛语义

- DB 中 `data_source='eastmoney_live'` 的记录占比 = 完整 5 因子可靠性比例
- 随增量轨每日累积，`eastmoney_live` 占比从当前 26/90 ≈ 29% 逐日提升
- 下游分析（S041/S042）可按 `data_source` 过滤：只统计 `eastmoney_live` 或混合统计时标注重建数据占比

## 6. 验收标准

- [ ] A1 `kline_rebuild.rebuild_date("2026-05-11")` 返回涨停股 GeneScore 列表，factors 含 3 个有值 + 2 个 None
- [ ] A2 重建的连板数与 K 线数据一致（手工核对 3 只股）
- [ ] A3 `data_source='kline_rebuild'` 的记录 `missing_factors=["封板率","炸板后溢价"]`
- [ ] A4 `backfill_history.py --source kline --days 90` 写入 ≥ 90 个交易日记录
- [ ] A5 增量轨 `limitup_precompute` back_days=10，seed task 已更新
- [ ] A6 `pytest -m "not live"` 全过（新测试 + 现有测试不破）
- [ ] A7 下游 `backtest_lite.run_backtest_async` 读 `data_source`，重建数据在结果中标注
- [ ] A8 合规：重建数据诚实标注 `kline_rebuild` + `missing_factors`，不冒充完整数据

## 7. 合规与工程底线自查

- [ ] 重建数据来自公开 K 线（客观事实），不涉方向性研判
- [ ] 降级标注诚实——`data_source` + `missing_factors` 如实记录，下游可见
- [ ] 不造假值——不可推因子设 `None`（非 0 或占位值）
- [ ] 增量轨走限流层，不绕过 em_get
- [ ] TickFlow API key 走 .env，不进 git
- [ ] 无私有数据进 git

## 8. 测试计划

- pytest：K 线涨停判定（mock K 线，验证连板数/涨停价精度）
- pytest：compute_factors 降级模式（3 因子有值 + 2 None）
- pytest：calc_total_score rebuild 权重
- pytest：DB schema 兼容（旧数据 data_source 默认 eastmoney_live）
- pytest：backfill --source kline 模式（mock kline + DB 隔离）
- live：`rebuild_date("2026-05-11")` 实跑验证涨停股数量合理（50-150 只）
- live：`backfill_history.py --source kline --days 90` 写入验证

## 9. 风险与回滚

- **涨停价精度**：四舍五入 + tick size 不一致可能导致误判。参考 tickflow_fetcher._round_limit_price 容差逻辑。
- **ST 状态历史**：ST 股的 ±5% 限制随时间变化，重建需历史 ST 状态表。若无则 ST 股按 ±10% 误判——接受此误差，标注。
- **新股首日**：无涨跌幅限制，需排除（上市日期 < N 天的排除）。
- **性能**：全市场扫 K 线太慢，用涨幅榜前 N + 当日涨停池 API（窗口内）组合。
- **回滚**：kline_rebuild.py 是独立模块，不跑不产生数据。DB schema 加字段是加法迁移，旧数据不受影响。back_days 改动是 seed task 参数，可回退。

## 10. 与 v1 的继承关系

- v1 已合 `feature/S040-backfill90`（817becd）：backfill_history.py 脚本 + backtest_lite kline_cache + 测试 13/13 → **保留**，v2 在此基础上扩展
- v1 的 `--days`/`--range`/`--dry-run`/`--force`/`--batch-size` 参数 → 保留
- v1 的"调 API 回填"逻辑 → 保留为默认 `--source eastmoney`，新增 `--source kline` 模式
- v1 的 live 验收（A1-A4 原）→ 被 A4（--source kline --days 90）替代
