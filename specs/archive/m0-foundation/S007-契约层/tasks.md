# Tasks: S007 — 契约层

> 原子任务拆分。依赖 `spec.md`/`plan.md`。标记：▶ 进行中 / ✅ 完成。

## 任务清单

| ID | 任务 | 依赖 | 验收 |
|---|---|---|---|
| T1 | 建 `backend/models/enums.py`（Market/ReportType/STIPhase） | — | 导入可用；枚举值齐 |
| T2 | 建 `backend/models/normalize.py`（`normalize_stock_code`） | T1 | A股/港/美/韩代码归一正确 |
| T3 | 建 `models/quote.py`（Quote，frozen，§5.1 单位） | T1 | 字段齐；`market_cap_yi` 派生 |
| T4 | 建 `models/valuation.py`（Valuation） | T1 | 字段齐 |
| T5 | 建 `models/report.py`+`news.py` | T1 | 字段齐 |
| T6 | 建 `models/market_snapshot.py`（含 Emotion/Sector，**不含个股名**——设计选择，非合规红线） | T1 | Emotion 无个股字段 |
| T7 | 建 `models/fund_flow.py`+`kline.py`（KLine/KLineBar） | T1 | 字段齐 |
| T8 | `models/__init__.py` re-export | T3-T7 | `from models import Quote` 可用 |
| T9 | 写 `tests/contract/record_baseline.py`（标 live） | T8 | 脚本可跑 |
| T10 | 跑一次录制 10 code 快照（手动 live） | T9 | `baseline/*.json` 存在 |
| T11 | 写 `tests/contract/test_models.py`（round-trip+必填+缺失+frozen） | T8,T10 | `not live` 全过 |
| T12 | `backend/conftest.py` 补 baseline 夹具 fixture | T11 | 测试可读 baseline |
| T13 | 建前端 `vitest.config.ts`+`src/test/setup.ts` | — | vitest 可跑 |
| T14 | `src/test/client.test.ts` 占位 | T13 | `npx vitest run` 过 |
| T15 | `pytest -m "not live"` + `npx vitest run` 全绿 | T11,T14 | 全绿；astock 返回值未变（A7） |

## 依赖图
```
T1 ── T2
T1 ── T3..T7 ── T8 ── T11 ── T15
T8 ── T9 ── T10 ── T11
T13 ── T14 ── T15
```

## 合规检查点
- T6 Emotion 无个股名（§1 四池聚合 → 设计选择，2026-07-30：聚合指标 vs 客观榜单分层，非硬约束）
- T10 baseline 无私有数据
