# Spec: S172 — 红利低波指数复制臂（A 臂 floor）

> 状态：已实现(2026-09-09)
> 作者：lzw9560  日期：2026-09-09
> 关联：S171-长线价值（长线底仓方向）；多策略工具箱（A 臂 = 红利低波 floor）
>
> 本文件命名为 `spec.md`，放在 `specs/S172-红利低波指数复制臂/` 子目录下。
> 同目录可选附 `plan.md`（技术方案）/ `tasks.md`（任务拆分）/ `验收报告.md`（实现归档）。

## 1. 问题 / 目标

10 万个人投资者，长线底仓稳拿红利低波 9-12% 年化，走最省成本路径。

核心问题不是「能不能选出更好的红利股」——红利低波已有三重定论（学术 / 卖方 / 指数 930955），选股 alpha 空间极窄。真正的问题 是「怎么拿住这个 beta 最便宜」：直接买 ETF 512890 还是自己复制 930955 成分？成本会计师 verdict 已给结论（见 §2）。本 spec 落地 A 臂 floor：买 ETF 512890，分批建仓，长线持有，跟踪 vs published 指数。

一句话：花最少成本拿住红利低波 beta，不自复制、不择时、不主动卖出。

## 2. 背景

### 2.1 红利低波三重定论

- **学术**：低波 + 红利因子在 A 股 / 全球市场长期有 academically 定论，不是「待验信号」。
- **卖方**：主流卖方覆盖，策略成熟。
- **指数 930955**：中证红利低波动指数（H30269.CSI / 930955），官方 published 成分 + 权重，定期调样。

结论：选股层无 edge 空间（不是去选股，是去拿 published beta）。这跟 §44 verdict「选股层无 validated edge」一致——本臂不赌选股，只拿指数。

### 2.2 ETF 512890 vs 自复制成本对比（成本会计师 verdict）

| 路径 | 成本构成 | 年化成本 | 致命点 |
|---|---|---|---|
| **ETF 512890**（华泰柏瑞红利低波 ETF） | 佣金 ~0.05%（券商竞争价）+ 免印花税 + 管理费 0.50%/年**已含净值** | ~0.55%/yr（含管理费）| 无 |
| 自复制 930955 成分 | 50 只成分股 × 佣金（5 元最低 × N 笔）+ 印花税 0.1% 卖出 + 调样再平衡 | ~1.6%/yr（保守估）| **5 元最低佣金是灾难**：小资金买 50 只，每只 2000 元，佣金 5 元 = 0.25% 单边，远超费率 |

成本会计师 verdict：**长线主仓走 ETF 512890**。自复制在 10 万规模下被 5 元最低佣金结构性击穿，且管理费已含净值（你看到的净值是扣费后），透明且省心。自复制只在 ≥500 万且券商给 0 元最低佣金时才有边际，当前规模不适用。

### 2.3 forkable 轮子定位

本臂是「实用选股优先」方向下的 **#5 forkable 轮子**：红利低波是 academically 定论策略，不需要从零验证，fork/wrap 即可。本 spec 实现的是 floor（最简可用底仓路径），不是 B 臂 experimental（smart-beta 优化另 spec）。

### 2.4 不接 accounting

ETF 市场收益即净收益——管理费已含净值，无 stop-loss / take-profit 触发逻辑（长线底仓 hold，不主动卖）。故**不接** `accounting` 模块（无 stop/take 计算需求），与打板 / 短线臂的 accounting 接线解耦。

## 3. 需求清单

