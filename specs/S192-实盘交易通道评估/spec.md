# Spec: S192 — 实盘交易通道评估（QMT/miniQMT + 替代）

> 状态：调研定论（不开户不实现，策略验证有 edge 后再启动）
> 作者：Claude  日期：2026-09-12
> 关联：[[../S189-做T框架/spec.md]]（T+0 无 validated edge）、[[buy-what-when-buy-when-sell-three-questions]]、`paper-trading-self-consistent-frame-2026-09-09`

## 1. 问题 / 目标

Vibe-Research 已有模拟盘自洽框架（S173/S175 trade journal + arms 信号 + floor），但**无实盘下单通道**。评估 A 股实盘通道（QMT/miniQMT 为主）的门槛、对接 macOS 后端的可行性 + Plan B，定"何时开户、走哪条路"。

**定论**：当前阶段**不开户**——breakout net -1.14%（S188）、T+0 无 validated edge（S189 grill verdict）、选股层 §44 证否（S168）。策略没 edge 就上实盘只亏。先免费回测验证，有 edge 再启动。

## 2. 调研定论（2026-09-12 现查，4 agent workflow）

### 2.1 QMT/miniQMT 注册 = 券商开户 + 资产门槛（非直接注册）

迅投社区 84 家券商三档（2025 版表，2026 仍更新）：
- **低门槛 10 万级**（14 家，推荐）：国金、国信（iquant）、华鑫、大同、德邦、第一创业 等
- 中门槛 30-50 万（36 家）：中信、国泰海通、申万、广发 等
- 高门槛 100 万+（34 家）：东财证券、招商、银河、中信建投、华泰 等

**miniQMT 门槛实测**（搜狐 2026-05）：10 万 20 日日均资产（股票/现金/基金都算，不冻结）。非 50 万硬墙。

### 2.2 macOS 对接坎（关键）

**QMT/miniQMT 客户端 + xtquant 库均 Windows-only**（PyPI classifiers 明标 `Microsoft::Windows`，macOS import 失败；官方+社区多源确认无 Mac 版）。

三条 macOS 对接路径：
| 路径 | 机制 | 优 | 缺 |
|---|---|---|---|
| A 虚拟机 | Parallels/UTM 装 Windows + miniQMT | 一机搞定 | VM 吃内存 8G+，客户端要常开 |
| B 云 Windows ECS | 阿里/腾讯云 Windows 跑 miniQMT | 7x24 稳定 | 月 50-200 元，云 IP 或被券商风控 |
| **C xqshare 远程代理**（推荐） | Windows 端 `python -m xqshare.server` + miniQMT 开着，macOS `pip install xqshare` 透明调 xtquant | API 完全一致（`xt.xtdata.get_full_tick`），HMAC+SSL+断线重连 | 需一台 Windows 机器（旧笔记本/迷你主机/云） |

xqshare：github.com/jasonhu/xqshare（GPLv3，2026-04 活跃），RPyC 协议端口 18812。

### 2.3 替代方案（Plan B，门槛/平台对比）

| 平台 | 门槛 | 实盘下单 | macOS | 评 |
|---|---|---|---|---|
| **miniQMT** | 10 万 | ✅ 券商版 | ❌ 需 Windows | **最优实盘通道**（Python SDK 可跨机传信号） |
| PTrade（恒生） | 10-30 万 | ✅ 但策略跑券商云端机房 | ❌ Windows | 不支持外部链接，Vibe 后端不能直接驱动 |
| **同花顺 SuperMind** | 回测免费，实盘"几十万" | ✅ 券商开户 | ✅ 浏览器跨平台 | **策略验证阶段用**（免费回测） |
| 掘金 MyQuant | 免费回测/仿真，专业版 9800/年 | ✅ 券商版 | ❌ Windows | 仿真验证用 |
| 聚宽 JoinQuant | 免费 | ❌ 2026-08 起限制非大陆 IP | ✅ | **不推荐**（IP 限制） |
| 米筐 RiceQuant | 免费 | 弱（官方"将来提供"） | ✅ | 不作实盘 Plan B |
| 东财 EMQuant/Choice | 数据接口付费 12800/年 | ❌ 纯数据 | ✅ 跨平台 | Vibe 已有 akshare，增量有限 |
| easytrader/Trade.dll | 免费 | ✅ 灰色 GUI 自动化 | ❌ Windows | 不推荐（不稳+合规风险） |

