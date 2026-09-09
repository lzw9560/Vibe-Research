# Spec: S176 — 盘中 conditioning 数据收集器（intraday OFI store，非信号生成器）

> 状态：已实现 v1（T1-T6 done，35 tests green + 188 全量无回归；conditioning lift harness deferred 等 60 天 live）
> 作者：lzw9560  日期：2026-09-10
> 关联：S175-模拟盘自洽闭环（deferred note: conditioning harness 应作数据收集器非信号生成器）/ S167-盘中微结构数据累积（intraday_accumulation_store 复用）/ S161-§44v2验证框架（conditioning lift harness deferred 等 60 天 live）
> 分级：medium —— 盘中数据收集器（五档轮询 + OFI + 封单诚意补全），非策略/非信号生成

## 1. 问题 / 目标

north-star「edge 在盘中未测」（memory `edge-in-intraday-not-selection`）—— §44 S168 12 harness 全 falsified **selection 层**（D+1 path, 无 conditioning, survivorship），盘中 conditional 未测是 §44 reframe 最 promising 方向。

打板量化模型设计（KG active `打板量化模型设计`）定义 6 盘中 conditional 因子：封单成交比 / 封单诚意 / OFI / 竞价量能 / 封板时间 / 盘口买压。当前 codebase 已有大半基建（seal_intraday_snapshots 60s / 竞价累积 / intraday_features / intraday_accumulation_store），但**缺五档时序轮询采集器 + OFI 纯函数 + 封单诚意补全**。

**S176 = 数据收集器**（写盘中五档/OFI/封单诚意到 intraday_accumulation_store extend），**非信号生成器**（S175 spec deferred note 明确：conditioning harness 应作数据收集器非信号生成器；conditioning lift harness regime 分层 §44v2 验证 deferred 等 60 天 live 数据）。

一句话：盘中定时（9:30-15:00）轮询腾讯五档（qt.gtimg.cn 不封 IP，e9ce79f 已解析）→ 算 OFI + 封单诚意 → 写 intraday_accumulation_store extend（独立 store，不喂 trade_journal），攒 60 天 live 数据供未来 §44v2 conditioning lift 验证。

## 2. 背景

### 2.1 §44 reframe（edge 在盘中未测）

- §44 S168 12 harness 全 falsified selection 层（D+1 path, 无 conditioning, survivorship）。
- memory `edge-in-intraday-not-selection`：edge 在盘中 conditional（未测 reframe 最 promising）。
- memory `methodology-window-before-no-edge-conclusion`：出无 edge 结论前先验窗口——§44 测错层（selection 非 盘中）。

### 2.2 6 盘中 conditional 因子（KG 打板量化模型设计）

| # | 因子 | 定义 | 数据源 | S176 覆盖 |
|---|------|------|--------|-----------|
| 1 | 封单成交比 seal_turnover_ratio | seal_amount/turnover_amount | 东财 zt_pool fund + tencent amount_wan，**S167 seal_intraday_snapshots 60s 已采集** | 已有（不重造） |
| 2 | 封单诚意 seal_sincerity（5 维） | slope/delta_ratio/volatility/break_count/drawdown | compute_trajectory 已有 3（slope/break_count/...），**需补 3 纯函数** | **R3 补全** |
| 3 | **OFI 订单流失衡** | Σ[Δbuy_i_vol − Δsell_i_vol]（5 档，涨停前）；涨停后退化为 Δseal_amount | tencent _parse_gtimg 五档（e9ce79f，不封 IP）/ eastmoney bids em_get | **R1+R2 新建** |
| 4 | 竞价量能 auction_vol_ratio | auction_amount/prev_total_amount | **S167 intraday_auction_snapshots 9:15-9:25 已采集** | 已有（不重造） |
| 5 | 封板时间 seal_time | first_seal_time + last_lock_time | compute_derived_features 已有 | 已有（不重造） |
| 6 | 盘口买压比 bid_ask_pressure | Σbuy_vol/Σsell_vol（5 档） | tencent _parse_gtimg 五档 / eastmoney bids | **R1 复用 + R2 纯函数** |

