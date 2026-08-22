# 任务拆分 · S081 打板P2战法匹配扩展

> 对应：`spec.md`（草案）+ `plan.md`（技术方案）
> 粒度：原子任务（独立可验，1-2h/条）。每条含：依赖、改动文件、验收方式、映射 AC。

---

## 阶段 A · 弱转强接力战法（AC1/AC2/AC3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | STRATEGY_REGISTRY 加"weak_turn_strong"注册项（code/name/entry_type/stop_loss_pct/take_profit_pct/weather_regimes/aliases） | — | `backend/limitup_strategy.py` | `len(STRATEGY_REGISTRY)` +1；现有 9 项不破坏 |
| A2 | 核实 STRATEGY_REGISTRY 现有 9 战法是否有语义重叠（break_reseal/reverse_package 与弱转强/反包） | A1 | — | grep 现有 code/name，重叠则合并非新增 |
| A3 | match_strategies 加 weak_turn_strong elif 分支骨架 | A1 | `backend/limitup_strategy.py` | mock gene+pool_item 命中分支返 StrategySignal |
| A4 | 因子取数：lbc/hs 从 pool_item；broken_duration_min/max_drop_pct/last_lock_time 从 `intraday_features.compute_derived_features(get_snapshots_by_code(code,date))` | A3 | `backend/limitup_strategy.py` | mock snapshots 返派生值，断言因子取到 |
| A5 | vol_ratio_1d：hs / 前日 hs（前日取不到标 None 降级） | A4 | `backend/limitup_strategy.py` | mock 前日缺失，断言 vol_ratio=None 不报错 |
| A6 | 5 因子硬阈值判定 + 置信度打分（全命中 high/4 命中 medium/≤3 不输出） | A4,A5 | `backend/limitup_strategy.py` | mock 5/4/3 因子命中，断言 confidence 对应 |
| A7 | S070 R7 门禁：snapshots 取不到标 data_status="missing_s070_r7" 跳过 | A4 | `backend/limitup_strategy.py` | mock 非交易日/无快照，断言跳过不报错 |
| A8 | 触发价输出：entry_price = _round_to_tick_size(昨日涨停价) + disclaimer | A6 | `backend/limitup_strategy.py` | 断言 entry_price 精度 + disclaimer 字段 |
| A9 | 单测：弱转强接力战法全场景（5 因子全过/部分过/数据缺失/触发价精度） | A6,A7,A8 | `backend/tests/test_s081_prd_strategies.py` | pytest 过 |

## 阶段 B · 形态反包战法（AC1/AC2/AC4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | STRATEGY_REGISTRY 加"pattern_reversal"注册项 | A1 | `backend/limitup_strategy.py` | `len(STRATEGY_REGISTRY)` +1 |
| B2 | 核实 K线函数实际名（astock.kline grep 无匹配，找 stock_kline / data.sources.eastmoney.kline 等） | — | — | grep 找到 K线取数函数 |
| B3 | match_strategies 加 pattern_reversal elif 分支骨架 | B1 | `backend/limitup_strategy.py` | mock 命中分支 |
| B4 | 因子取数：close_pct 从 pool_item.zdp；max_high_pct/shadow_length_pct 从 K线（B2 核实的函数）；K线取不到标 None 降级 | B2,B3 | `backend/limitup_strategy.py` | mock K线缺失断言降级 |
| B5 | volume_1d/volume_2d 从 pool_item.fundamt + 前日对比；ma_5_status 从 K线+均线计算 | B4 | `backend/limitup_strategy.py` | mock 前日/均线 |
| B6 | 5 因子硬阈值判定 + 置信度打分 | B4,B5 | `backend/limitup_strategy.py` | mock 5/4/3 因子 |
| B7 | 触发价输出：entry_price = _round_to_tick_size(昨日K线最高价+0.01) + disclaimer | B6 | `backend/limitup_strategy.py` | 断言精度 + disclaimer |
| B8 | 单测：形态反包战法全场景 | B6,B7 | `backend/tests/test_s081_prd_strategies.py` | pytest 过 |

## 阶段 C · 回归 + 验收（AC5-AC9）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | 现有 9 战法回归：match_strategies 现有分支不破坏 | A3,B3 | — | `pytest test_s031*.py test_s063*.py`（现有战法测试）过 |
| C2 | StrategyMatcher.match() 自动覆盖验证：调 match() 返 PRD 战法信号 | A9,B8 | — | mock gene+pool_item 调 StrategyMatcher.match() 断言含 PRD 信号 |
| C3 | AC6 不接券商确认 + AC7 风险提醒自查 | A8,B7 | — | 代码审查无券商 API + disclaimer 全标注 |
| C4 | AC8 阈值探索性标注 + config 可配 | A6,B6 | `backend/limitup_strategy.py` | 阈值标"探索性"，进 config 可配（financial_rigor 待 live） |
| C5 | 全套 pytest 过 + 写验收报告 | C1-C4 | `specs/S081-打板P2战法匹配/验收报告.md` | 全绿 |

---

## 依赖图

```
A1(注册) → A3(分支) → A4(因子) → A6(阈值) → A9(单测)
                   → A5(换手) ↗     → A7(门禁) ↗
                                    → A8(触发价)↗
B1(注册) → B3(分支) → B4(K线因子) → B6(阈值) → B8(单测)
B2(核实K线) ↗      → B5(量/均线) ↗ → B7(触发价)↗
C1-C5 回归验收
```

关键路径：A1→A3→A4→A6→A9 + B1→B2→B3→B4→B6→B8 → C1→C5

---

## 执行规则

- TDD：先 RED（写测试断言）再 GREEN（实现）
- 每代码 task 跑 `pytest -m "not live"`
- 不写方向结论词外的执行指令（合规 §1.1）
- PRD 阈值标"探索性"，进 config 可配
- K线函数名待 B2 核实（spec 假设 astock.kline，实际可能不同）
