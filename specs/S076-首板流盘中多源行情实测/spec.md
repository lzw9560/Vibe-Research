# Spec: S076 — 首板流盘中多源行情实测

> 状态：草案
> 作者：lzw9560  日期：2026-08-18
> 关联：S075-首板流（父 spec，盘中闭环）/ §44 复验窗口 / winrate doc §10.1 D7d（影子先行）
> 级别：small（纯探查脚本，零生产改动）；若 mootdx 需先 minimal 接线才能测，升级 medium（届时补 plan.md）

## 1. 问题 / 目标

首板流盘中链（confirm + position）要接线（S075 闭环中间断口：filter T-1✅ → confirm+position 未接 → t1_review T+1✅）。但盘中关键数据点依赖 `tencent_quote` 在 9:25 集合竞价 + 9:31-9:35 开盘采样的行为——**这是未核实盲区**（`astock.py` 无注释，grep 空）。单源依赖风险高（tencent 9:25 `open` 可能空 → `fetch_auction_data` 跑不了 → 竞价确认后移）。

本 spec **实测多源**（tencent / mootdx / 东财 push2 via `em_get`）在盘中关键时点的返回可用性，产出「源 × 时点 × 字段 × 可用性」矩阵，为后续多源回退层 spec 提供依据。**零风险探查脚本，不改生产。**

## 2. 背景

### 2.1 grill 决策来源（2026-08-18 /grill-me 首板流）

设计 + 盘中两轮 grill 收敛的 8 项动作清单中，**#7 实测先行**（零风险出数据，给后续所有动作地基）。本 spec 仅覆盖 #7。其余 7 项（拔 9 维 ranker / 影子盘接线 / 多源回退层 / B1 剔除验证 / 卡片重写 / T-1 自选观察推送 / 转真建仓）后续各自 spec。

关键 grill 决策（与本 spec 相关）：
- **影子先行（D7d）**：盘中先接影子盘（记账不真建仓），≥30 交易日 + 洞B-gate≥2x 才转真建仓。
- **多源层复用现成职责链模式**：tencent 主 / mootdx 备 / 东财 push2 末选（脆弱不进主路径）。
- **建仓 gate (ii)**：后端自动 select + 记账 + 飞书推（α 诚实口径「通过确认 N 只受 cap 取前5，时间序非质量排序，§44 未验证」），系统不下单（红线）。

### 2.2 已核实事实

| 事实 | 来源 |
|---|---|
| mootdx 源在仓但未接 astock 主 quote 路径 | `backend/data/sources/mootdx_src.py`（`Quotes`） |
| 东财 push2 偶发断连（自陈） | `astock.py:22` 注释 |
| `em_get` 包熔断（5 次 OPEN/60s 恢复）+ 代理降级 | `data/transport.py` |
| **现成多源回退模式**：kline `baidu→sina→mootdx→akshare` 职责链+策略 | `astock.py` |
| 涨停池已有备用源先例（交叉验证） | `ths_limit_up_pool` |
| 东财 push2 已知坑：需 ut token / IP 封 / 探测≥10min | 记忆 `eastmoney-push2-ut-token` |
| confirm 需喂的字段：open/last_close/vol_ratio/amount_wan/price | `first_board_confirm.py` |

### 2.3 confirm 模块的数据需求（实测靶子）

confirm 三必要 AND 门需在 9:25-9:35 取得：
- ① 竞价高开 1-3% → `open` + `last_close`（9:25）
- ② 量比 >1.5 → `vol_ratio`（9:30+）
- ③ 5 分钟不破开盘价 → 9:31-9:35 每分钟 `price` 采样

本 spec 测的就是这三个字段在三个源、各关键时点的可用性。

## 3. 需求清单

- [ ] R1 探查 `tencent_quote` 在 9:20-9:30（集合竞价）+ 9:31-9:35（开盘采样）+ 9:36（对照）各时点返回：`open`/`last_close`/`vol_ratio`/`amount_wan`/`price` 是否非空、值是否合理、延迟 ms
- [ ] R2 探查 `mootdx_src`（`data/sources/mootdx_src.py`）同时段能否取到竞价价 / 五档 / 逐笔 / 实时价（若 mootdx 不可直调，产出「mootdx 需先 minimal 接线」结论）
- [ ] R3 探查东财 push2（via `em_get`，限流）同时段实时 tick 可用性：ut token 需求 / 断连率 / 返回字段
- [ ] R4 产出「源 × 时点 × 字段 × 可用性」矩阵 JSON + 人话结论（哪个源在哪个时点能喂 ①②③）
- [ ] R5 `tools/` 脚本只读；**唯一生产改动 = `scheduled_tasks.py` 加临时任务类型** `first_board_quote_probe`（R7 auto-trigger，回滚=disable 任务+删 _execute）
- [ ] R6 东财 push2 探查走 `em_get` 限流（不裸调 requests，探测间隔 ≥10min，断连统计但不重试刷屏）
- [ ] R7 auto-trigger：`scheduled_tasks` 加 `first_board_quote_probe` 任务（cron `20-36 9 * * 0-4` 每分钟 9:20-9:36，push2 ≥10min 状态文件门控 `.scratch/s076-quote-probe/push2_state.json`）；临时研究，收 3-5 天后 disable；需 app 进程在 9:20-9:36 运行（无 catch-up）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `tools/first_board_quote_source_probe.py`（新建，与 Phase 0 `first_board_premium_baseline.py` 同目录，实现时确认确切路径） | 多源探查脚本 |
| `.scratch/s076-quote-probe/matrix_{date}.json`（新建） | 输出矩阵 JSON |
| `.scratch/s076-quote-probe/conclusion.md`（新建） | 人话结论 |
| `backend/scheduled_tasks.py` | +`first_board_quote_probe` 任务类型 + `_execute`（push2 状态门控）+ seed cron `20-36 9 * * 0-4`（临时，回滚=disable 任务+删 _execute） |

