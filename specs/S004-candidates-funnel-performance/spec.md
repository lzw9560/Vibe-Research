# Spec: S004 — 候选池漏斗 run_funnel 性能优化

> 状态：草案
> 作者：Claude ｜日期：2026-07-29
> 关联：`../S002-打板工作流重构/spec.md`（候选池漏斗 S002）、`../S003-api-bugfix-batch/spec.md`（candidates 事件循环阻塞已修）
> 技术方案见 `plan.md`；任务拆分见 `tasks.md`。
> 测试基线：2026-07-29 :8900 live 实测 `GET /api/workflow/candidates` 首次 >60s（client 60s 超时未返回）；并发 `weather/pardon` 0.3s（事件循环未阻塞——S003 已解决阻塞，本 spec 只解决"慢"）。

## 1. 问题 / 目标

`/api/workflow/candidates`（及 `/candidates/funnel`、`/funnel/layers`、`/candidates/{code}/diagnosis`）首次请求 >60s，前端不可用。目标：**首次冷请求 ≤30s；命中缓存 ≤1s；盘后预计算使交易时段请求恒命中缓存**。事件循环阻塞已由 S003 修复，本 spec 不再涉及。

## 2. 背景

- `run_funnel` 编排 6 个同步 source：`gene` → `board_ladder` → `activity(r1_kept)` → `fund_flow(r1_kept)` → `auction` → `catalyst(r2_kept)` → 逐只 `build_diagnosis_card`。
- 各 source 已由 `routers/candidates.py` 的 `asyncio.to_thread` 包裹（不阻塞事件循环）；但内部 `em_get` 串行限流（QPS≤2）。
- 合规：漏斗仅客观筛选，不预置标的、不排名、不推荐（S002 已守；本 spec 性能改造不得引入方向性）。

## 3. 需求清单

- [ ] R1 量化各 source 耗时，定位逐只循环 source 与调用数（产出耗时表，见 `plan.md`）。
- [ ] R2 并行化独立 source（`gene`/`board_ladder`/`auction` 互不依赖）；`activity`/`fund_flow` 在 R1 完成后并行。
- [ ] R3 限界 R1 宽源：按基因得分 top-N（默认 80，可配）进入 R2，避免对全市场上百只逐只取数。
- [ ] R4 漏斗级缓存：`run_funnel` 结果按 `(date, stage, cfg_hash)` 缓存，TTL ≥300s，命中直返。
- [ ] R5 盘后预计算：新增定时任务 `candidate_funnel_precompute`，盘后跑一次当日漏斗写缓存；交易时段请求恒命中。
- [ ] R6 首次冷请求 ≤30s；命中缓存 ≤1s；并发期间他端点不被拖累（S003 回归）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/funnel.py` | R2/R3：并行 source、top-N 限界；R4：内置 `_FUNNEL_CACHE` |
| `backend/candidate_funnel/sources/*.py` | R1 后，对逐只循环 source 做批量/并发改写（按 `plan.md` 调研结论） |
| `backend/routers/candidates.py` | R4：`@cache_response` TTL 60→300 |
| `backend/scheduled_tasks.py` | R5：`TaskExecutor._executors` 加 `candidate_funnel_precompute` |
| `backend/config.py` | R3：`CANDIDATE_FUNNEL_MAX_R2`（默认 80）等可配项 |

## 5. 验收标准

- [ ] A1 `GET /api/workflow/candidates` 首次冷请求（清缓存）≤30s 返回 200。
- [ ] A2 第二次请求命中缓存 ≤1s。
- [ ] A3 盘后预计算任务跑过后，交易时段请求恒 ≤1s。
- [ ] A4 candidates 请求期间并发 `/api/sentiment/weather/pardon` ≤2s（S003 回归）。
- [ ] A5 `pytest -m "not live"` 全过；新增 `tests/test_s004_funnel_perf.py` 覆盖缓存命中 + top-N 限界 + 独立 source 并行。
- [ ] A6 合规自查（§6）逐条通过。

## 6. 合规自查（逐条确认）

- [ ] 仅性能改造，未引入方向性建议/标的/排名/预测（实现时口径）。
- [ ] 未触碰涨停四池原始个股名接 API/UI（实现时口径；个股呈现属设计选择，非硬约束）；`market._emotion` 聚合不变。
- [ ] 未改 `chat.SYSTEM_PROMPT`（实现时口径；措辞放宽见 S010）。
- [ ] 不涉及用户私有数据。
- [ ] R2/R5 复用各 source 既有 `em_get` 限流路径，不裸调东财。

## 7. 测试计划

- 单测 `tests/test_s004_funnel_perf.py`：mock 6 source 各置标志/sleep，验证并行墙钟、top-N 限界、缓存命中不重复调 source。
- 集成：:8900 live，清缓存后计时（A1/A2）；预计算后（A3）；并发 pardon（A4）。
- `pytest -m "not live"` 全量。

## 8. 风险与回滚

- `em_get` 全局串行锁 → fund_flow 逐只并行**无收益**（见 `plan.md`），主杠杆为缓存+预计算+限界。
- R3 top-N 可能漏低分但 R3 命中催化的标的——N=80 宽松，且自选（SELF）层不受限。
- R5 预计算失败不阻塞请求（请求侧仍可冷算，只是慢）。
- 回滚：恢复顺序 `run_funnel`、删预计算任务、TTL 回 60。