- [ ] R1 取 ETF 512890 实时行情（akshare `fund_etf_spot_em`），返回现价 / 涨跌 / 成交额 / IOPV（若可得）
- [ ] R2 取 930955 published 成分 + 权重（akshare `index_stock_cons_weight_csindex('930955')`），仅用于跟踪对比，**非复制持仓**
- [ ] R3 跟踪误差报告：512890 净值收益 vs 930955 指数收益，滚动窗口（近 1 月 / 3 月 / 6 月 / 1 年），跟踪误差 < 1% 为绿灯
- [ ] R4 分批建仓调度：5 批 × 2 万，1 周 1 批；或一次性建仓（用户可切）。记录每批买入价 / 份数 / 日期到 `.vibe-research/`
- [ ] R5 周报：持仓市值 / 成本基 / 浮动盈亏 / 跟踪误差 / 累计收息（若 ETF 分红），周产出
- [ ] R6 无主动卖出逻辑：长线底仓 hold，不挂 stop/take，不出卖出信号
- [ ] R7 不破坏现有功能（现有 pytest -m "not live" 全绿）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/fetch_etf_tracking.py` | **新建**。取 512890 行情 + 930955 published 成分 + 跟踪误差报告 |
| `backend/strategies/index_replication_floor.py` | **新建**。分批建仓调度 + 持有状态 + 周报产出 |
| `backend/vr_paths.py` | **不改**（复用 `data_dir()` 写持仓 / 报告到 `.vibe-research/`）|
| `backend/accounting/*` | **不改**（ETF 无 stop/take，市场收益即净收益，不接 accounting）|
| `backend/scheduled_tasks.py` | **可选**（后续 plan 决定是否挂周报 cron；本 spec 只建工具，不强制接线）|

## 5. 设计方案

### 5.1 数据源

| 数据 | akshare 函数 | 说明 |
|---|---|---|
| ETF 512890 实时行情 | `ak.fund_etf_spot_em()` | 东财源，返回全市场 ETF spot，筛 512890 |
| 930955 成分 + 权重 | `ak.index_stock_cons_weight_csindex('930955')` | 中证指数公司 published，仅跟踪对比 |
| 930955 指数历史 | `ak.index_zh_a_hist('930955', ...)` 或 csindex 直取 | 算指数收益做跟踪误差 |

**防封说明**：akshare 的 `fund_etf_spot_em` 走东财 datacenter（非 push2/push2his），**不需要 `em_get` 限流**——datacenter 端点不触发 ut token / IP 封禁（见 memory `eastmoney-push2-ut-token`：push2/push2his 才需 ut，datacenter 不需）。但仍遵循 akshare 调用间 sleep ≥ 2s 的惯例（低量一次性调用，非高频）。

### 5.2 模块拆分

```
backend/tools/fetch_etf_tracking.py
  ├─ fetch_etf_quote(code='512890')          # R1 实时行情
  ├─ fetch_index_cons_weight(index='930955') # R2 published 成分
  └─ tracking_error_report(etf_code, index_code, windows)  # R3 跟踪误差

backend/strategies/index_replication_floor.py
  ├─ build_position_batches(total=100000, n_batches=5, interval_days=7)  # R4 分批建仓
  ├─ hold_status()                          # 持有状态（从 .vibe-research/ 读）
  └─ weekly_report()                        # R5 周报
```

### 5.3 分批建仓设计

- 默认 5 批 × 2 万，每批间隔 7 个交易日（可切一次性）
- 每批记录：日期 / 买入价 / 份数 / 金额，写入 `data_dir() / 'etf_floor' / 'batches.json'`（`.vibe-research/` 下，不进 git）
- 分批是 **timing 风险缓释**，不是择时信号——均匀分批降低单日买点方差，是 feature 非择时
- 建仓完成后进入 hold 态，无再平衡触发（长线底仓）

### 5.4 跟踪误差口径

- ETF 净值收益（复权）vs 930955 指数收益，日收益序列做差
- 跟踪误差 = std(差值序列) × sqrt(252)（年化）
- 绿灯 < 1%（ETF 跟踪红利低波指数的合理误差范围）
- 黄灯 1-2%（关注，可能申赎 / 调样 lag）
- 红灯 > 2%（→ §9 回滚：换 512890 替代品如 515450 / 159525）

### 5.5 备选方案为何不选

- **自复制 930955 成分**：5 元最低佣金击穿（§2.2），10 万规模不适用。≥500 万 + 0 元佣金券商时可 revisit。
- **期货 / 期权拿 beta**：红利低波无对应衍生品流动性，不可行。
- **场外指数基金（联接基金）**：申赎 T+2，不如 ETF 灵活，且申赎费可能高于 ETF 佣金。ETF 是最优载体。

## 6. 验收标准

- [ ] A1 `fetch_etf_quote('512890')` 返回现价 / 涨跌 / 成交额，非空（联网验收）
- [ ] A2 `fetch_index_cons_weight('930955')` 返回成分 + 权重，行数 ≥ 50（930955 成分数）
- [ ] A3 `tracking_error_report('512890', '930955')` 产出近 1/3/6/12 月跟踪误差，数值合理（< 2%）
- [ ] A4 `build_position_batches(total=100000, n_batches=5)` 产出 5 批建仓计划，间隔 7 交易日
- [ ] A5 `weekly_report()` 产出持仓市值 / 成本基 / 浮动盈亏 / 跟踪误差报告
- [ ] A6 无主动卖出逻辑（代码中无 stop/take 触发，grep 确认）
- [ ] A7 `pytest -m "not live"` 全绿（不破坏现有）
- [ ] A8 持仓 / 成本数据写入 `.vibe-research/`，未进 git（`git status` 确认）

## 7. 合规与工程底线自查（逐条确认）

- [x] **研判/推荐/买卖时机**：本臂给建仓计划（分批 / 一次性）+ 跟踪报告，属系统能力（2026-07-30 新口径，CLAUDE.md §1.1）。ETF 是公开产品，无个股推荐合规风险。用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」。
- [x] **判断可复现**：ETF 行情 / 指数 published 均为公开数据，akshare 取数可复算。跟踪误差用标准口径（日收益差 std × sqrt(252)），禁臆造 / 心算。涉及成本的对比已在 §2.2 列明口径。
- [x] **涨停四池/连板股榜**：不涉及（本臂是 ETF 底仓，非涨停 / 连板榜单）。
- [x] **用户私有数据隔离**：持仓 / 成本基 / 建仓批次写入 `data_dir()`（`.vibe-research/`，gitignored，绝不进 git）。见 `vr_paths.py` `data_dir()` 实现。
- [x] **新增东财端点走 `em_get`**：本臂用 akshare `fund_etf_spot_em`（走 datacenter，**非 push2/push2his**）。datacenter 端点不触发 ut token / IP 封禁（memory `eastmoney-push2-ut-token` 确认：push2/push2his 才需 ut + em_get，datacenter 不需）。故无防封问题。仍遵循 akshare 调用间 sleep ≥ 2s 惯例。

**弱合规定位**：私人投研助理（自托管、个人使用），ETF 公开产品，无合规仪式需求。工程底线（不臆造 / 私有数据隔离 / 防封）全部确认通过。

## 8. 测试计划

- **单测（离线）**：
  - `test_fetch_etf_tracking`：mock akshare 返回，验取数解析 + 跟踪误差计算口径
  - `test_index_replication_floor`：mock 行情，验分批建仓计划生成 + 周报格式
  - 跑 `pytest -m "not live" backend/tests/ -k "etf_tracking or index_replication"`
- **联网验收**：A1-A5 手动跑一次（akshare 取真实 512890 + 930955）
- **不破坏现有**：A7 全量 `pytest -m "not live"` 绿

## 9. 风险与回滚

| 风险 | 影响 | 回滚 |
|---|---|---|
| ETF 512890 跟踪误差 > 2%（红灯）| 底仓偏离 published beta | 换替代品：515450（红利低波 ETF 转型）/ 159525（红利低波 100 ETF），重跑跟踪误差 |
| 分批建仓期市场大跌 | 建仓期浮亏 | **是 feature 非 bug**——分批降 timing 风险，大跌反而后续批次买更低成本。不触发止损（长线底仓 hold）|
| akshare `fund_etf_spot_em` 接口变更 | 取数失败 | 降级到 hithink ETF 行情端点（已集成）或东财 datacenter 直取 |
| 930955 调样期间成分未更新 | 跟踪误差短期跳升 | 标注调样窗口，黄灯容忍，调样完成后复算 |
| 周报 cron 接线后 scheduled_tasks 冲突 | 定时任务异常 | 本 spec 只建工具，不强制接 cron（R5 周报先手动跑）；接线在后续 plan 决定 |

---

> 本 spec 只写规范，不写实现代码。下一步：plan.md（技术方案）→ tasks.md（任务拆分）→ 实现 → 验收。SDD §0 不跳。
> B 臂（experimental，smart-beta 优化）另 spec，不在本 spec 范围。
