# Tasks: S016 — 测试网

> 依赖各 spec 的测试要求（S007 基线/S011 调度测/S012 桩测/S014 前端测）。

## 任务清单

| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T1 | 建 `backend/pytest.ini`（marker+--cov+testpaths） | — | pytest 读到配置 | ✅ 2026-07-31 落地；含 `-m "not live"`、`--cov=. --cov-report=term-missing --cov-config=.coveragerc`、`testpaths=tests` |
| T2 | `conftest.py` 补 `isolated_market_db` fixture | — | 测试不写真实库 | ✅ 已存在（S011 落地）：`isolated_market_db` 用 `tmp_path` + `scheduled_tasks/workflow_state_machine.set_db_path` 重定向，`VR_MARKET_DATA_DB`/`VR_DATA_DIR` 环境隔离 |
| T3 | `conftest.py` 补 `state_machine`/`cron_scheduler` fixture | T2 | scheduler/状态机测可用 | ✅ 已存在（S011 落地）：`cron_scheduler`、`state_machine(isolated_market_db)` fixture 均在 conftest.py |
| T4 | `tests/contract/test_io_playback.py`（基线回放） | S007 | 10 code 字段一致 | ⬜ 后续（R4，本任务范围外） |
| T5 | `tests/test_regression_bugs.py`（get_kline/import/可变默认值/cache key） | S008,S011,S015 | 4 bug 回归过 | ⬜ 后续 |
| T6 | `tests/test_cron.py`（*/n/范围/边界） | S011 | cron 匹配过 | ⬜ 后续（S011） |
| T7 | `tests/test_task_executor.py`（各任务+去重+add_run） | S011 | 无重复 run | ⬜ 后续（S011） |
| T8 | `tests/test_state_machine.py`（流转/非法/reset/落库） | S011 | 状态落库可查 | ⬜ 后续（S011） |
| T9 | `tests/test_realtime_post_stubs.py`（NotImplementedError+编排不崩） | S012 | 全过 | ⬜ 后续（S012） |
| T10 | `frontend/vitest.config.ts`（S007 骨架补配置） | S007 | vitest 可跑 | ⬜ R6 前端，本任务范围外 |
| T11 | `src/test/{DailyReview,Workflow,SentimentWeather,StockDeep}.test.tsx` 快照 | S014 | 快照过 | ⬜ R6 前端 |
| T12 | `src/test/client.test.ts`（鉴权/JSON/解包/错误） | S013 | 契约过 | ⬜ R7 前端 |
| T13 | 后端纯函数覆盖率 ≥80%（按模块 --cov） | T4-T9 | 报告达标 | 🟡 基线已测（见下"覆盖率基线"），门槛 `--cov-fail-under` 暂注释，待远程全量跑后按模块定 |
| T14 | `.github/workflows/ci.yml`（backend+frontend+drift 三 job） | T13,T11 | 流水线跑通 | ⬜ R8 CI，本任务范围外 |
| T15 | 验证：pytest+cov + build + vitest + drift 全绿 | T13,T11,T14 | A1-A9 全过 | ⬜ |

## 依赖图
```
T1,T2 ─ T3
S007 ─ T4,T10
S008,S011,S015 ─ T5
S011 ─ T6,T7,T8; S012 ─ T9
S014 ─ T11; S013 ─ T12
T4-T9 ─ T13 ─ T14 ─ T15
```

## 合规检查点
- 测试不含方向性判断断言
- 基线快照无私有数据
- test_compliance.py 在覆盖率范围
- 测试不裸调东财（用基线回放）

## 覆盖率基线（2026-07-31，本地 venv，`-m "not live"`）

> 命令：`cd backend && .venv/Scripts/python.exe -m pytest -m "not live" --cov=. --cov-config=.coveragerc --cov-report=term-missing`
> 本地 venv 缺 lightgbm/mapie/catboost，部分 ML 测试跑不全；纯计算测试可跑。
> 结果：818 passed / 3 failed（contract 基线 + e2e/fixes/market_global_macro 个别，预存失败非本次引入）/ 14 deselected (live)。
> 全包行覆盖：**TOTAL 50%**（15675 stmts / 7877 miss）——含大量 IO/路由/调度未测，拉低整包；纯函数口径见下。

