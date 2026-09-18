# Spec: S105 — hithink_src 从 subprocess CLI 改直连 HTTP（复刻 envelope 转译层）

> 状态：已实现(2026-08-30)
> 作者：lzw9560  日期：2026-08-30
> 级别：large（重构数据源调用层，碰外部数据源）
> 分支：`feature/S105-hithink-direct-http`（off develop，squash-merge）
> 关联：S104（hithink_src 已建 subprocess 版）/ grill「坚实数据底座」/ CLI 协议逆向

## 1. 问题 / 目标

S104 的 `hithink_src.py` 用 `subprocess` 调 node CLI，实测 avg **1.09s/次**（vs 腾讯 gtimg 0.01s）。慢的不是远端服务，是 **node subprocess 冷启动**（fork + ESM 模块加载 ~1.0s）。

CLI 协议逆向（直读 `dist/` 源码核实）：
- `GET https://fuyao.aicubes.cn{path}?{query}` + `X-api-key` header
- 远端原始 envelope：`{code:int, message:str, request_id?:str, data:unknown}`（`dist/infrastructure/fuyao/envelope.js`）
- `code === 0` → 成功取 `data`；非 0 → 失败（`businessError`，client.js:154）
- 重试：`RETRYABLE_HTTP_STATUS_CODES={429,502,503,504}` + `RETRYABLE_BUSINESS_CODES={4001,5001,5002,5003}`，maxAttempts=3，指数退避 `min(1000*2^attempt, 8000)+20% 抖动`，Retry-After 优先上限 30s（`dist/infrastructure/fuyao/retry.js`）

**直连实测**：urllib ~0.1s（快 10 倍），数据一致（茅台 PS=9.361984 两方式相同）。直连 envelope 与 CLI 不同（直连有 `code/message`，CLI 输出 `ok`）——CLI 做了转译层。

**目标**：hithink_src.py 改直连 HTTP，**复刻 CLI envelope 转译层**，下游零改动。CLI 不在运行时调用，仅作升级后契约校验源（grill 方案 c）。

## 2. 背景

- S104 已建 hithink_src.py：`_run_cli`（subprocess）+ thscode 映射 + 5 对外函数 + `_normalize_*` + 5min 缓存 + `circuit_breaker("hithink")`。
- API Key：41 字符，存 macOS Keychain（`hithink-finance`/`profile:default`）。CLI 读取优先级：explicit > `HITHINK_FINANCE_API_KEY` env > keyring。
- 下游契约：`full_valuation`（astock.py）调 `valuation_snapshot` 补 PS/PCF；3 AI 工具（stock_tools.py）；3 端点（routers/market.py）。全依赖 hithink_src 返**项目惯用结构**（裸 code 键），不依赖 CLI envelope 形态。
- **Key 工程化盲点**（实测发现）：macOS keychain 在非交互环境（pytest/服务进程）`security` 命令会弹 GUI 授权框，Python subprocess 读超时 3s。故 env 必须作主路径，keychain 仅本机 fallback。

## 3. 需求清单

