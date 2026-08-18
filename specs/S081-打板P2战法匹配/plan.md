# 技术方案 · S081 打板P2战法匹配扩展

> 对应 spec：`spec.md`（草案，S070 R7 已就绪）
> 分支：`feature/S081-战法匹配扩展`（off develop d15e57a）
> 作者：Claude ｜日期：2026-08-18

---

## 0. 依据与复用清单

| spec 要求 | 复用的现有能力（不重造） |
|---|---|
| R1 弱转强接力注册 | `limitup_strategy.STRATEGY_REGISTRY`（9 战法已实现，加第 10 项） |
| R2 match 分支扩展 | `limitup_strategy.match_strategies(code, gene, pool_item)` line 656 —— 在 for 循环加 elif 分支 |
| R1.2 因子取数 | 涨停池字段 `lbc`(连板) `zbc`(炸板) `hs`(换手) 从 `pool_item`；`broken_duration_min`/`max_drop_pct`/`last_lock_time` 从 `intraday_features.compute_derived_features(snapshots)`（S070 R7 已落地） |
| R3 形态反包注册 | STRATEGY_REGISTRY 加第 11 项 |
| R3.2 K线取数 | **待核实**：`astock.kline()` grep 无匹配，实现阶段核实实际 K线函数名（可能是 `astock.stock_kline` / `data.sources.eastmoney.kline` 等） |
| R5.3 触发价精度 | `limitup_strategy._round_to_tick_size` line 29 + `_validate_limit_up_price` line 34（既有） |
| StrategyMatcher 消费 | `strategies/strategy_matcher.py:36 match()` 包装 `match_strategies`，扩展后自动覆盖，不改 match() |
| snapshots 取数 | `risk.seal_intraday_collector.get_snapshots_by_code(code, date)` —— S070 已实现 |

**新增**：STRATEGY_REGISTRY 2 个注册项 + match_strategies 2 个 elif 分支 + 触发价输出。**不新增**：引擎/路由/前端（S079 已做 P2RiskPanel，S081 战法命中后信号通过既有链路流出）。

---

## 1. 目录结构

```
backend/
├── limitup_strategy.py（修改）
│   ├── STRATEGY_REGISTRY 加 2 项（weak_turn_strong / pattern_reversal）
│   └── match_strategies 加 2 个 elif 分支
├── strategies/
│   └── strategy_matcher.py（不改，match() 自动覆盖）
├── tests/
│   └── test_s081_prd_strategies.py（新增）
```

无前端改动（S079 P2RiskPanel 已展示战法信号）。

---

## 2. 实现步骤

### R1 弱转强接力战法注册 + match 分支

**注册项**（STRATEGY_REGISTRY 加 dict）：
```python
{
    "code": "weak_turn_strong",
    "name": "弱转强接力",
    "entry_type": "次日竞价确认后",
    "stop_loss_pct": -5.0,
    "take_profit_pct": 10.0,
    "max_hold_days": 2,
    "entry_condition": "昨日涨停+炸板≥20min+回撤≥5%+尾盘封死+换手1.8-3.0倍",
    "weather_regimes": ["晴天", "极端反弹"],
    "aliases": ["弱转强", "分歧转一致"],
}
```

**match 分支**（match_strategies for 循环加 elif）：
```python
elif strategy["code"] == "weak_turn_strong":
    # 因子取数
    lbc = pool_item.get("lbc") if pool_item else None  # 连板数
    hs = pool_item.get("hs") if pool_item else None  # 换手率
    # S070 R7 派生（需取 snapshots，实现阶段从 get_snapshots_by_code 取）
    # broken_duration_min / max_drop_pct / last_lock_time 从 compute_derived_features
    # vol_ratio_1d = hs / 前日 hs（需前日数据，标 None 降级 if 取不到）
    # 5 因子硬阈值判定 + 置信度打分
```

**S070 R7 依赖门禁**：snapshots 取不到时（非交易日/数据未采），标 `data_status="missing_s070_r7"` 跳过匹配不报错。

### R3 形态反包战法注册 + match 分支

**注册项**：
```python
{
    "code": "pattern_reversal",
    "name": "形态反包",
    "entry_type": "次日突破昨日最高价确认",
    "stop_loss_pct": -4.0,
    "take_profit_pct": 12.0,
    "max_hold_days": 3,
    "entry_condition": "昨日未封涨停+最高≥7%+上影线≥4%+放量1.2倍+5日线向上",
    "weather_regimes": ["晴天", "阴天"],
    "aliases": ["反包", "长上影洗盘修复"],
}
```

**match 分支**：
- `close_pct` 从 `pool_item.get("zdp")`
- `max_high_pct` / `shadow_length_pct` 从 K线（**待核实函数名**）；K线取不到标 None 降级
- `volume_1d` / `volume_2d` 从 `pool_item.get("fundamt")` + 前日对比
- `ma_5_status` 从 K线 + 均线计算

**不依赖 S070 R7**（因子来自涨停池 + K线，不需分时派生）—— 可先行实现。

### R5 信号输出（触发价）

- 弱转强接力：`entry_price = _round_to_tick_size(昨日涨停价)`；竞价达标额参数附 description
- 形态反包：`entry_price = _round_to_tick_size(昨日K线最高价 + 0.01)`
- 参数标注"参考值，非执行指令"（附 disclaimer 字段）

### R2.1 不修改现有 match_strategies 逻辑

新增 elif 分支加在 for 循环末尾（现有 9 战法 elif 不改），保持单一事实来源。

---

## 3. 验收对齐

| spec AC | plan 实现步骤 | 验证方式 |
|---|---|---|
| AC1 STRATEGY_REGISTRY 加 2 项不破坏 9 个 | R1/R3 注册项 | mock 现有 9 战法匹配不变 |
| AC2 match 扩展输出命中/置信度 | R2/R4 elif 分支 | mock 满足/不满足阈值标的 |
| AC3 弱转强因子从 S070 R7 取 | R1.2 派生取数 | mock snapshots 缺失标"数据层未就绪"跳过 |
| AC4 形态反包因子从涨停池+K线 | R3.2 | mock pool_item + K线 |
| AC5 触发价精度复用 _round_to_tick_size | R5 | 断言 entry_price 精度 |
| AC6 不接券商不下单 | 全 plan | 代码审查无券商 API |
| AC7 轻量风险提醒 | R5 disclaimer | 断言 disclaimer 字段 |
| AC8 阈值探索性 + 验算 | config 可配 | 标注探索性（financial_rigor 待 live） |
| AC9 AC10 放宽继承 S079 §2.3 | — | 文档引用 |