**S176 新建限于**：五档时序轮询采集器（R1）+ OFI 纯函数（R2）+ 封单诚意补全 3 纯函数（R3）。因子 1/4/5 已有（S167/intraday_features），不重造。

### 2.3 codebase 复用（不重造，KG 清单 + fresh grep）

- `backend/data/sources/tencent.py:46 _parse_gtimg`（e9ce79f）——五档买卖盘已解析（buy/sell list[{level,price,vol}]，fields 9-28）。**S176 高频源**（qt.gtimg.cn 不封 IP 无显式限流 vs em_get 0.3s 串行）。
- `backend/strategies/intraday_features.py`（S070）——compute_trajectory（seal_delta/slope/max/min/snapshot_count）+ compute_derived_features（last_lock_time/broken_duration/max_drop）+ SealTrajectory dataclass（break_count 已有）。**R3 扩展 3 纯函数**。
- `backend/data/intraday_accumulation_store.py`（S167）——盘中微结构累积库（intraday_auction_snapshots/intraday_quote_snapshots/baostock_5min_freeze），schema+save/load 全套。**R4 extend ofi_snapshots 表**。
- `backend/scheduler/executors/intraday.py`——seal_intraday_collect（60s）+ intraday_microstructure_snapshot（*/10）+ intraday_auction_dense（*/2）。**R5 仿照加 ofi_collect executor**。
- `backend/strategies/first_board_filter.py:276`——已从 zt_pool fund 取 seal_amount 写候选 dict（候选股池来源）。

### 2.4 频率约束（KG 数据 map）

- OFI ≥3s 五档轮询（tencent 不限流，多股分批可行；em_get 0.3s 限流则多股串行慢）。
- 封单诚意 60s 上界（zt_pool 端点限流≥10min，不可加密——S167 已有 60s）。
- 竞价 9:15-9:25 每 1min（S167 已有）。
- **L2 逐笔免费不可得**（同花顺/东财超级 Level-2/新浪/券商均付费）→ 3s/60s 粒度是免费源上界，封单诚意撤单方向精度需付费（标 coarse 近似）。

## 3. 需求清单

