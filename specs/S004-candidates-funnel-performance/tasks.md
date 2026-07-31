# 任务拆分 · S004 候选池漏斗性能优化

> 对应：`spec.md`（规范）+ `plan.md`（技术方案）
> 粒度：原子任务（独立可验）。每条含：依赖、改动文件、验收方式、映射 AC。
> 规则：TDD（先 RED 再 GREEN）；每代码 task 跑 `pytest -m "not live"`；不写方向/参考价位/主观评分（合规）。

## 阶段 A · 调研（已完成）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A0 | 各 source 耗时表（fund_flow/catalyst 逐只 em_get 为瓶颈；activity 已批量；em_get 串行锁约束） | — | — | 结论写入 `plan.md` §0 | R1 |

## 阶段 B · 限界 + 缓存（最大收益、低风险）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | R3 限界：`run_funnel` R1 后 top-N（默认 80）进 R2；`config.py` 加 `CANDIDATE_FUNNEL_MAX_R2` + env | A0 | `candidate_funnel/funnel.py`、`config.py` | 单测：mock `gene.fetch_genes` 返 200 只带 gene_score，断言进 activity/fund_flow 的 codes ≤ 80 | R3 |
| B2 | R4 缓存：`funnel.py` 模块级 `_FUNNEL_CACHE`（TTL 300）+ 路由 `@cache_response` TTL 60→300 | A0 | `candidate_funnel/funnel.py`、`routers/candidates.py` | 单测：第二次 `run_funnel` 不再调 source、返回等值 | R4 |

## 阶段 C · 并行（独立 source）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | R2 并行：独立组 A（gene/board/auction）`ThreadPoolExecutor(4)`；依赖组 B（activity/fund_flow）R1 后并行；**不做** fund_flow 逐只并行 | B1 | `candidate_funnel/funnel.py` | 单测：mock 三 source 各 sleep 1s，断言总墙钟 < 2.5s | R2 |

## 阶段 D · 盘后预计算

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| D1 | R5 预计算：`TaskExecutor._executors["candidate_funnel_precompute"]` 调 `run_funnel` 预热（失败不抛）；`/api/scheduled-tasks/types` 追加 | B2 | `scheduled_tasks.py` | 单测：mock run_funnel 置标志，调 executor 断言被调且不抛；`/api/scheduled-tasks/types` 含该项 | R5 |

## 阶段 E · 验收 + 回归

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| E1 | live 验收：清缓存计时 A1≤30s、A2≤1s、预计算后 A3≤1s、并发 pardon A4≤2s | B1,B2,C1,D1 | — | :8900 live 计时 | A1-A4 |
| E2 | 全量回归：`pytest -m "not live"` 0 失败 + `tests/test_s004_funnel_perf.py` 全绿 | E1 | — | pytest 全过 | A5,A6 |

## 依赖图

```
A0(✅) → B1(限界) → C1(并行) ──┐
        B2(缓存) ─────────────┤→ D1(预计算) → E1(live) → E2(回归)
```

## 规模与取舍
- 最大收益最低风险：**B2 缓存 + D1 预计算**（请求侧 ≤1s，与计算耗解耦）。
- B1 限界降预计算墙钟并封顶 r1_kept。
- C1 仅并行独立 source；fund_flow 逐只并行**不做**（em_get 锁约束，见 `plan.md` §3）。
