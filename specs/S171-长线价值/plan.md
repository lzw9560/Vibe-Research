# Plan: S171 — 价值因子月度 §44v2 验证

> 状态：草案 | 日期：2026-09-08 | 分级：medium | 关联：[spec.md](./spec.md)（822db17 定稿）

## 1. 模块拆分 + 依赖序

| 模块 | 文件 | 依赖 | 状态 |
|---|---|---|---|
| R3 共享基建 | `backend/tools/_s44_wire.py` + `backend/s44_verifier/verifier.py` | 无 | step 参数已 done（a99214f）；**event_materiality_floor 第 5 参数待加**（bug 6） |
| R1 数据采集 | `backend/tools/scan_long_value_cache.py`（新建） | R3（cache 格式兼容 R2） | 待实现 |
| R2 harness | `backend/tools/long_value_run.py`（新建） | R1 cache + R3 wire_verdict | 待实现 |

**依赖序**：R3 event_materiality_floor 第 5 参数（先，10 min，TDD）→ R1 数据采集（background，Layer0 2.5hr pre-check → Layer1-4 ~11hr baostock）→ R2 harness（TDD + dry-run）→ verdict → 逐条对 spec §4 验收 → 归档。

## 2. 数据流

`baostock/akshare → cache（.vibe-research/，.gitignore，不 in git）→ R2 harness 构建 survivors/universe + PIT earnings + 退市 -100% → wire_verdict（5 参数透传）→ verify() → Verdict → Recorder + lineage`

cache 文件（6 个）：
- `baostock_kline_cache_long.json`（**两套**：adjustflag=2 前复权 return 用 + adjustflag=3 不复权 PE 用，bug 1 fix）
- `profit_data_cache_multiyear.json`（pubDate+epsTTM+roeAvg+MBRevenue+totalShare，2016-2026×4Q）
- `historical_universe_monthly.json`（每月 PIT active 集，含停牌过滤 + outDate 二义 sanity）
- `stock_basic_type1.json`（ipoDate+outDate 元数据，code 前缀过滤 A 股非 type=1）
- `benchmark_indices.json`（HS300+ZZ500 pctChg，须补股息率 caveat）
- `stock_value_em_exploratory.json`（Layer0 pre-check，若跑）

## 3. R3 event_materiality_floor 第 5 参数（先做，~10 min TDD）

`_s44_wire.wire_verdict` 加 `event_materiality_floor` 参数（第 5 个，None 默认，条件透传 + 存 Recorder params——bug 6：verifier.py:370-374 是唯一直接影响 status 的参数，不存→reproduce 用默认 0.003 非 harness 0.001→status 翻→A5 炸）。S171 传 0.001（月频校准，默认 0.003=日频 3.6%/年对 value 2-4%/年恒 thin_positive）。

TDD 2 测试（同 a99214f 模式）：`test_wire_verdict_passes_event_materiality_floor` + `test_stores_event_materiality_floor_for_reproduce`。向后兼容 None 默认。

## 4. R1 scan_long_value_cache.py（数据采集，Layer 非任意序）

依赖序（Layer1 需 stock_list 先就绪）：
1. **Layer0.5** `query_stock_basic`（code 前缀过滤 A 股：sh.6/sz.000/sz.002/sz.30/sh.688/bj，非 type=1 参数——baostock 无）→ `stock_list_type1.json`
2. **Layer0**（可选）akshare `stock_value_em` pre-check（PIT 待验子步骤 + falsified spot-check，spec R1 Layer0）
3. **Layer1** baostock kline 多年（2016-01-01..2026-09-03，**两套 adjustflag=2+3**，per 50 股 re-login，fields=date/open/high/low/close/volume/amount/turn/pctChg/isST）
4. **Layer2** baostock `query_profit_data` 多年（2016-2026×4Q，pubDate+epsTTM+roeAvg+MBRevenue+totalShare）
5. **Layer3** `query_all_stock`(月末) PIT active 集（**PIT 第一步 gate**：抽查≥3 月末 ∩ stock_basic(outDate>D) 非空，否则 fallback）+ type=1 交集过滤指数/债券/ETF + outDate='' 二义 sanity（last bar 远→疑似漏标退市）+ 0 bars coverage 审计（计入严格分母）+ 停牌股过滤（volume==0 stale close，双重剔除 universe+Q1/Q5 候选）
6. **Layer4** benchmark HS300+ZZ500（pctChg，须补股息率 caveat）