- [ ] R1 **五档时序轮询采集器**：建 `engine/intraday_ofi_collector.py`——盘中（9:30-15:00）每 3-5s 轮询 tencent _parse_gtimg 五档（涨停股池候选）→ 取 buy/sell list[{level,price,vol}]。**用 tencent（不封 IP 无限流）非 em_get（0.3s 限流）**——memory `tencent-gtimg-5level-latent` 解 OFI 3s→1s 瓶颈。
- [ ] R2 **OFI + 盘口买压 纯函数**：建 `engine/intraday_ofi.py`（~30 行）——`compute_ofi(buy_levels, sell_levels)` = Σ(buy_vol) - Σ(sell_vol) 或 (Σbuy - Σsell)/(Σbuy + Σsell)；`compute_bid_ask_pressure(buy_levels, sell_levels)` = Σbuy_vol/Σsell_vol（涨停时 sell=0 →∞，cap 或转 seal_amount）。纯函数无 IO，可单测。
- [ ] R3 **封单诚意补全 3 纯函数**：`strategies/intraday_features.py` 扩展 `compute_seal_delta_ratio`（净增减比）/ `compute_seal_volatility`（高=演戏忽大忽小）/ `compute_seal_drawdown`（峰值回撤）——各 ~10 行，复用 SealTrajectory dataclass。slope/break_count 已有。
- [ ] R4 **intraday_accumulation_store extend**：加 `ofi_snapshots` 表（code/date/time/ofi/bid_ask_pressure/buy_vols_json/sell_vols_json/seal_amount/regime）+ save_ofi/load_ofi 方法。**独立 store（.vibe-research/intraday_ofi via intraday_accumulation_store），不喂 trade_journal**（S175 spec deferred note）。
- [ ] R5 **scheduler executor**：`scheduler/executors/intraday.py` 加 `ofi_collect(payload)` executor（仿 seal_intraday_collect）+ `scheduler/executors/__init__.py` dispatch + `seed.py` cron 盘中 `* 9-14 * * 1-5`（每分钟，盘中 9:00-14:59）or `*/3` OFI 高频。**收盘后停**（15:00 后不跑）。
- [ ] R6 **候选股池**：涨停股池（zt_pool 当日涨停）+ premarket_candidates（盘前候选）——只收集 ~20-50 股非全市场 4106（baostock 5226 太多）。从 first_board_filter 候选 dict 或 zt_pool。
- [ ] R7 **数据质量门**：缺失/异常五档（vol=0/price=0/格式错）不写，降级不崩（对齐 tencent _parse_gtimg 返空处理）。tencent 不封 IP 但单股请求偶发失败 → 跳过该股该次。
- [ ] R8 **不喂 trade_journal**：intraday_ofi 独立 store，不调 trade_journal.insert，非信号生成器。S176 只收集，conditioning lift harness（regime 分层 §44v2 验证）deferred 等 60 天 live 数据。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/engine/intraday_ofi_collector.py` | **新建** R1 — 五档时序轮询采集器（tencent _parse_gtimg，涨停股池） |
| `backend/engine/intraday_ofi.py` | **新建** R2 — OFI + bid_ask_pressure 纯函数 |
| `backend/strategies/intraday_features.py` | R3 — 扩展 compute_seal_delta_ratio/volatility/drawdown 3 纯函数 |
| `backend/data/intraday_accumulation_store.py` | R4 — extend ofi_snapshots 表 + save_ofi/load_ofi |
| `backend/scheduler/executors/intraday.py` | R5 — 加 ofi_collect executor |
| `backend/scheduler/executors/__init__.py` | R5 — _executors dispatch 加 ofi_collect |
| `backend/scheduler/seed.py` | R5 — 加 cron 盘中 ofi_collect |
| `backend/data/sources/tencent.py` | 复用 _parse_gtimg（e9ce79f，不改） |
| `backend/tests/test_intraday_ofi.py` | **新建** — OFI 纯函数 + 采集器 + store 测试 |

## 5. 设计方案

### 5.1 数据流

```
cron 盘中 * 9-14 * * 1-5（每分钟，盘中 9:00-14:59；OFI 高频可 */3）
→ TaskExecutor._execute_ofi_collect [R5]
→ ofi_collect(payload)
  ├ 取候选股池（zt_pool 涨停 + premarket_candidates，~20-50 股）[R6]
  ├ per stock: tencent._parse_gtimg(code) → buy/sell 五档 list [R1]
  ├ compute_ofi(buy, sell) + compute_bid_ask_pressure(buy, sell) [R2]
  ├ 封单诚意（如涨停）：compute_seal_delta_ratio/volatility/drawdown [R3，复用 seal_intraday_snapshots 历史]
  └ save_ofi(store, code, time, ofi, pressure, buy_vols, sell_vols, seal_amount, regime) [R4]
→ intraday_accumulation_store.ofi_snapshots（独立 store，不喂 trade_journal）[R8]
```

### 5.2 OFI 公式（R2 纯函数）

```
OFI = Σ(buy_vol_i) - Σ(sell_vol_i)  for i in 1..5
    或归一化: (Σbuy - Σsell) / (Σbuy + Σsell)  ∈ [-1, 1]
