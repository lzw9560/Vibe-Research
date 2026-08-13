# Spec: S016 — 测试网（后端覆盖率 + IO 录制回放 + 前端 vitest + CI）

> 状态：部分实现（基建已搭，四项缺口待补）——2026-08-13 归档补录。已落地：`backend/pyproject.toml` pytest+coverage 配置（R1/R2）、`backend/conftest.py` DB 隔离 fixture（R1/R2）、`frontend/vitest.config.ts` + 20+ 组件测试（R6 部分）。缺口：R4 IO 录制回放夹具（`backend/tests/contract/baseline/` 仅有 README）、R3 80% 覆盖率门槛（pyproject 注释待定）、R7 回归专项测试、R8 CI 流水线（无 `.github/workflows/`）。
> 作者：Claude  日期：2026-07-29
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 10 步）、`../S007`（契约基线夹具）、`../S011`（scheduler/状态机单测）、`../../CLAUDE.md` §2（测试命令）

---

## 1. 问题 / 目标

后端纯计算层覆盖好（limitup_screener ~70%/limitup_sti ~75%），原始数据层/调度/状态机 0 覆盖；无 `pytest.ini`/覆盖率/CI 配置；前端零测试（无 vitest/jest）；conftest 无 scheduler/workflow fixture，不隔离 `market_data.db`；模式为"bug 驱动补测"非 TDD。静默 bug（get_kline、缺 import）均未被测试捕获。

**目标**：后端纯函数 ≥80% 行覆盖；IO 函数用录制回放 contract test（不设硬门槛）；前端 vitest + @testing-library 关键 page 快照；conftest 补 scheduler/workflow/market_data.db 隔离 fixture；CI 集成覆盖率门槛。

## 2. 背景

- S007 已建 `tests/contract/baseline/` 10 只 code 录制夹具 + 契约测试骨架。
- S011 已要求补 cron/TaskExecutor/状态机单测；S012 桩测试；S014 前端 vitest。
- 本 spec 是测试网总收口：覆盖率配置 + CI + fixture 补全 + 前端测试基建。

## 3. 需求清单

- [ ] R1 建 `backend/pytest.ini`：`-m "not live"` 默认、`--cov=backend --cov-report=term-missing`、纯函数门槛 80%
- [ ] R2 `conftest.py` 补：`market_data.db` 临时隔离、scheduler/workflow_state_machine fixture、VR_DATA_DIR 隔离已存在
- [ ] R3 后端纯函数覆盖率 ≥80%（astock 纯函数 `_parse_gtimg`/`calc_peg`/`pe_digestion`/`get_prefix`、limitup 计算、sti 计算、pctColor 等）
- [ ] R4 IO 函数用 S007 基线录制回放 contract test 覆盖代表性路径（不设硬行覆盖门槛）
- [ ] R5 scheduler/状态机/TaskExecutor 单测（S011 要求，本 spec 验收汇总）
- [ ] R6 前端 `vitest.config.ts` + `@testing-library/react` + 关键 page 快照（DailyReview/Workflow/SentimentWeather/StockDeep）
- [ ] R7 前端 `lib/api/client.ts` 契约测试（鉴权/JSON/解包/错误）
- [ ] R8 CI：`pytest -m "not live" --cov` + `npm run build` + `npx vitest run`；覆盖率低于门槛失败
- [ ] R9 回归 bug 专项测试：get_kline 非零、scheduled_tasks import、seat_engine 可变默认值、cache_response key 不撞（来自各 spec）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/pytest.ini` | ➕覆盖率+marker 配置 |
| `backend/conftest.py` | ✏️补 market_data.db 隔离+scheduler/状态机 fixture |
| ➕`backend/tests/test_cron.py`/`test_task_executor.py`/`test_state_machine.py` | ➕（S011 落地，本 spec 验收） |
| ➕`backend/tests/contract/test_io_playback.py` | ➕IO 录制回放 |
| ➕`backend/tests/test_regression_bugs.py` | ➕回归 bug 专项 |
| ➕`frontend/vitest.config.ts` | ➕（S007 骨架，本 spec 补配置） |
| ➕`frontend/src/test/*.test.tsx` | ➕关键 page 快照+client 契约 |
| ➕`.github/workflows/ci.yml` 或等效 | ➕CI 流水线 |

## 5. 设计方案

- **两口径**：纯函数 ≥80% 行覆盖（可达成）；IO 函数用录制回放 contract test 覆盖代表性路径，不设硬门槛（网络 IO 强求 80% 产出脆性 mock）。
- **录制回放**：S007 基线 10 只 code 快照，mock 网络层返回，比对字段值——不联网、稳定、可回归。
- **前端快照**：关键 page（DailyReview/Workflow/SentimentWeather/StockDeep）vitest 快照锁渲染结构，拆分时防回归。
- **CI**：PR 触发 `pytest -m "not live" --cov` + `npm run build` + `npx vitest run`；纯函数覆盖率 <80% 失败。
- **取舍**：不追求 100% 覆盖（边际成本高）；优先覆盖数据层/调度/状态机/纯计算 + 关键 page 快照。

## 6. 验收标准

- [ ] A1 `pytest.ini` 就位；`pytest -m "not live" --cov` 产出覆盖率报告
- [ ] A2 后端纯函数覆盖率 ≥80%（astock 纯函数/limitup/sti 计算）
- [ ] A3 IO 函数有录制回放 contract test 覆盖 10 只代表 code
- [ ] A4 scheduler/状态机/TaskExecutor 有单测（S011 验收）
- [ ] A5 前端 vitest 跑通；关键 page 快照存在
- [ ] A6 `lib/api/client.ts` 契约测试过
- [ ] A7 CI 流水线跑通：pytest+cov+build+vitest 全绿
- [ ] A8 回归 bug 专项测试全过（get_kline/import/可变默认值/cache key）
- [ ] A9 conftest 隔离 `market_data.db`（测试不写真实库）

## 7. 合规自查（按新 CLAUDE.md §1）

- [ ] 测试不含方向性判断断言
- [ ] 基线快照无私有数据
- [ ] test_compliance.py 在覆盖率范围
- [ ] 测试不裸调东财（用基线回放）

## 8. 测试计划

- 本 spec 即测试基建，验收 = A1-A9
- CI 跑通即验收

## 9. 风险与回滚

- 🟡 80% 纯函数门槛可能需补测若干模块：分模块推进
- 🟡 前端快照脆性（UI 变更触发快照更新）：关键 page 快照 + 拆分后子组件快照分立
- 🟡 CI 搭建（项目无现成 CI）：用 GitHub Actions 或本地脚本
- 🟢 回滚：删 pytest.ini/vitest 配置（测试不破坏现有行为）
