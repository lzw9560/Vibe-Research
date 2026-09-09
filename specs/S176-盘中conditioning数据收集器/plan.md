# Plan: S176 — 盘中 conditioning 数据收集器（技术方案）

> spec 见 `spec.md`。reuse 假设已 fresh grep 核实（intraday_accumulation_store schema/save 范式 / intraday_features compute_trajectory+SealTrajectory / tencent _parse_gtimg levels shape）。

## 1. 模块拆分

| 模块 | 行数估 | 职责 | 依赖 |
|---|---|---|---|
| `engine/intraday_ofi.py`（新建） | ~40 | OFI + bid_ask_pressure 纯函数（无 IO） | 无 |
| `engine/intraday_ofi_collector.py`（新建） | ~80 | 五档时序轮询采集器（tencent _parse_gtimg，涨停股池）→ 算 OFI + pressure → save_ofi | tencent + ofi 纯函数 + store |
| `strategies/intraday_features.py`（改） | +40 | compute_seal_delta_ratio/volatility/drawdown 3 纯函数（复用 compute_trajectory 输出 + SealTrajectory） | 无 |
| `data/intraday_accumulation_store.py`（改） | +50 | _SCHEMA_OFI + save_ofi/load_ofi（extend，同 save_quote 范式） | 无 |
| `scheduler/executors/intraday.py`（改） | +25 | ofi_collect executor（仿 seal_intraday_collect） | collector |
| `scheduler/executors/__init__.py`（改） | +2 | _executors dispatch + thin wrapper | intraday.py |
| `scheduler/seed.py`（改） | +8 | cron 盘中 `* 9-14 * * 1-5` ofi_collect | executors |
| `tests/test_intraday_ofi.py`（新建） | ~100 | OFI 纯函数 + 采集器 mock tencent + store + 数据质量门 | T1-T4 |

## 2. 依赖序

```
P0（无外部依赖，纯函数 + store）:
  T1 intraday_ofi.py OFI + bid_ask_pressure 纯函数（无依赖，TDD）← 一切前提
  T2 intraday_accumulation_store extend ofi_snapshots + save_ofi/load_ofi（schema+IO，无依赖）
  T3 intraday_features.py 3 封单诚意纯函数（复用 compute_trajectory，无依赖）
P1（依赖 T1+T2）:
  T4 intraday_ofi_collector.py 采集器（tencent _parse_gtimg → T1 OFI → T2 save_ofi）+ 数据质量门
P2（依赖 T4）:
  T5 scheduler/executors/intraday.py ofi_collect + __init__ dispatch + seed cron
  T6 集成验收（mock tencent 跑 ofi_collect → store 有记录 + 不喂 trade_journal）
```

## 3. 数据流

```
cron 盘中 * 9-14 * * 1-5（每分钟，9:00-14:59）
→ TaskExecutor._execute_ofi_collect [T5]
→ ofi_collect(payload)
  ├ 取候选股池（zt_pool 涨停 + premarket，~20-50 股）[R6]
  ├ per stock: tencent._parse_gtimg(code) → buy/sell 五档 list[{level,price,vol}] [T4, e9ce79f]
  ├ compute_ofi(buy, sell) + compute_bid_ask_pressure(buy, sell) [T1]
  ├ 涨停股（sell=0）：封单诚意 compute_seal_delta_ratio/volatility/drawdown [T3, 复用 seal_intraday_snapshots 历史]
  └ save_ofi(store, code, time, ofi, pressure, buy_vols, sell_vols, seal_amount, regime) [T2]
→ intraday_accumulation_store.ofi_snapshots（独立 store，不喂 trade_journal）[R8]
```

## 4. 关键设计决策

- **OFI 归一化**：`(Σbuy_vol - Σsell_vol) / (Σbuy_vol + Σsell_vol)` ∈ [-1, 1]（跨股可比）。绝对值版本另存 `ofi_abs`（跨股不可比但保留量级）。
- **涨停 sell=0 退化**：bid_ask_pressure = Σbuy/Σsell → sell=0 时 ∞ → cap 999.0；OFI 涨停后退化为 Δseal_amount（封单净增=买压，KG 因子 3）——S176 涨停股用 seal_amount（从 first_board_filter 候选 dict 或 seal_intraday_snapshots）替代 OFI。
- **tencent 非 em_get**：tencent qt.gtimg.cn 不封 IP 无显式限流（memory `tencent-gtimg-5level-latent`：解 OFI 3s→1s 瓶颈 vs em_get 0.3s 串行）。S176 五档轮询用 tencent。
- **intraday_accumulation_store extend 非 new store**：S167 已有 schema+save/load 范式（rankings/quotes/baostock/auction），R4 加 ofi_snapshots 同范式（不重造 store 框架）。
- **不喂 trade_journal**：ofi_collect 不 import trade_journal（grep 确认），独立 intraday_accumulation_store。S176 只收集，conditioning lift harness deferred。
- **频率**：初版每分钟（cron `* 9-14`），保守。tencent 多股分批 ~20 股 × 0.3s = 6s，分钟内够。后续可升 `*/3`（OFI 高频）。

## 5. 备选为何不选

- **不建 conditioning lift harness（regime 分层 §44v2 验证）**：S175 spec deferred note + KG verdict——等 60 天 live 数据后另起 spec。S176 只收集数据。
- **不用 em_get 走东财五档 bids**：tencent 不封 IP 无限流 vs em_get 0.3s 串行（memory `tencent-gtimg-5level-latent`）。tencent 是高频 OFI 更优源。
- **不新建独立 intraday_ofi store**：intraday_accumulation_store（S167）已有 schema+save/load 框架，extend ofi_snapshots 同范式（DRY，不重造 store）。
- **不收集全市场 4106 股**：候选 ~20-50 股（zt_pool + premarket），盘中高频只跟踪涨停/候选（非全市场扫描）。
- **不做 L2 逐笔撤单方向**：免费不可得（KG 数据 map），3s/60s 粒度 coarse 近似（标 coarse 不假装精确）。