**checkpoint/resume**：per-batch-50 JSON sidecar atomic write（tmp+os.replace，防 kill 时损坏）。cache 文件 atomic write（per-batch append 到内存 dict → tmp+os.replace，防 truncated JSON）。

## 5. R2 long_value_run.py（harness）

月度 rebalance（月末最后交易日 `query_trade_dates`）→ PIT earnings gate（`pubDate < D` 严格小于，`get_pit_profit_row` helper + `(pubDate, quarter_key)` 元组降序 sort tie-breaking——bug 7+8）→ quintile 选股（**不复权 close** PE，bug 1）→ build：
- **co-PRIMARY ①** Q1-Q5 spread（event edge_type，mean t-test）
- **co-PRIMARY ②** Q1-excess-universe（selection edge_type，survivors/universe → PurgedKFold+walk-forward OOS）
- **AUXILIARY** selection-low_pe/high_pe
- **SECONDARY** Q1-excess-HS300（event，size-confounded caveat；BH m=1 latent caveat 若扩 K）

cost 预扣（`returns -= round_trip_cost × (turnover_Q1 + turnover_Q5)` 分腿实测，非 single×2）+ 退市 -100% inject（最后 active 交易月，survivors/universe 一致，bug 4 计入分母）+ sensitivity -0.5/-1.0 两档 → window_sanity={"path":{mean,winrate,base_rate}} → `wire_verdict`（5 参数：window_sanity/walk_train=36/walk_test=12/step=12/**event_materiality_floor=0.001**）→ **三 gate**：互验 gate（①② 一致）+ sensitivity 一致性 gate（-0.5/-1.0 一致）+ 严格覆盖率 gate（≥50%）。

## 6. 取舍（备选为何不选）

- **adjustflag=3 不复权 PE**（非 adjustflag=2 前复权）：前复权价调当前股本，epsTTM 原始股本→PE 虚低→成长股误入 Q1（bug 1 致命）。return 仍用前复权 total return（含 split/dividend 经济回报）。
- **双 co-PRIMARY 互验**（非"单 PRIMARY + 方向一致性检查"）：grill 条1 B 用户确认；workflow round 3 重构推翻被回滚（①② 共享 Q1 腿非独立=workflow 理由，但互验 gate 仍有效）。
- **sensitivity 两档一致性 gate**（非 descriptive flag）：grill 条4a 用户确认（sensitivity 回答"退市 -1.0 假设驱不驱动 verdict"）；workflow round 2 降 descriptive 被回滚。
- **不引入 dual-field/honesty_flags 架构**（YAGNI）：scope 不蔓延到 Recorder 大改；honesty 标注用 Verdict.note + params dict 足够（Recorder append-only 已支持）。
- **不加 ZZ500 SECONDARY**（YAGNI）：HS300 够 benchmark；ZZ500 是 workflow 过度修订回滚。
- **不加 reversal-control / 2015 crash 扩展 / TTM cyclical-peak / Shiller CAPE / accruals**（deferred）：非 S171 核心，deferred 段记。

## 7. 测试策略

- **R3 event_materiality_floor**：TDD 2 测试（透传 + 存 params for reproduce）
- **R1 scan**：per-Layer dry-run（Layer0.5/1/2/3/4 各自验 cache 格式 + atomic write + resume + PIT 第一步 gate）
- **R2 harness**：`--dry-run`（构建 survivors/universe 不跑 wire_verdict，验 PIT gate + 退市 -100% 注入完整性 + quintile 跨调整法 stability + 停牌过滤）+ **mini-wire**（5-10 月小样本跑 wire_verdict 全 5 参数，缩减 walk_train/walk_test=3/2 触发 OOS 路径 + PurgedKFold n_splits=2 ≥4 dates 避退化）
- **A5 reproduce**：每 verdict_id 重算 status 一致（含 event_materiality_floor 存了）
- **A6 pytest** `-m "not live" --deselect 3 flaky` 全绿（R3 additive 向后兼容，无回归）
- **退市 sensitivity**：-0.5 vs -1.0 两遍一致性 gate + 注入完整性 A-test（survivors/universe 同月同值 -1.0）

## 8. 风险（实现期）

- baostock 全股多年 fetch ~11hr（Layer1-4），若中断→checkpoint resume 须 atomic write 否则白跑
- profit_data 2016-2017 覆盖稀疏→days_robust 可能<60→underpowered 诚实标
- query_all_stock PIT 行为未验→若返当前快照→survivorship bias（Layer3 第一步 gate 把关）
- 退市 0 bars 股占比未知→若>5%→unrecoverable bias 降级