### 纯函数模块（spec R3）实际行覆盖率

| 模块 | Stmts | Miss | 覆盖率 | 达 80%? |
|---|---|---|---|---|
| `astock.py`（`calc_peg`@99 / `pe_digestion`@105） | 64 | 4 | 94% | ✅ |
| `data/sources/tencent.py`（`get_prefix`@23 / `_parse_gtimg`@39） | 43 | 3 | 93% | ✅ |
| `data/mappers.py` | 171 | 15 | 91% | ✅ |
| `data/validators.py` | 54 | 1 | 98% | ✅ |
| `data/transport.py` | 55 | 7 | 87% | ✅ |
| `data/sources/sina_financial.py` | 35 | 7 | 80% | ✅（临界） |
| `limitup_screener/__init__.py` | 19 | 2 | 89% | ✅ |
| `limitup_screener/models.py` | 124 | 5 | 96% | ✅ |
| `limitup_sti/__init__.py` | 8 | 0 | 100% | ✅ |
| `limitup_sti/models.py` | 60 | 3 | 95% | ✅ |
| `limitup_sti/data.py` | 73 | 7 | 90% | ✅ |

### 纯函数 gap 清单（<80%，待补测）

| 模块 | 覆盖率 | 未覆盖行（要点） | gap 性质 |
|---|---|---|---|
| `limitup_screener/data.py` | 53% | 64-94, 142-168, 173-182, 201-216, 221-236, 252-254 | 数据获取/解析分支缺测 |
| `limitup_screener/service.py` | 53% | 46-48, 71-75, 91-93, 118-119, 127, 152-196, 238-265, 274-275, 282, 287-288, 309, 314, 335-390 | 业务编排主路径缺测 |
| `limitup_sti/service.py` | 63% | 78-81, 88-108, 111-118, 135, 168-169, 180-185, 195, 207, 238-293 | STI 计算编排缺测 |
| `utils/data_processing.py` | 15% | 9, 14-29（几乎全未测） | 纯工具函数零测 |
| `utils/sanitize.py` | 40% | 9-11 | 净化函数缺测 |
| `formatters.py` | 18% | 17-31, 36-48, 53-59, 64-71, 76-82, 87-90 | 通知格式化纯函数缺测 |
| `data/sources/akshare_src.py` | 30% | 22-123（多数未测） | akshare 数据源缺测 |
| `data/sources/cninfo.py` | 20% | 17-41 | cninfo 源缺测 |

> 注：spec R3 列的 `_parse_gtimg`/`calc_peg`/`pe_digestion`/`get_prefix` 四个点名纯函数 **全部 ≥93%**，已达 80% 门槛。gap 集中在 limitup_screener/sti 的 service/data 层、utils/data_processing、formatters、部分 data/sources——这些是后续 T4-T9 补测的重点。

### 门槛配置决策

- `pytest.ini` 中 `--cov-fail-under=80` **暂注释**：
  1. 全包口径仅 50%（IO/路由/调度未测拉低），整包门槛会致 `-m "not live"` 全量失败；
  2. 纯函数口径按模块设门槛需 `--cov=backend.limitup_screener.models,...` 逐模块列，但本地缺 ML 依赖跑不全全量；
  3. 待远程全量跑（814 passed 基线）后，按纯函数模块逐个 `--cov-fail-under` 或用 `--cov=package` 分模块设门槛。
- 当前留 `marker + --cov + --cov-report=term-missing`，基线报告可产出，不阻断现有测试。

## 改动文件

- ➕ `backend/pytest.ini`（R1：marker + addopts + testpaths）
- ➕ `backend/.coveragerc`（R1 辅助：source/omit，排除 .venv/tests/catboost_info 等，保留 data/sources 进测量以覆盖 R3 点名纯函数）
- `backend/conftest.py` 无需改（R2 三 fixture 已由 S011 落地，确认存在）
- ✏️ `specs/S016-测试网/tasks.md`（勾选 T1/T2/T3，记 gap）
