# Spec: S056 — 天气熔断三铁律规则补全（软 gate）

> 状态：已实现（R1/R2/R3 全落地——R2 解桩完成，接 S055 seal_intraday_snapshots 真实封单额判定，撤单比口径不可得仅用封单额阈值显式标注；后端 10 passed；软 gate 只提醒不锁死）
> 作者：Codex（DSA 借鉴 grill 会话）  日期：2026-08-11
> 级别：**medium**（跨层，>50 行；无新外部数据源——复用 sentiment_weather + S055 时序）
> 流程门：develop 直提 + 勤 commit；issue 级 review（.scratch 单轮）；简化验收（后端冒烟 + 关键路由）
> 关联：`routers/sentiment_weather.py`（weather_fuse/pardon 骨架已存在）、S055（撤单熔断依赖封单时序）、S050/S054（W0 行动闭环）、DSA `limitup-trading-workflow-prd.md` §3.7（三铁律原型）

## 1. 问题 / 目标

DSA PRD 的三条熔断铁律（总仓位/撤单/次日强制离场）在 VR 已有骨架：`weather_fuse`（规则读写 + 历史）、`weather_pardon`（豁免 toggle/revoke/结果回填）。但规则内容为空壳，未与天气状态、封单时序、竞价监控联动。本 spec 补全规则内容，按 **Q3 裁决的软 gate 语义**落地：只提醒不锁死。

## 2. 背景

- `get_weather_fuse` / `update_weather_fuse` / `get_weather_fuse_history`：熔断规则 CRUD 已在。
- `get_weather_pardon` / `toggle_weather_pardon` / `revoke_weather_pardon` / `submit_weather_pardon_outcome`：豁免 + 结果回填已在——即 override 落库机制，胜率归因可接 `signal_source=override` 桶。
- 三铁律原型（DSA PRD §3.7）：①暴风雨 → 锁死买入；②排板封单<3000 万或撤单比>20% → 自动撤单；③次日竞价未高开或 5 分钟破均线 → 强制离场。
- VR 适配：不自动下单 → 三条都落成「信号 + 醒目提醒 + pardon 记录」。

## 3. 需求清单

- [ ] R1 铁律一（总仓位熔断）：天气=暴风雨（或 STI 阶段=冰点/退潮，可配）时，盘前简报与候选输出挂红色熔断横幅 + 熔断状态字段（`fuse_state`），候选照常产出（软 gate）；触发/解除写 fuse_history
- [ ] R2 铁律二（撤单熔断提醒）：候选股封单额 < 3000 万（阈值可配）触发撤单提醒；撤单量/封单量比值依赖盘口数据，实施时评估可得性，不可得则仅用封单额阈值并显式标注口径；数据源依赖 S055 `seal_intraday_snapshots`
- [ ] R3 铁律三（次日强制离场信号）：持仓股次日 09:25 竞价未高开（<0%）或开盘 5 分钟站不稳均线（均线口径=前 N 日均价，N 可配）→ 生成强制离场信号，接 W0 盘后/盘前呈现（S054 三问页 + 简报），数据用 `bidding_monitor` / `auction_screener` + 腾讯实时行情
- [ ] R4 pardon 联动：三条铁律的提醒卡片带「豁免」入口（复用 pardon 端点），豁免必填理由，结果回填进胜率归因
- [ ] R5 通知：铁律触发接 `notification/`（开关默认关），与 S055 告警共用去重冷却

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/routers/sentiment_weather.py` | fuse 规则内容 + fuse_state 计算 |
| `backend/routers/workflow.py` | 简报输出 fuse_state + 强制离场信号 |
| `backend/bidding_monitor.py` / `auction_screener.py` | 竞价未高开/破均线判定函数 |
| `frontend/.../PreMarketBriefing.tsx` | 熔断横幅 + 豁免入口 |

## 5. 设计方案

- 软 gate：系统不拒绝生成候选（Q3 裁决），熔断只改变呈现优先级与提醒强度；pardon 机制承担 override 职责，避免"狼来了"后用户直接无视。
- 铁律二完全依赖 S055——S055 未合并前 R2 置为桩（返 `data_status=待S055`），其余先行。
- 备选不选：硬锁买入（Q3 已否决）；独立熔断服务（骨架已在 sentiment_weather，另起炉灶违反复用原则）。

## 6. 验收标准

- [ ] A1 pytest -m "not live" 全过：三条铁律触发条件单测（含缺数据降级）
- [ ] A2 冒烟：构造暴风雨天气（mock STI）简报出现红色横幅 + fuse_history 落库
- [ ] A3 pardon 全流程：豁免 → 理由落库 → revoke → 结果回填
- [ ] A4 缺数据诚实：竞价/封单数据不可得时提醒不触发且显式标注

## 7. 合规与工程底线自查

- [ ] 熔断提醒属风险标注（§1.1），不出现「必须清仓」式指令，文案中性 + 轻量风险提醒
- [ ] 判断可复现：提醒带触发值 + 阈值 + 时点
- [ ] 不新增东财端点（复用 S055/现有），无新限流面
- [ ] 私有数据（持仓/pardon 理由）不进 git

## 8. 测试计划

离线：铁律单测 + pardon 流程测试 + 端点测试。手动：简报熔断横幅走查、豁免交互走查。

## 9. 风险与回滚

- 误触发扰民：冷却去重 + pardon；回滚＝fuse 规则开关置关。
- S055 延期：R2 桩化不阻塞其余。
