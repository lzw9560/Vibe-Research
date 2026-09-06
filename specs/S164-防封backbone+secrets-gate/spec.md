# Spec: S164 — 防封 backbone robust + secrets gate

> 状态：草案（S160 component 4，priority 3，design-agnostic）
> 关联：S160 / grill-foundation-holes-2026-09-06（#10 防封 aspirational / #3 hithink key 泄漏）/ hithink-apikey-泄漏待轮换
> 分级：medium —— issue 层单轮 review

## 0. 问题

grill #10（proxy_pool 未接 transport + 裸 requests 绕 em_get MITM 风险 / 单 eastmoney breaker 粒度粗无持久化，重启忘封禁再轰 / lake consumer-coupled）+ grill #3（hithink key 泄漏未轮换且被 reuse 清单遗漏）。防封 backbone 多 aspirational，secrets gate 缺。

## 1. 目标

建防封 backbone robust（breaker 持久化 + eastmoney breaker 拆 2 组 + 裸 requests lint gate 禁绕 em_get + 保留 em_get 现有系统代理降级）+ secrets gate（hithink key 轮换 + 启动校验 + 泄漏标记）。design-agnostic 不依赖 gap。proxy_pool+Redis 服务 defer optional（单用户工具过设计，免费代理质量有限）。

## 2. 需求清单

- **R1 breaker 持久化**：`circuit_breaker.py` `_breakers: dict` 全内存 → SQLite state + `last_failure_time`，`recovery_timeout` 跨进程计算。治 :8900 重启丢 OPEN 状态（重启即忘封禁再轰）。
- **R2 breaker per-端点拆**：仅拆单 eastmoney breaker 为 2 组——{push2his/push2/fflow}（IP+ut 敏感，同 host family——fflow 用 push2.eastmoney.com 带 `_PUSH2_UT` per `eastmoney.py:148`）一组 / {datacenter}（不需 ut，不同子域）一组。共 2 组。sina_kline/sina_financial 已是独立 breaker 不动（生产现 6 breaker：eastmoney/ths/sina_kline/sina_financial/worldmonitor/hithink）。避免 push2his 封禁连累 datacenter。
- **R3 裸 requests lint gate（非 proxy_pool 服务化）**：grill #10 真 MITM 修复 = CI lint/grep 检查——无代码裸调 `requests.get()` on eastmoney/tencent host，全须走 `em_get`（breaker+rate-limit+proxy fallback 保护路径）。保留 em_get **现有**系统代理降级（`transport.py` `trust_env` + `VR_DATA_PROXY=1`），代理层已存在，不新起进程。**proxy_pool+Redis defer**：降级为 optional/exploratory，仅当真实 IP-ban 问题发生（breaker OPEN 频率超阈值，有证据）时才启用——若启用需 Redis（`127.0.0.1:6379`，`DB_CONN` 占位密码 `'pwdstring'` 须配置）为前置。留 paid 代理口子（Bright Data 等）作可靠层。
- **R4 secrets gate**：启动校验 key 健康度（存在 + 非泄漏标记）+ hithink key 轮换提醒（[[hithink-apikey-泄漏待轮换]] 用户待办：sk-fuyao- 泄漏，revoke+重生成写 .env）+ .env 不进 git 强制。reuse 数据源清单补 hithink（grill #3）。

## 3. 受影响文件

- 改 `backend/circuit_breaker.py`（持久化 SQLite + eastmoney breaker 拆 2 组）。
- 改 `backend/data/transport.py`（保留现有系统代理降级 `trust_env` + `VR_DATA_PROXY=1`，代理层不改）。
- 新建 `backend/secrets_gate.py`（启动校验 + 轮换提醒）。
- 新建 CI lint/grep 检查（裸 `requests.get()` 调 eastmoney/tencent host 的代码禁止合入）。
- `vendor/proxy_pool`：defer optional（仅 IP-ban 真实发生时启用，需 Redis `127.0.0.1:6379` + `DB_CONN` `pwdstring` 配置为前置）。

## 4. 验收标准

- [ ] R1 breaker 持久化（重启不丢 OPEN 状态，跨进程 recovery_timeout）。
- [ ] R2 breaker per-端点（eastmoney 拆 2 组：push2his/push2/fflow 一组 + datacenter 一组；push2his 封禁不连累 datacenter）。
- [ ] R3 裸 requests lint gate（CI grep 检查：无代码裸调 `requests.get()` on eastmoney/tencent host，全走 em_get；em_get 现有系统代理降级保留 `transport.py` `trust_env` + `VR_DATA_PROXY=1`）。
- [ ] R4 secrets gate（启动校验 key + hithink 轮换提醒 + .env 不进 git）。
- [ ] pytest 单测 + 防封 e2e（breaker 持久化跨重启验证）。

## 5. 合规与工程底线自查

- [x] 不臆造：breaker state 机器实算（持久化 + 拆组）。
- [x] 私有数据隔离：secrets 不进 git 不上云（.env gitignore 强制）。
- [x] em_get 防封：裸 requests lint gate（治 grill #10 MITM——禁止绕 em_get 裸调）+ breaker 持久化 + eastmoney 拆 2 组 + 保留现有系统代理降级。
- [x] 不闭门造车：proxy_pool defer optional（免费代理质量有限，单用户工具不必跑服务）；paid 口子留 Bright Data 作可靠层。

## 6. 分级

medium（breaker 持久化 + eastmoney 拆 2 组 + 裸 requests lint gate + secrets gate）。issue 层单轮 review。design-agnostic（任何线路需防封 + secrets 安全）。proxy_pool+Redis defer optional（仅 IP-ban 真实发生时启用）。
