# Spec: S134 — 新浪源熔断器（sina_kline + sina_financial）

> 状态：已实现(2026-09-01) · v2（多 lens review 后修订：10 confirmed/9 refuted，7 缺陷全修）
> 作者：lzw9560  日期：2026-09-01
> 级别：large（碰外部数据源 Sina；3 源文件 + circuit_breaker.py + health + 测试 + conftest fixture）
> 关联：S133 §7 work-list（新浪源熔断器，单列待办，属底座第 1/5 层·缓存治理/真实裂缝）/ S008（sina/sina_financial 源）/ S108（fetch_merged_periods 三表 merge）/ S126（前端渲染诚实 data_status）/ S114（health._check_circuit_breaker eastmoney 硬编码）

## 1. 问题 / 目标

Sina 数据源有 2 个裸调 urllib 的入口（K线 + 财报三表），**无熔断**。真实 outage 时每次 `urlopen(timeout=30)` 要等满 30s 超时——三表路径 `fetch_merged_periods` 每只股调 3 次 `fetch_raw`，Sina 宕时单只股最多浪费 3×30s=90s，批量回填/train 时灾难性。

S133 §7 把"新浪源熔断器"单列为 work-list（属底座第 1/5 层·缓存治理/真实裂缝）。本 spec 落地：镜像现有 `circuit_breaker.get_breaker()` + `_ths_get` 范式，给 Sina 两入口加独立熔断器，OPEN 后 fast-fail 省超时 + health 可见 + 诚实标注（不臆造"有数据"）。

**不在本 spec**：`_sina_fund_flow_fallback`（eastmoney.py:530，第 3 个 Sina 入口）——已有 bare `except: return []` 保护 + 诚实降级到 `data_status='missing'`（risk_models.py:761），breaker 边际价值最低，留 follow-up（§7）。

## 2. 背景

### 现有熔断范式（`backend/circuit_breaker.py` + `backend/data/transport.py`）

- `CircuitBreaker` + `CircuitBreakerConfig`（默认 `failure_threshold=5` / `recovery_timeout=60s` / `half_open_max_calls=3` / `success_threshold=2`）
- 状态机 `CLOSED→OPEN→HALF_OPEN→CLOSED`；`get_breaker(name)` 单例注册表（first-write-wins config，`circuit_breaker.py:119`）
- `allow_request()`（有副作用，OPEN 满 60s 转 HALF_OPEN）/ `peek_state()`（无副作用，health 用）/ `record_success()` / `record_failure()`
- **无内部锁**——状态突变无锁；现有 eastmoney/ths 接受此风险。**注意**：eastmoney/ths 有 rate-limit 锁（`_em_last_call_lock`/`_ths_lock`）串行化 HTTP 调用，**Sina 无任何锁**（§5.9 / R-fail4）。
- **失败检测：只认 exception**——`record_success()` 在 `urlopen`/`.get()` 返回瞬间调用，body/status 都没看（`transport.py:85-87,90-94`；`eastmoney.py:257-259`）。200+空 body 算 success。
- `_breakers` 是模块级私有 dict（`circuit_breaker.py:116`），无公开枚举 API——R8 加 `list_breakers()`。

### em_get 范式（`transport.py:66-107`）与 `_ths_get` 范式（`eastmoney.py:239-262`）

`_ths_get` 是非 eastmoney 域熔断的**最贴近模板**：

```python
def _ths_get(url, params=None, headers=None, timeout=10):
    breaker = get_breaker("ths")
    if not breaker.allow_request():
        raise RuntimeError(f"[CircuitBreaker:ths] 同花顺数据源熔断中，快速失败（{url}）")
    with _ths_lock:  # rate-limit only
        ...
    try:
        r = requests.get(url, ...); breaker.record_success(); return r
    except Exception:
        breaker.record_failure(); raise
```

S134 镜像此结构（`allow_request`→raise→try→record），但 **Sina 不加 rate-limit 锁**（Sina urllib 源 `sina.py:2` 实测**不封 IP**，无限流需求；breaker 仅为 outage fast-fail，非防 IP 封，见 §7）。transport 从 requests 换 urllib，breaker name 换 `sina_kline`/`sina_financial`。

