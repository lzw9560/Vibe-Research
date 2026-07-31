# Plan: S016 — 测试网技术方案

> 对应 `spec.md`。细化 pytest.ini、conftest fixture、录制回放、vitest、CI。

## 1. pytest.ini

```ini
[pytest]
markers = live: 联网实测（默认跳过）
addopts = -m "not live" --cov=backend --cov-report=term-missing
testpaths = backend/tests
```
- 纯函数门槛按模块设（见 §6），避免 IO 拉低整包覆盖率

## 2. conftest 补 fixture

```python
@pytest.fixture
def isolated_market_db(tmp_path, monkeypatch):
    monkeypatch.setattr("scheduled_tasks._DB_PATH", str(tmp_path/"test.db"))
@pytest.fixture
def state_machine(): return WorkflowStateMachine()
@pytest.fixture
def cron_scheduler(isolated_market_db): return CronScheduler(...)
```
- 已有 VR_DATA_DIR 隔离保留；scheduler/workflow fixture 新增

## 3. 录制回放 contract test

- `tests/contract/test_io_playback.py`：mock `astock._http_get`/`em_get` 返回 S007 基线 JSON
- 比对 `astock.tencent_quote(code)` 返回的模型字段值与基线一致
- 不联网（`not live`），稳定可回归
- 录制一次（S007 `record_baseline.py`，`live` 标记手动跑）

## 4. 前端 vitest

- `vitest.config.ts`（S007 骨架已有）
- 关键 page 快照：`src/test/{DailyReview,Workflow,SentimentWeather,StockDeep}.test.tsx`
- client 契约：`client.test.ts`（鉴权/JSON/解包/错误）

## 5. CI 流水线

```yaml
jobs:
  backend: run: cd backend && .venv/Scripts/python.exe -m pytest -m "not live" --cov
  frontend: run: cd frontend && npm ci && npm run build && npx vitest run
  drift: run: cd frontend && npm run gen:api && git diff --exit-code src/lib/api/types.ts
```
- 后端 cov + 前端 build+vitest + codegen 漂移校验

## 6. 覆盖率两口径

- 纯函数（astock `_parse_gtimg`/`calc_peg`/`pe_digestion`/`get_prefix`、limitup 计算、sti 计算）：≥80%
- IO 函数：录制回放 contract test 覆盖代表性路径，不设硬门槛
- `--cov` 按纯函数模块设（`--cov=backend.models,backend.limitup_screener.models,...`）

## 7. 回归 bug 专项

`tests/test_regression_bugs.py`：
- `test_risk_models_kline_nonzero`（S008 get_kline→kline）
- `test_scheduled_tasks_imports`（S011 timedelta/asyncio）
- `test_seat_engine_defaults_isolated`（S008 可变默认值）
- `test_cache_response_key_unique`（S015 key 修）

## 8. 实现步骤
1. pytest.ini + conftest fixture
2. IO 录制回放测试
3. 回归 bug 专项
4. 前端关键 page 快照 + client 契约
5. CI 流水线
6. 验证：pytest+cov + build + vitest + drift 全绿

## 9. 风险点
- 80% 门槛按纯函数模块设避免 IO 拉低
- 前端快照脆性 → 子组件快照分立
- CI 需 Python+Node 双环境 → 分 job
