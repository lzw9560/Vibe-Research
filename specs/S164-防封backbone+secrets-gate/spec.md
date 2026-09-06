# Spec: S164 — 防封 backbone robust + secrets gate

> 状态：草案（S160 component 4，priority 3，design-agnostic）
> 关联：S160 / grill-foundation-holes-2026-09-06（#10 防封 aspirational / #3 hithink key 泄漏）/ hithink-apikey-泄漏待轮换
> 分级：medium —— issue 层单轮 review

## 0. 问题

grill #10（proxy_pool 未接 transport + 裸 requests 绕 em_get MITM 风险 / 单 eastmoney breaker 粒度粗无持久化，重启忘封禁再轰 / lake consumer-coupled）+ grill #3（hithink key 泄漏未轮换且被 reuse 清单遗漏）。防封 backbone 多 aspirational，secrets gate 缺。

## 1. 目标

建防封 backbone robust（breaker 持久化 + per-端点拆 + proxy_pool 接 transport 非裸 requests）+ secrets gate（hithink key 轮换 + 启动校验 + 泄漏标记）。design-agnostic 不依赖 gap。

## 2. 需求清单

- **R1 breaker 持久化**：`circuit_breaker.py` `_breakers: dict` 全内存 → SQLite state + `last_failure_time`，`recovery_timeout` 跨进程计算。治 :8900 重启丢 OPEN 状态（重启即忘封禁再轰）。
- **R2 breaker per-端点拆**：push2his/push2（IP 封敏感）一组 / datacenter（不需 ut，不同子域）一组 / fflow 一组 / sina 一组。避免 push2his 封禁连累 datacenter。
- **R3 proxy_pool 接 transport**：`vendor/proxy_pool`（jhao104）作代理源服务跑（schedule + server），em_get 从 `127.0.0.1:5010/get` 取代理 + 失败删 + 重试。**非裸 requests**（MITM 防护）。留 paid 代理口子（Bright Data 等）作可靠层（免费代理质量有限）。
- **R4 secrets gate**：启动校验 key 健康度（存在 + 非泄漏标记）+ hithink key 轮换提醒（[[hithink-apikey-泄漏待轮换]] 用户待办：sk-fuyao- 泄漏，revoke+重生成写 .env）+ .env 不进 git 强制。reuse 数据源清单补 hithink（grill #3）。

## 3. 受影响文件

- 改 `backend/circuit_breaker.py`（持久化 SQLite + per-端点拆细）。
- 改 `backend/data/transport.py`（proxy_pool 接 transport，em_get 取代理）。
- 新建 `backend/secrets_gate.py`（启动校验 + 轮换提醒）。
- `vendor/proxy_pool` 接 em_get（schedule + server 跑，API /get）。

## 4. 验收标准

- [ ] R1 breaker 持久化（重启不丢 OPEN 状态，跨进程 recovery_timeout）。
- [ ] R2 breaker per-端点（4 组，push2his 封禁不连累 datacenter）。
- [ ] R3 proxy_pool 接 transport（em_get 取代理 + 失败删 + 重试，非裸 requests）。
- [ ] R4 secrets gate（启动校验 key + hithink 轮换提醒 + .env 不进 git）。
- [ ] pytest 单测 + 防封 e2e（breaker 持久化跨重启验证）。

## 5. 合规与工程底线自查

- [x] 不臆造：breaker/proxy 实算（state 机器 + 代理轮转）。
- [x] 私有数据隔离：secrets 不进 git 不上云（.env gitignore 强制）。
- [x] em_get 防封：proxy_pool 接 transport 非裸 requests（治 grill #10 MITM）+ breaker 持久化 + per-端点。
- [x] 不闭门造车：proxy_pool 用开源 jhao104 + paid 口子留 Bright Data。

## 6. 分级

medium（breaker 持久化 + 拆细 + proxy 接 transport + secrets gate）。issue 层单轮 review。design-agnostic（任何线路需防封 + secrets 安全）。