## 5. 设计方案

### 5.1 探查流程

脚本在真实交易日的 9:20-9:30 + 9:31-9:35 + 9:36 各跑一次（手动触发或 cron 一次性），对每源每时点取数，记录：字段值、非空、合理性（高开在 0-10% 内、量比 0-10 内等）、延迟 ms。

### 5.2 三源

- **tencent**：`astock.tencent_quote`（60s 缓存，探查时绕缓存或标注缓存命中）
- **mootdx**：`data.sources.mootdx_src`（直调；若 import/初始化失败 → 结论标「需先接线」，不在本 spec 接）
- **东财 push2**：via `em_get`（限流 + 熔断，≥10min 间隔；ut token 缺则标「不可用」）

### 5.3 输出

```
matrix_{date}.json = {
  date, sampled_at: ["09:20","09:25","09:30","09:31"..."09:35","09:36"],
  sources: {
    tencent: { "09:25": {open:{val,non_empty,sane,latency_ms}, last_close:{...}, ...}, ... },
    mootdx:  { ... },
    em_push2:{ ... }
  },
  conclusion: "9:25 竞价确认可用源=X；9:31-9:35 采样可用源=Y；..."
}
```

### 5.4 取舍

- **不在脚本里做回退**（那是后续多源回退层 spec 的事），本脚本只探查产出矩阵。
- **不选「直接盲搭多源回退层」**：不知各源 9:25 实际返回，会建在错误假设上。
- **不选「只测 tencent」**：用户要求多源，且 tencent 单源风险高（9:25 open 可能空）。

## 6. 验收标准

- [ ] A1 脚本在真实交易日 9:20-9:35 跑通，产出 `matrix_{date}.json`
- [ ] A2 矩阵覆盖 tencent/mootdx/东财 push2 三源 × 9:25/9:31-9:35 关键时点 × confirm 所需字段（open/last_close/vol_ratio/amount_wan/price）
- [ ] A3 结论明确回答：9:25 竞价确认能用哪个源（tencent `open` 是否空、mootdx 能否补、东财 push2 可用性）；9:31-9:35 采样哪个源稳定
- [ ] A4 东财 push2 探查走 `em_get` 限流（不裸调，断连率统计不刷屏）
- [ ] A5 不改生产代码（只读探查，git diff 无生产文件）
- [ ] A6 多日跑 3-5 个交易日取稳定结论（单日 tencent 偶发断连不误判）
- [ ] A7 矩阵结论喂后续「多源回退层」spec（本 spec 不实现回退层）
- [ ] A8 auto-trigger 任务 seeded + push2 状态门控单测过（4 态：无状态/状态新/状态旧/payload override）✅

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机：本 spec 是探查脚本，无用户可见研判/推荐/买卖输出 → 合规无涉
- [x] 判断可复现：探查产出原始返回数据矩阵，非研判；不涉及市值/估值/三情景，`financial_rigor.py` 不适用
- [x] 涨停四池/个股：本 spec 不呈现个股 code/name 给用户（只测行情源技术可用性）→ 无涉
- [x] 用户私有数据：探查用公开行情源，不触私有数据；输出矩阵放 `.scratch/`（不入 git）
- [x] 东财端点走 `em_get` 限流：R6 明确，push2 探查走 `em_get` 不裸调，≥10min 间隔

## 8. 测试计划

- **离线单测**（`pytest -m "not live"`）：mock 三源返回，验矩阵生成 + 合理性判定逻辑。
- **联网/手动**（主验收）：真实交易日 9:20-9:35 手动触发（或 cron 一次性），观察矩阵；连续 3-5 个交易日取稳定结论。
- 不进 `pytest -m "not live"` 默认套件（live 探查，按 `newsradar-flaky-network-test` 教训 deselect 或标 live）。

## 9. 风险与回滚

| 风险 | 处置 |
|---|---|
| tencent 9:25 返回空 | 预期场景 → 结论「竞价确认后移 9:30」，confirm 降级（grill 已备选） |
| mootdx 不可直调（需先接线） | 结论标「mootdx 需先 minimal 接线」，升级 medium 补 plan.md，不在本 spec 接 |
| 东财 push2 ut token 缺/断连 | 矩阵标「不可用/末选」，符合预期（本就定末选） |
| 单日偶发断连误判 | A6 多日 3-5 天取稳定结论 |
| 回滚 | 纯探查脚本，删脚本 + `.scratch/s076/` 即可，零生产影响 |