### Sina 三入口（map 核实）

| # | 函数 | file:line | host | transport | 失败模式 | 现有保护 |
|---|---|---|---|---|---|---|
| 1 | `sina._fetch_json` | `sina.py:28-41` | `money.finance.sina.com.cn` | urllib, 30s | raise on net error；`[]` 仅 empty-200 | 无 |
| 2 | `sina_financial._fetch_json` | `sina_financial.py:33-47` | `quotes.sina.cn` | urllib, 30s | raise on net error；`[]` 仅 empty-200（`_parse:56`） | 无 |
| 3 | `eastmoney._sina_fund_flow_fallback` | `eastmoney.py:530-575` | `vip.stock.finance.sina.com.cn` | requests, 10s | silent `[]`（bare except:555） | 已有 `except` + `source='sina_fallback'` provenance |

**关键纠正前提**：Sina #1/#2 **网络错误会 raise**（不是静默 `[]`），只有 empty-200 才返 `[]`。所以 exception-only breaker 能抓住真实 outage（省 30s 超时）——核心 value 落地。empty-200（Sina soft-block）是未实测的推测模式，留 follow-up（§5.4，YAGNI）。

### `fetch_merged_periods` per-table 容错（load-bearing，已核实 `sina_financial.py:93-104`）

```python
try: lrb = fetch_raw(code, "lrb", num)
except Exception: lrb = []
try: fzb = fetch_raw(code, "fzb", num)
except Exception: fzb = []
try: llb = fetch_raw(code, "llb", num)
except Exception: llb = []
if not (lrb or fzb or llb): return []
```

**breaker raise 在 `fetch_raw` 内 → `fetch_merged_periods` 吞成 `[]` → 不冒泡**。故 raise-on-OPEN 不破 anomaly endpoint（`routers/value_funnel.py:120` 调 `fetch_merged_periods` 非 `fetch_raw`，外层 `except→500` 只在 `detect_anomalies` raise 时触发）。

## 3. 需求清单