- [x] R1 新增 `_http_get(path, query, timeout)` 直连 fuyao，复刻 envelope 转译：`code==0` 取 data，非 0 失败
- [x] R2 复刻有界重试：429/502/503/504 + 业务码 4001/5001/5002/5003，maxAttempts=3，指数退避（1s/2s/4s 上限 8s + 20% 抖动），Retry-After 优先（上限 30s）
- [x] R3 失败返 None（下游惯用空），log 含 CLI 风格 code（FUYAO_/UPSTREAM_HTTP_）——不透传 envelope
- [x] R4 Key 读取 `_resolve_api_key`：env 优先 / fallback macOS keychain（`security`）/ 都失败 `DependencyMissing`
- [x] R5 删 `_run_cli` subprocess，5 对外函数改调 `_http_get`（thscode/normalize/缓存/熔断不变）
- [x] R6 CLI 不在运行时调用，仅留契约校验脚本位（`tools/hithink_parity_check.py` 占位，实现期留待）
- [x] R7 下游零改动（full_valuation / AI 工具 / 端点 不动）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/hithink_src.py` | `_run_cli` → `_http_get`（直连 + 复刻转译/重试/error）+ `_resolve_api_key` + `_retry_delay`；endpoint 表常量（含 `-list` 后缀修正） |
| `backend/tests/test_s104_hithink_source.py` | mock `subprocess.run` → mock `urllib.request.urlopen` + `_resolve_api_key`；envelope 转译/重试/Key 解析用例 |
| `backend/.env`（gitignored） | 加 `HITHINK_FINANCE_API_KEY=`（Key 从 keychain 导出，不进 git） |
| `backend/.env.example` | 加 `HITHINK_FINANCE_API_KEY=` 占位（空值，引导配置） |

## 5. 设计方案

### 5.1 `_http_get` 直连 + 复刻转译（核心，hithink_src.py）

`_resolve_api_key`：env `HITHINK_FINANCE_API_KEY` 优先 → fallback macOS `security find-generic-password` → `DependencyMissing`。

`_http_get(path, query, timeout)`：
1. `get_breaker("hithink").allow_request()` 判熔断，OPEN 快速失败返 None
2. 解析 Key（DependencyMissing 时返 None 不崩）
3. `urllib.request.urlopen` + `X-api-key` header，重试循环 maxAttempts=3：
   - `code==0` → `record_success` + 返 data
   - `code in _RETRYABLE_BIZ` 且未耗尽 → 退避重试
   - HTTPError `code in _RETRYABLE_HTTP` → 退避重试（Retry-After 优先）
   - URLError/Timeout/JSONDecodeError → 退避重试
   - 耗尽/非重试 → `record_failure` + 返 None
4. `_retry_delay`：Retry-After 优先（上限 30s），否则 `min(1000*2^attempt, 8000)/1000 + 20% 抖动`

### 5.2 endpoint 表（逆向 `dist/contracts/remote-capabilities.js`）

- `valuation.snapshot` → `/api/a-share/valuations/snapshot`，query `{thscodes}`
- `special.skyrocket` → `/api/a-share/special-data/skyrocket-list`，query `{period}`（day/hour）
- `special.hot-stock` → `/api/a-share/special-data/hot-stock-list`，query `{period}`
- `special.anomaly-list` → `/api/a-share/special-data/anomaly-analysis-list`，query `{tag_codes?}`
- `special.anomaly-stock` → `/api/a-share/special-data/anomaly-analysis-stock`，query `{thscodes}`

⚠️ endpoint 带 `-list` 后缀（实现期实测 404 后修正，原 spec 推测无后缀错）。

### 5.3 保留不变（S104 接口）

`_to_thscode`/`_strip_thscode`（复用 `tencent.get_prefix`）、`_normalize_rank_items`/`_normalize_anomaly_items`、5min TTL 缓存、`circuit_breaker("hithink")` 全保留。5 对外函数签名/返回结构不变 → 下游零改动。

### 5.4 CLI 契约校验（方案 c）

CLI 不在运行时调用。`hithink-finance update` 后手动跑 parity 测试（直连 vs CLI 各 endpoint 对比 data）防升级埋雷。实现期留占位，未做（YAGNI，CLI 未升级前不需要）。

## 6. 验收标准

- [x] A1 `valuation_snapshot(["600519"])` 直连返 PS=9.361984，延迟 0.29s（≤0.3s）
- [x] A2 `code==0` 成功取 data；`code!=0`（mock）失败返 None 不透传 envelope
- [x] A3 mock 429 连续 → 重试 maxAttempts 次后 None + record_failure；HTTP 500（非重试）直接 None
- [x] A4 业务码 4001（retryable）触发重试；非 retryable 直接失败
- [x] A5 Key：env 优先 / fallback keychain / 都无 DependencyMissing（keychain 非交互超时实测确认 env 主路径必要性）
- [x] A6 下游零改动：`full_valuation("600519")` 仍返 PS/PCF；3 端点 + 3 AI 工具不变（28 单测含 downstream 用例）
- [x] A7 `skyrocket`/`hot_stock` 各 30 条（直连实测 0.09s）；`anomaly_list` 盘后空
- [x] A8 5min 缓存仍生效

## 7. 合规与工程底线自查

- [x] 不臆造：`code!=0`/HTTP 错/超时全返 None，诚实缺失
- [x] 私有数据隔离：API Key 走 env/keychain，`.env` gitignored 不进 git
- [x] em_get 防封：hithink 走自己熔断 `get_breaker("hithink")`，不碰东财 em_get
- [x] §44 口径：纯调用层重构，不出 winrate/r/verdict；PS/PCF 仍唯一源无仲裁
- [x] Key 不硬编码（env/keychain），不写日志/对话

## 8. 测试计划

- **单测** 28 用例全 PASS：envelope 转译 3 + 重试 4 + Key 解析 3 + valuation_snapshot 4 + 特色数据 3 + 下游零改动 2 + thscode 映射 9
- **真实冒烟**（`.env` Key）：valuation 0.29s PS=9.361984；skyrocket 0.09s 30 条
- **全量 gate**：2364 passed, 7 failed（**pre-existing**：`fund_flow_120d` 相关，develop 上同挂，`bc197ca` 资金流降级 commit 引入，与本 spec 无关）

## 9. 风险与回滚

- **风险 1**：CLI 升级 envelope 转译规则变（code 表/schema），直连埋雷。**缓解**：`tools/hithink_parity_check.py` 升级后校验（占位待做）；log 含 CLI 风格 code 便于定位。
- **风险 2**：keychain 非交互环境读不到（GUI 授权）。**缓解**：env 优先（`.env` 设 Key），生产必设 env。
- **风险 3**：直连丢 CLI outputSchema 校验（data 字段裁剪）。**缓解**：`_normalize_*` 已显式取字段，不依赖 schema 剥离。
- **⚠️ Key 暴露风险**：实现期 API Key 曾在对话明文出现（视为已泄漏）。**待办**：用户去 fuyao.aicubes.cn/admin 轮换 Key，新 Key 写 `.env`（不用对话明文）。
- **回滚**：`_http_get` 改回 `_run_cli` 即退回 subprocess（5 对外函数签名不变）。

## 10. 冲突审查表

| 旧 spec R-item | 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S104 R1 `_run_cli subprocess 封装` | subprocess 调 node CLI | 改直连 HTTP `_http_get` | **替换** | 5 对外函数改调 `_http_get`，签名/返回结构不变，下游零改动。thscode/normalize/缓存/熔断保留。 |
| S104 R3 `熔断 get_breaker("hithink")` | subprocess 失败 record_failure | 直连失败 record_failure | 共存 | 熔断器逻辑不变，`_http_get` 复用同一 breaker。 |
| S104 R4 `5min TTL 缓存` | valuation_snapshot 缓存 | 不变 | 共存 | 缓存层在 `_http_get` 之上。 |
| S104 R2 `ok 字段解析` | 解析 CLI envelope `{ok}` | 解析远端 envelope `{code}` | **替换** | 直连拿远端原始 `{code,message,data}`，`code==0` 成功。CLI 转译层（code→ok）在直连里复刻为 `code==0` 判定。 |

## 11. 不在本 spec 范围

- cross_validate 接线（PE/PB 仲裁）—— S105 后回到这个（第 3 层孤儿）
- `tools/hithink_parity_check.py` 完整实现（CLI 升级校验，占位待做）
- 龙虎榜 hithink 集成（维度不同，另立）
- 缓存治理全铺（datacenter/tencent，第 1 层后续切片）
- 资金流 `fund_flow_120d` 测试修复（pre-existing，另立）