bid_ask_pressure = Σ(buy_vol) / Σ(sell_vol)  （涨停 sell=0 →∞，cap 999 or 转 seal_amount）
```

涨停后退化为 Δseal_amount（封单净增=买压，KG 因子 3）——S176 涨停股用 seal_amount 替代 OFI（sell=0 时）。

### 5.3 频率 + 候选池

- OFI 每 3-5s（tencent 不限流）or 盘中每分钟（cron `* 9-14`，保守起步）。初版每分钟（SQLite 写入 + tencent 多股分批 ~20 股 × 0.3s = 6s，分钟内够）。
- 候选 ~20-50 股（zt_pool + premarket），非全市场。first_board_filter 候选 dict 或 zt_pool 当日涨停。

### 5.4 不喂 trade_journal（R8，S175 spec deferred note）

intraday_ofi 独立 store（intraday_accumulation_store.ofi_snapshots），不调 trade_journal.insert，不产 signal。S176 只收集数据，conditioning lift harness（regime 分层 §44v2 验证）deferred 等 60 天 live 数据后另起 spec。

## 6. 验收标准

- [ ] A1 **OFI 纯函数正确**：compute_ofi(buy=[{vol:100},{vol:200},...], sell=[{vol:50},{vol:100},...]) = (300-150)/(300+150) = 0.333。
- [ ] A2 **采集器写 store**：mock tencent _parse_gtimg 返五档 → ofi_collect 跑 → intraday_accumulation_store.ofi_snapshots 有记录（code/time/ofi/pressure）。
- [ ] A3 **不喂 trade_journal**：ofi_collect 跑后 trade_journal.db 无新记录（独立 store，grep trade_journal.insert in ofi_collect = 0）。
- [ ] A4 **数据质量门**：tencent 返空/格式错 → 跳过该股该次，不崩，其他股正常写。
- [ ] A5 **封单诚意补全**：compute_seal_delta_ratio/volatility/drawdown 3 纯函数单测过。
- [ ] A6 **私有隔离**：intraday_ofi 写 .vibe-research/（intraday_accumulation_store），不进 git。

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机——S176 是**数据收集器非信号**，不产推荐/不诱导交易（非信号生成器，S175 spec deferred note）。
- [x] 判断可复现——OFI 纯函数 + tencent raw 五档快照存盘，可重算（S088 范式）。
- [x] 涨停四池/连板股榜——候选股池从 zt_pool 公开涨停股，客观榜单。
- [x] 用户私有数据——intraday_ofi 写 .vibe-research/（intraday_accumulation_store resolve_data_dir），不进 git（.gitignore line 72）。
- [x] 东财端点走 em_get——**S176 用 tencent qt.gtimg.cn（不封 IP 无限流）非东财**，无 em_get 限流需求；seal_amount 复用 S167 seal_intraday_snapshots（已走 em_get 限流）。

## 8. 测试计划

- `cd backend && .venv/bin/python -m pytest tests/test_intraday_ofi.py -v`（OFI 纯函数 + 采集器 mock tencent + store extend + 数据质量门）
- `cd backend && .venv/bin/python -m pytest tests/test_intraday_features.py -v`（封单诚意 3 纯函数，如已有测试文件 extend）
- `cd frontend && npx tsc --noEmit`（无前端改动，确认不破）
- 手动：盘中跑 ofi_collect → intraday_accumulation_store.ofi_snapshots 有记录

## 9. 风险与回滚

- **盘中高频轮询**：tencent qt.gtimg.cn 不显式限流但高频可能触发（~20 股 × 0.3s × 每分钟 = 6s，分钟内够）。回滚：频率降到每 5min 或候选减到 10 股。
- **封单诚意撤单方向精度**：L2 逐笔免费不可得 → 60s/3s 粒度 coarse 近似（KG verdict 标 coarse）。接受精度限制，不假装精确。
- **intraday_accumulation_store extend schema**：加 ofi_snapshots 表（迁移幂等，对齐 memory migration-stubs-fresh-db-fix v1 完整 CREATE）。
- **不喂 trade_journal 隔离**：ofi_collect 不 import trade_journal（grep 确认），防误接。
- **deferred conditioning lift harness**：S176 只收集，不验 edge。等 60 天 live 数据后另起 spec（conditioning lift regime 分层 §44v2 验证）。

---

关联 memory：`edge-in-intraday-not-selection`（edge 在盘中未测）+ `tencent-gtimg-5level-latent`（五档已解 OFI 瓶颈）+ `methodology-window-before-no-edge-conclusion`（出无 edge 前先验窗口）+ `multiline-strategy-direction`（多线路，盘中打板 capture）+ `s175-spec-paper-trading-unified-loop`（S175 deferred note: conditioning harness 数据收集器非信号）。