- [ ] **R1**：`sina_financial.fetch_raw`（`sina_financial.py:74`）顶加 `get_breaker("sina_financial", CircuitBreakerConfig(failure_threshold=3))` 熔断（threshold=3 理由见 §5.8），镜像 `_ths_get`：`allow_request()`→False 则 `raise RuntimeError("[CircuitBreaker:sina_financial] ...")`；`try: _fetch_json...; record_success; return _parse`；`except Exception: record_failure; raise`。
- [ ] **R2**：`sina.fetch_raw`（`sina.py:74`）顶加 `get_breaker("sina_kline")`（默认 config，理由见 §5.8）同 R1 范式。
- [ ] **R3**：anomaly endpoint（`routers/value_funnel.py:111-124`）返体加 `data_status` 字段：`period_count>=2`→`"ok"`；`==0` 时 peek `get_breaker("sina_financial").peek_state()`，OPEN→`"sina_breaker_open"`，否则 `"missing"`。不删现有 `{data, period_count}` 字段（加，不破契约）。
- [ ] **R4**：`health._check_circuit_breaker`（`routers/health.py:40-55`）从硬编码 `get_breaker("eastmoney")` 改为遍历所有已注册 breaker（经 R8 `list_breakers()`）；**`detail` 字段保持 string**（worst-state，backward-compat），新增 `breakers` dict 字段报 per-breaker `{state, failure_count}`；fresh OPEN 任一 → `ok=False`。**`backfill_history.breaker_state()`（`:107-113`）不改**——保持返 str，因其同文件调用方 `:231-232` `if state=="open"` 依赖 str 比较（改 dict 会让 `dict=="open"` 恒 False，静默关 65s 恢复等）。
- [ ] **R5**：`backend/tests/conftest.py` 加 `sina_breaker` save/restore fixture（镜像 `eastmoney_breaker` at `test_circuit_breaker.py:97-115`），防 breaker 状态跨测试污染。
- [ ] **R6**：全量 gate 绿：`cd backend && .venv/bin/python -m pytest -m "not live" --deselect backend/tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails --deselect backend/tests/test_s032*.py::test_s032_refresh_loop`（deselect 见 memory flaky 项）。
- [ ] **R7**：exception-only failure detection——empty-200（`_fetch_json` 正常返空 body）→ `record_success`（eastmoney-consistent），**不**在 `fetch_raw` 内把 empty 当 failure。empty-200-as-failure 留 follow-up（§5.4）。
- [ ] **R8**：`circuit_breaker.py` 加 `list_breakers() -> dict[str, CircuitBreaker]` 公开 API（返回 `_breakers` 的浅拷贝或 view），供 health 遍历——避免 health 读私有 `_breakers`。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/circuit_breaker.py` | 加 `list_breakers() -> dict[str, CircuitBreaker]` 公开 API（R8，返 `_breakers` view/浅拷贝） |
| `backend/data/sources/sina_financial.py` | `fetch_raw`（:74-78）顶加 sina_financial breaker 包裹，config `failure_threshold=3`（R1）；`_fetch_json`/`_parse`/`fetch_merged_periods` 不动 |
| `backend/data/sources/sina.py` | `fetch_raw`（:74-80）顶加 sina_kline breaker 包裹，默认 config（R2）；`_fetch_json`/`_parse` 不动 |
| `backend/routers/value_funnel.py` | `get_anomaly`（:111-124）返体加 `data_status`（R3） |
| `backend/routers/health.py` | `_check_circuit_breaker`（:40-55）遍历 `list_breakers()`；`detail` 留 string + 新增 `breakers` dict（R4） |
| `backend/tests/conftest.py` | 加 `sina_breaker` save/restore fixture（R5） |
| `backend/tests/test_s134_sina_breaker.py` | 新增 7 测（§8） |
| `backend/tests/test_s008_sources_sina.py` | 不改（monkeypatch `_fetch_json`→breaker CLOSED 放行；R5 fixture 防污染） |
| `backend/tests/test_s008_sina_financials.py` | 不改（同上） |
| `backend/tests/test_circuit_breaker.py` | **不改**——`:127/:139` 断言 `detail==string` 保持绿（S134 留 `detail` 为 worst-state string backward-compat，新加 `breakers` dict；test 仅设 eastmoney state，worst=其 state → 字串匹配） |
| `backend/backfill_history.py` | **不改**——`breaker_state()` 留 str（eastmoney），`if state=="open"` 调用方依赖 str（R4 决定不动 backfill） |

## 5. 设计方案

### 5.1 独立 breaker（非共享 `sina`）——2 个

`get_breaker("sina_financial")` + `get_breaker("sina_kline")`，不共享 `sina`。理由：两入口在**不同 host**（`quotes.sina.cn` vs `money.finance.sina.com.cn`），独立失败（host-specific 宕 vs IP 级封）；且失败 profile 不同（三表慢 12-25s、3×/code、**无 Sina 备份**；K线 30s 但 kline_resolver 有 mootdx/akshare 回退）。共享 breaker 会导致 K线超时把三表路径也毒开（误阻没有备份的三表 fetch）。`get_breaker(name)` 注册表已支持任意 name。

**备选（不选）**：单 `sina` breaker——host 独立性被忽略，K线抖动误阻三表。**备选（不选）**：3 breaker 含 `sina_fundflow`——fundflow 已 bare-except 保护 + 诚实降级 `missing`（map 核实 `risk_models.py:761`），breaker 边际仅省 10s 超时 + health 可见，YAGNI 留 follow-up。

### 5.2 breaker 置 `fetch_raw` 顶（非 `_fetch_json`）

`fetch_raw` 是 `_fetch_json`（urllib 请求层，测试 monkeypatch 点）的上层。breaker 置 `fetch_raw` 顶：
- OPEN 短路在调 `_fetch_json` **之前**（`allow_request()→False` 直接 raise，不触网）
- CLOSED 时正常调 `_fetch_json`（测试 monkeypatch `_fetch_json` 仍 work——breaker CLOSED 放行，monkeypatch 的 `_fetch_json` 被调）
- `_fetch_json` raise → `record_failure` + re-raise（`fetch_merged_periods` 吞成 `[]`）
- `_fetch_json` 返正常 → `record_success` + 返 `_parse` 结果

**备选（不选）**：breaker 置 `_fetch_json` 内——测试 monkeypatch `_fetch_json` 会**整个绕过 breaker**，无法测 OPEN 路径。置 `fetch_raw` 顶才能既保 monkeypatch 又能测 OPEN。

### 5.3 raise-on-OPEN（非 return-[]）

镜像 eastmoney/ths 范式：OPEN → `raise RuntimeError`。安全性已核实：`fetch_merged_periods`（sina_financial.py:93-104）per-table `try/except` 吞 raise 成 `[]`；`kline_resolver`（kline_resolver.py:142）`except Exception` 吞 raise 成回退下一源。故 raise 不破任何 caller。

**备选（不选）**：return `[]` on OPEN——breaker-OPEN 信号被 early-conflate 成"无数据"，且偏离 eastmoney/ths 一致性。raise 让 breaker-OPEN 作为**独立信号**（RuntimeError），需要区分的 caller（anomaly endpoint）用 `peek_state` 显式查（R3），不靠 exception 巧合。

### 5.4 exception-only failure detection（empty-200→success）

`record_success` 在 `_fetch_json` 正常返回（非 raise）时调用，**不**检查 body 是否空。理由：
1. eastmoney/ths 一致（`transport.py:101-103` 只认 exception）
2. 低风险——真实 outage（URLError/timeout/HTTPError）会 raise，breaker 能抓住，核心 fast-fail value 落地
3. empty-200-as-failure 会误判合法空（新股无财报、非交易日无 K线）为 failure，连续 N 次误 trip

**empty-200-as-failure（Sina soft-block 检测）留 follow-up**：Sina ban 模式（200+空 vs 403/timeout）未实测，无数据就加 = 投机（YAGNI）。需先采集 divergence 数据证明 soft-block 是真实模式。**注意**：若 follow-up 落地 empty-200-as-failure，R3 的 `data_status='sina_breaker_open'` 区分对 soft-block **失效**（soft-block→CLOSED→`missing`）——follow-up 须同时复查 R3 路径（breaker 修后自动传播：soft-block→OPEN→`sina_breaker_open`）。

### 5.5 anomaly endpoint data_status（R3 诚实缝）

`routers/value_funnel.py:122` 现返 `{data, period_count}`，breaker-OPEN 与"真无财报"无法区分（honesty gap）。加 `data_status`：

```python
from circuit_breaker import get_breaker
periods = fetch_merged_periods(code)
assessment = detect_anomalies(periods)
if len(periods) >= 2:
    status = "ok"