### 2.4 xtquant API（miniQMT 程序化接口）

- **xtdata**（行情）：`subscribe_quote` / `subscribe_whole_quote` / `get_full_tick`（五档快照）/ `get_market_data_ex`（历史）；频率 tick(3 秒含五档) / 1m / 5m / 1d
- **xttrader**（下单）：`order_stock`(同步) / `order_stock_async`(异步回调)；撤单 `cancel_order_stock`；查询 `query_stock_asset/positions/orders/trades`
- 回调：继承 `XtQuantTraderCallback`（`on_stock_order` / `on_stock_trade` / `on_order_error` 等）
- 无内置回测框架（对 Vibe 是优点——已有 §44v2/S161 自建回测基建）

## 3. 分两步走（用户确认第一步）

### 第一步（当前）——不开户，免费回测验证策略
- 用 **同花顺 SuperMind** 免费回测（macOS 浏览器可用，跨平台）
- 验证目标：breakout/T+0/事件/趋势 等候选策略在 A 股历史数据上是否有 §44v2 validated edge（非噪声）
- 当前状态：breakout net -1.14%（S188）、T+0 无 validated edge（S189 grill）、选股层 §44 证否（S168）→ **当前无 edge，不应上实盘**

### 第二步（策略验证有 edge 后）——国金开户 + miniQMT + Windows 网关
1. 国金证券开户（10 万门槛最低，支持 QMT+miniQMT+PTrade）
2. 转入 10 万（20 日日均，不冻结）→ 申请 miniQMT 权限
3. 准备一台 Windows 机器（旧笔记本/迷你主机/云 ECS）
4. Windows 端装 miniQMT 客户端 + `pip install xqshare` + `python -m xqshare.server`
5. macOS Vibe-Research `pip install xqshare`，新增 `backend/data/qmt_transport.py`（类比现有 `transport.py` em_get 模式）
6. `chat.TOOLS` 加 QMT 工具项（CLAUDE.md §3，自动同步 MCP）
7. 行情用 xtdata `get_full_tick` 补/替腾讯五档；交易走 xttrader（S173/S175 模拟盘接实盘执行层）

## 4. 受影响文件（第一步无；第二步实现时）

| 文件 | 改动（第二步） |
|---|---|
| `backend/data/qmt_transport.py` | 新增——xqshare 封装（类比 transport.py em_get） |
| `backend/chat.py` TOOLS | 加 QMT 工具项 |
| `backend/.env` | QMT 连接配置（xqshare server 地址 + HMAC token） |
| `backend/strategies/forward_test.py` | 接 xttrader 实盘执行层（t0_mode / 实盘 mode） |

## 5. 验收（第一步）

- [x] A1：QMT 注册定论落 spec + memory（券商门槛 + macOS 对接坎 + Plan B）
- [x] A2：第一步决策（不开户，SuperMind 免费回测先行）记入
- [ ] A3：策略验证有 edge 后启动第二步（未触发）

## 6. 风险与盲点

- **券商风控**：云 Windows ECS 的 IP 可能被券商风控拦截交易——开户时必须问客户经理是否允许云服务器跑 QMT（未核实各券商政策）
- **客户端保活**：miniQMT 客户端需常开登录，部分券商要求每日重新登录/定期验证——断线重连必备（xqshare 有）
- **Level2 千档行情**：需投研版 VIP token 额外付费（未核实价格）
- **延迟**：macOS→Windows 代理→miniQMT→交易所，比直连多 1-2 跳——对打板/OFI 毫秒级有影响，对日内/短线/事件驱动 3 秒 tick 粒度足够
- **合规**：CLAUDE.md §1 弱合规（私人助理）——实盘交易是用户最终决策，系统只给信号/执行通道，用户确认才下单

## 7. 关联

- [[S189-做T框架]]（T+0 verdict，第一步的"无 edge"依据）
- [[S188-breakout多窗口holding-return]]（breakout net -1.14%）
- [[S168-12harness-verdict-selection-no-edge]]（选股层 §44 证否）
- [[paper-trading-self-consistent-frame-2026-09-09]]（模拟盘自洽框架，第二步接实盘的基础）
- 调研 workflow: `wf_b2b74334-ed9`（2/4 agent 成功，券商+流程 2 facet 因 LLM 风控失败）