elif get_breaker("sina_financial").peek_state().value == "open":
    status = "sina_breaker_open"
else:
    status = "missing"
return {"data": assessment.model_dump(mode="json"), "period_count": len(periods), "data_status": status}
```

只在 `period_count==0`（歧义点）时 peek，减少 breaker 状态读取。`data_status` 值与 risk_models 契约（`ok`/`degraded`/`missing`）共享 `ok`/`missing`；新增 `sina_breaker_open` 是**仅 anomaly endpoint 的响应字段**，不进 risk_models `_merge_data_status`（两代码路径不相交：risk_models 不调 fetch_merged_periods/get_anomaly，value_funnel 不调 _merge_data_status；map 核实 grep 0 ref）。前端 S126 渲染诚实层可据此显示"Sina 暂不可用"而非"无异常"。

### 5.6 health 扩展（R4）——detail 留 string + 新增 breakers dict

`health._check_circuit_breaker`（:40-55）现硬编码 `get_breaker("eastmoney")`，sina breaker 不可见。改遍历 `list_breakers()`（R8）。**关键：`detail` 字段保持 string（worst-state），不破 `test_circuit_breaker.py:127/139` 的 `assert result["detail"]=="circuit_breaker_half_open"/"circuit_breaker_open"` 字串断言**——per-breaker 详情走**新** `breakers` dict 字段：

```python
from circuit_breaker import list_breakers
breakers = list_breakers()
details = {name: {"state": br.peek_state().value, "failure_count": br.failure_count}
           for name, br in breakers.items()}
any_open = any(d["state"] == "open" for d in details.values())
_sev = {"open": 2, "half_open": 1, "closed": 0}
worst = max((d["state"] for d in details.values()), key=lambda s: _sev.get(s, 0), default="closed")
return {"ok": not any_open, "detail": f"circuit_breaker_{worst}", "breakers": details}
```

**为何 `detail` 留 string**：`test_circuit_breaker.py:127/139` 断言 `detail==string`，test 只设 eastmoney state（sina 未注册），`worst`=eastmoney state → `"circuit_breaker_half_open"`/`"circuit_breaker_open"` 字串匹配，断言保持绿。若 `detail` 改 dict（v1 设计），`dict==string` 恒 False → 两测红（review confirmed HIGH A）。新 `breakers` dict 承载 per-breaker 详情，前端/运维可读所有源 state。

**`backfill_history.breaker_state()` 不改**——保持返 str（eastmoney state）。其调用方 `backfill_history.py:231-232` `if state=="open": await asyncio.sleep(65)` 依赖 str 比较；改 dict 会让 `dict=="open"` 恒 False，**静默关 65s 恢复等**（review confirmed HIGH B）。backfill 默认源是 eastmoney（:125），仅需 eastmoney state；sina breaker 经 health `breakers` 字段可见，不进 backfill。

**备选（不选）**：health 仍只报 eastmoney + 单独加 sina 检查——两套逻辑维护成本高，遍历 `list_breakers()` 是正解。

### 5.7 conftest `sina_breaker` fixture（R5 防污染）

mirror `eastmoney_breaker`（`test_circuit_breaker.py:97-115`）：save `(state, failure_count, last_failure_time, half_open_calls, success_count)` → yield → restore。**显式引用**（非 autouse）——因 test_s134 的 breaker-OPEN/failure 测用 `_FakeBreaker`（monkeypatch `get_breaker` 返 fake，绕过全局 `_breakers`，review refuted 证明不污染全局）；仅直接操 `get_breaker("sina_*")` 全局单例的测（如 health traversal A7）显式引 fixture。`backend/tests/` 是扁平结构（无 sina 子目录），autouse 限目录不可行；`_FakeBreaker` 已是主防污染机制，fixture 补全局单例测。

### 5.8 sina_financial threshold=3（sina_kline 默认 5）——review confirmed E

sina_financial 用 `CircuitBreakerConfig(failure_threshold=3)`（**非**默认 5）。理由：三表路径 3× `fetch_raw`/code、每 30s 超时、**无 Sina 备份**（§5.1）。

- 默认 threshold=5：持续 outage 下 stock1 的 3 表（90s）+ stock2 第 2 表（30s）= **150s** 才 trip，stock3+ 才 fast-fail
- threshold=3：stock1 的 3 表（90s）后即 trip，stock2+ fast-fail

§1 称"90s/股 灾难性"，threshold=3 让 fast-fail 在 **1 股内**触发（90s 而非 1.5 股 150s）。3 是"3 表/股"的自然单位——stock1 三表全失败（3 failures）= 1 股完整 outage 信号，trip 合理；间歇性单表失败（record_success 重置 count）不会误 trip。

sina_kline 留默认 5——kline_resolver 有 mootdx/akshare 回退，超时非灾难（回退即可），默认足够；降 threshold 反易误 trip（单次 sina 抖动）误阻 kline。

两 config 经 `get_breaker(name, config)` first-write-wins 注入（§2）——确保首次 `get_breaker("sina_financial", CircuitBreakerConfig(failure_threshold=3))` 在 `fetch_raw` 顶部，后续调用 `get_breaker("sina_financial")` 返同实例。

### 5.9 无锁并发（review confirmed C）——诚实接受

`CircuitBreaker` 无内部锁（§2）。**Sina 不像 eastmoney/ths 有 rate-limit 锁串行化**——`get_anomaly`（`routers/value_funnel.py:111`）是 **sync def**，FastAPI 跑在 threadpool（默认 40 线程），并发请求 → 并发 `sina_financial` breaker 状态突变。后果：
- `failure_count` 自增可能丢失（read-modify-write race）→ 可能需 >3 次才 trip（而非精确 3）
- HALF_OPEN `half_open_calls` race → 可能 >`half_open_max_calls` probe

**接受**——后果轻微（稍延迟 trip / 稍多 probe，非正确性破坏；eastmoney/ths 同样无锁且生产稳定）。**若并发问题实测出现**，加 `threading.Lock` 包 `allow_request`/`record_*`（follow-up，非本 spec——保持与 eastmoney/ths 一致性）。

## 6. 验收标准

- [ ] A1：`sina_financial` breaker OPEN（mock `allow_request→False`）→ `fetch_merged_periods("600519")` 返 `[]`（raise 被 per-table catch 吞），不抛冒泡。
- [ ] A2：`sina_kline` breaker OPEN → `sina.fetch_raw("600519")` `raise RuntimeError`，`kline_resolver.fetch_kline` catch → 回退 mootdx。
- [ ] A3：`_fetch_json` raise（mock `urlopen` 抛 URLError）→ `fetch_raw` `record_failure` + re-raise；`_FakeBreaker.failures==1`。
- [ ] A4a：`sina._fetch_json`（kline）返 `[]`（empty-200，`list[dict]` 合法空）→ `record_success`；`_FakeBreaker.successes==1, failures==0`。
- [ ] A4b：`sina_financial._fetch_json` 返 `{"result":{"data":{}}}`（empty-200，`dict` 合法空——`_fetch_json` 返 dict 非 list，bare `[]` 会触发 `AttributeError` 走 failure 路径，review confirmed G）→ `record_success`；`_FakeBreaker.successes==1, failures==0`。
- [ ] A5：OPEN → `last_failure_time=time.time()-61` → `peek_state()==HALF_OPEN` → `allow_request()` True → 2 次 `record_success` → `CLOSED`（mirror `test_circuit_breaker.py:43-51`）。
- [ ] A6：anomaly endpoint breaker OPEN → 返 `{"data":..., "period_count":0, "data_status":"sina_breaker_open"}`；CLOSED+空 → `"missing"`；有 periods → `"ok"`。
- [ ] A7：`GET /api/health` 返 `circuit_breaker` 含 `detail`（string，worst-state）+ `breakers` dict 含 `eastmoney`+`sina_financial`+`sina_kline` 三项 `{state, failure_count}`；任一 fresh OPEN → `ok=False` + `detail=="circuit_breaker_open"`。
- [ ] A8：全量 gate 绿（R6 deselect 项外 0 failed）；现有 `test_s008_sources_sina` / `test_s008_sina_financials` / `test_s108_sina_financials` / `test_circuit_breaker:127,139` 全绿。
- [ ] A9（合规）：`sina_financial`/`sina_kline` 走 urllib，**非** em_get。Sina 不封 IP（`sina.py:2`），breaker 是 outage fast-fail + 诚实标注（非防 IP 封）。无私有数据，无臆造（empty→`missing`/`sina_breaker_open`）。

## 7. 合规与工程底线自查（逐条确认）

- [x] **研判/推荐/买卖时机**：本 spec 纯工程（数据源熔断基础设施），无研判输出。N/A。
- [x] **判断可复现**：breaker 状态机可复现（同输入同状态转移）；无财务计算（三表数据经 breaker 透传，不改值），无需 `financial_rigor.py` 验算。empty→`missing`/`sina_breaker_open` 是诚实标注非臆造。
- [x] **涨停四池/连板股榜**：N/A（本 spec 不碰榜单呈现）。
- [x] **用户私有数据隔离**：Sina 是公开市场数据源，无私有数据进 git/上传。breaker 状态在内存 `_breakers` 注册表，不落盘私有目录。
- [x] **东财端点走 `em_get`**：本 spec 不加东财端点（Sina 非 东财）。§1.2 防封底线（限流/熔断/代理探测 防 IP 封）适用**东财**，S134 不碰东财。S134 加的是**熔断+fast-fail**（**非**限流——Sina urllib 源 `sina.py:2` 实测**不封 IP**，无限流需求；breaker 仅 outage 快速失败省超时 + 诚实标注，非防 IP 封）。**不**声称"镜像 em_get 防封范式"——em_get 的限流是防 IP 封手段，Sina 无此需求，两者目的不同。

**工程底线备注**：§1.2 三条底线（不臆造/私有数据隔离/防封）全过。breaker OPEN 不臆造数据（返 `[]`+`data_status='sina_breaker_open'`/`missing`）；私有数据不涉；防封底线针对东财 em_get（S134 不碰），Sina 不封 IP 故 breaker 非 IP 防封手段而是 outage 容错。

## 8. 测试计划

新增 `backend/tests/test_s134_sina_breaker.py`，mirror `test_availability.py:143-163`（em_get breaker-OPEN 消费侧）+ `test_s085_bids_ths.py:171-219`（`_FakeBreaker` 传输侧）：

1. `test_sina_financial_breaker_open_returns_empty`：mock `allow_request→False` → `fetch_merged_periods` 返 `[]`（A1）
2. `test_sina_kline_breaker_open_raises_and_resolver_falls_through`：mock → `fetch_raw` raise → `kline_resolver` 回退（A2）
3. `test_sina_breaker_records_failure_on_exception`：`_fetch_json` raise → `record_failure`+re-raise（A3）
4a. `test_sina_kline_breaker_records_success_on_empty_list`：`sina._fetch_json`（kline，返 `list[dict]`）返 `[]` → `record_success`（A4a）
4b. `test_sina_financial_breaker_records_success_on_empty_dict`：`sina_financial._fetch_json`（返 `dict`）返 `{"result":{"data":{}}}`（`_parse` 转成 `[]`）→ `record_success`（A4b——不能用 bare `[]`，否则 `d.get(...)` 在 list 上 `AttributeError` 走 failure 路径，review confirmed G）
5. `test_sina_breaker_open_half_open_recovery`：OPEN→61s→HALF_OPEN→2 success→CLOSED（A5，mirror `test_circuit_breaker.py:43-51`）
6. `test_anomaly_endpoint_breaker_open_data_status`：breaker OPEN → endpoint `data_status='sina_breaker_open'`（A6）
7. `test_health_reports_all_breakers`：注册 eastmoney+sina_financial+sina_kline（经 `get_breaker(name)` 注册）→ health 返 `detail`（string）+ `breakers` dict 三项（A7）

`conftest.py` 加 `sina_breaker` fixture（R5）。现有 sina 测试（`test_s008_*`/`test_s108_*`）不改——R5 fixture + `_FakeBreaker` 保其 breaker 状态不被污染。`test_circuit_breaker.py:127/139` 不改——`detail` 留 string backward-compat。

**离线**：所有 Sina 测试 monkeypatch `_fetch_json`/`fetch_raw`，不联网（memory 核实：非 newsradar/s032 flaky 项）。跑 `pytest -m "not live" --deselect <newsradar> --deselect <s032>`。

## 9. 风险与回滚

- **R-fail1（test 污染）**：breaker 在 `fetch_raw` 内，monkeypatch `_fetch_json` raise 的测试会 `record_failure` 污染全局 `get_breaker("sina_*")`。**缓解**：R5 `sina_breaker` save/restore fixture（显式引用在操全局单例的测，如 A7）；`_FakeBreaker`（monkeypatch `get_breaker`）是主防污染（绕过全局 `_breakers`，review refuted 证明 test_s008/test_s108 不受影响）。
- **R-fail2（health 读私有 `_breakers`）→ 已由 R8 解决**：`list_breakers()` 公开 API 替代私有 dict 读取，`circuit_breaker.py` 列入 §4。
- **R-fail3（empty-200 漏检 soft-block）**：exception-only 抓不住 Sina 200+空 soft-block。**接受**——soft-block 模式未实测，YAGNI 留 follow-up；soft-block 是快速返空（不浪费 30s 超时），breaker fast-fail value 主要在 timeout/net-error。**若 follow-up 落地 empty-200-as-failure，须复查 R3**（§5.4 已注）。
- **R-fail4（breaker 无锁并发）**：`failure_count` 自增/HALF_OPEN probe 可能 race。**接受**——Sina 无 rate-limit 锁（不比 eastmoney/ths，§5.9 已诚实标注），sync `get_anomaly` 走 threadpool 并发真实，但后果轻微（稍延迟 trip / 稍多 probe，非正确性破坏）。加 `threading.Lock` 留 follow-up（若实测并发问题），保持与 eastmoney/ths 一致性。
- **回滚**：circuit_breaker.py 加 1 函数 + 2 源文件加 breaker 包裹 + 1 endpoint 加字段 + health 遍历 + conftest fixture + 新测——纯加法，无破坏性改（`detail` 留 string，`breaker_state` 不动，旧契约全共存）。回滚 = revert commit，无数据迁移、无 schema 改。

## 10. 冲突审查表（large spec，AGENTS.md §44 格式）

| 旧 spec R-item | 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S133 §7 work-list | "新浪源熔断器" 单条 work-list | S134 拆 2 breaker（sina_financial threshold=3 + sina_kline 默认），fundflow 留 follow-up | 替换 | S133 §7 该 work-list 项标注"→S134 实现"；S134 §1 引用 S133 §7 |
| S108 `fetch_merged_periods` per-table try/except（`sina_financial.py:93-104`） | 单表失败→`[]`，merge 用余表 | 不变——breaker raise 被此层吞成 `[]`，契约保持 | 共存 | 无迁移；A1 验收锁此行为 |
| S008 `fetch_raw` 契约（`_fetch_json` monkeypatch 点） | `fetch_raw` 调 `_fetch_json`→`_parse`，raise 传播 | `fetch_raw` 顶加 breaker 包裹，`_fetch_json`/`_parse` 不动 | 共存 | 无迁移；monkeypatch `_fetch_json` 仍 work（breaker CLOSED 放行） |
| S126 `data_status` 渲染诚实（risk_models `ok`/`degraded`/`missing`） | 三态 | 新增 `sina_breaker_open`（仅 anomaly endpoint 响应字段，**不进** risk_models `_merge_data_status`——两路径不相交） | 共存 | 无迁移；新值不冲突现有三态；前端 S126 渲染层按需扩展（本 spec 不改前端） |
| S114 health `_check_circuit_breaker` eastmoney 硬编码（`health.py:40-55`） | `detail`=string，只报 eastmoney | `detail` 留 string（worst-state backward-compat）+ 新增 `breakers` dict 遍历 `list_breakers()` | 共存（加字段非替换） | `test_circuit_breaker.py:127/139` 断言 `detail==string` **保持绿**（worst=仅设的 eastmoney state）；A7 验收新 `breakers` dict |
| S133 §7 fundflow work-list | 隐含"新浪源熔断器"含 fundflow | fundflow 明确 out-of-scope（§1），留 follow-up | 共存 | fundflow 不动，§7 标注"已 bare-except 保护，边际低，follow-up" |
| `backfill_history.breaker_state()` str 契约（`:107-113`，调用方 `:232`） | 返 str，`if state=="open"` | **不改**——保持 str（review confirmed B：改 dict 静默关 65s 恢复等） | 共存 | 无迁移；sina breaker 经 health `breakers` 字段可见，不进 backfill |

**无直接被废弃 R-item**——S134 是加法（新 breaker + 新函数 + 新字段 + 新 fixture），旧契约全共存（`detail` 留 string、`breaker_state` 留 str、`fetch_merged_periods` catch 不变、`_fetch_json` monkeypatch 不变）。冲突审查表实现时为权威参考。
