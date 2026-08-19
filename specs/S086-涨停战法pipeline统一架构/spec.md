# Spec: S086 — 涨停战法 pipeline 统一架构

> 状态：已实现（2026-08-20，commit 见 git log）
> 作者：lzw9560　日期：2026-08-19
> 关联：S066（策略注册表+天气硬开关）/ S072（去天气）/ S081（PRD2 战法）/ S084（选股池战法解耦）
>
> grill 记录：本 spec 经两轮 grill-me 审查（设计决议 5 项 + spec 审查 6 项），用户全部同意。
> 实现记录：见 §10（8 项 spec/prompt 与代码实情偏差的处置）。

## 1. 问题 / 目标

当前涨停战法 pipeline 是**混合态**：一个共享 pipeline + 一个 350 行 monolithic switch dispatch（`match_strategies` 的 if/elif），两套注册表分裂（`STRATEGY_REGISTRY` 11 项 dict + `STRATEGY_FUNNEL_REGISTRY` 10 项 dataclass），三处暴风雨硬开关与 S072"去天气"决议冲突。目标：**统一为共享 pipeline + 可插拔 Strategy 模块，单一注册表，消灭 switch dispatch，移除天气硬开关。**

## 2. 背景

### 2.1 现状（grill 前扫描结论）

| 环节 | 现状 | 问题 |
|---|---|---|
| match 分发 | `limitup_strategy.py:696-1043`，一个函数 350 行 if/elif，10 个战法挤在一起 | 加战法即膨胀；旧 5 战法（简单）与新 2 战法（复杂，读 IndicatorSet/derived）逻辑差异 3-5 倍，但挤在同一函数 |
| 注册表 | `STRATEGY_REGISTRY`（dict，11 项）+ `STRATEGY_FUNNEL_REGISTRY`（dataclass，10 项） | storm_reversal 只在新表，weak_turn_strong/pattern_reversal 只在旧表；`_MATCHED_STRATEGY_CODES` 白名单兜底 |
| 入场价 | 旧 5 战法用 `gene.total_score`（0-100 分数）代理；新 2 战法用 `pool_item.p`（真实涨停价） | **语义错误**：用 75 分当 75 元算止损，对用户误导 |
| 天气开关 | `sentiment_context.py:226-227`（暴风雨只允许 storm_reversal）+ `strategy_funnel_registry.py:448`（非暴风雨跳过 storm_reversal）+ 熔断 triggered | 与 S072"去天气"冲突；grill Q7 保留暴风雨为例外，但本次决议全移除 |
| storm_reversal | 不在 `STRATEGY_REGISTRY`，无 match 分支，"无条件放行" | 无 match 条件是 bug 不是设计——其条件是封板时间≤10:30 |

### 2.2 已有 spec 冲突审查

- **S066**：建立天气硬开关。本 spec **部分废弃** S066 的天气硬开关（保留天气软标注）。S066 的注册表 + 权重集 + 策略分计算保留。
- **S072**：选股链去天气/STI。本 spec **延续** S072，移除暴风雨例外，彻底去天气硬开关。
- **S081**：PRD2 战法（weak_turn_strong/pattern_reversal）。本 spec **保留** S081 的战法逻辑，抽成 Strategy 模块。
- **S084**：选股池战法解耦。本 spec **延续** S084 的解耦方向，`score_candidates` 改为传完整 ctx。

## 3. 需求清单

- [ ] R1：抽 Strategy 协议，每战法一个 `match(ctx) → list[ConditionMatch]` 方法，消灭 `match_strategies` 的 if/elif switch dispatch
- [ ] R2：入场价统一到 `pool_item.p`（真实涨停价），移除 `gene.total_score` 代理；`pool_item` 缺失时 fallback `gene.total_score` + 标注"价格代理"
- [ ] R3：移除三处暴风雨天气硬开关（`sentiment_context.py:226-227` / `strategy_funnel_registry.py:448` / 熔断 triggered），storm_reversal 纳入 `match_strategies`（match 条件=封板时间≤10:30，读 `pool_item["fbt"]`）
- [ ] R4：暴风雨天仓位缩放（0.3）降为建议提示，不做强制
- [ ] R5：两套注册表合并为单一 dataclass（`StrategyFunnelConfig` 超集），每项含参数 + 指向 Strategy 实现；`_MATCHED_STRATEGY_CODES` 白名单删除
- [ ] R6：调度器统一组装 `StrategySignal`（入场价/止损/止盈/历史统计/disclaimer），Strategy 类只返回 `ConditionMatch` + `confidence` + `entry_price`
- [ ] R7：`score_candidates` 增加 `pool_item_map: dict[str, dict] | None` 入参，由调用方传入；调度器用其构造 `StrategyContext.pool_item`
- [ ] R8：`derived` fallback 逻辑上提到调度器（当前在 weak_turn_strong Strategy 内部 20 行），调度器统一准备 `StrategyContext.derived`；T-1 vs 今日的判断由调用方传参决定
- [ ] R9：清掉 `reverse_package` 的 `activation_note="待 S055 激活"`（数据已就绪，标注过时）；清掉 `break_reseal` / `reverse_package` / `n_shape_counterattack` 三个过时 note
- [ ] R10：Strategy 实现按数据依赖维度拆 4 个文件（`gene_based` / `pool_based` / `indicator_based` / `db_based`），不拆 12 个单文件

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/limitup_strategy.py` | `STRATEGY_REGISTRY` 合并到新注册表；`match_strategies` 拆为 12 个 Strategy 类 + 调度器；入场价统一 `pool_item.p` |
| `backend/strategies/strategy_funnel_registry.py` | `STRATEGY_FUNNEL_REGISTRY` 合并；`_MATCHED_STRATEGY_CODES` 删除；line 448 暴风雨硬开关删除；`score_candidates` 传完整 ctx |
| `backend/sentiment_context.py` | line 226-227 暴风雨硬开关删除（全 allowed）；line 239 熔断 triggered 改软标注 |
| `backend/strategies/position_advisor.py` | 暴风雨 `position_scale=0.3` 改建议提示 |
| `backend/strategies/position_advisor_v2.py` | 同上；`_lookup_strategy` 从新注册表读参数 |
| `backend/pre_market_workflow.py` | `pool_item_map` 传入 match 调度器 |
| `backend/intraday_coach.py` | `STRATEGY_REGISTRY` 引用改为新注册表 |
| `backend/prediction_ingest.py` | 同上 |
| `backend/strategies/strategy_backtest.py` | 同上 |
| `backend/strategies/strategy_matcher.py` | 适配新 Strategy 协议 |
| 新增 `backend/strategies/strategy_base.py` | Strategy 协议 + StrategyContext + ConditionMatch + 调度器 dispatch_match + _prepare_derived |
| 新增 `backend/strategies/impl/gene_based.py` | 7 个只读 gene 因子的 Strategy 实现（first_plate/consecutive_relay/break_reseal/end_of_day_sneak/n_shape_counterattack/platform_breakout/dragon_head） |
| 新增 `backend/strategies/impl/pool_based.py` | 1 个读 pool_item 的 Strategy 实现（storm_reversal） |
| 新增 `backend/strategies/impl/indicator_based.py` | 2 个读 IndicatorSet 的 Strategy 实现（weak_turn_strong/pattern_reversal） |
| 新增 `backend/strategies/impl/db_based.py` | 1 个读 seal_intraday.db 的 Strategy 实现（reverse_package） |

## 5. 设计方案

### 5.1 Strategy 协议（strategy_base.py）

```python
@dataclass
class StrategyContext:
    """调度器统一准备的上下文容器，各 Strategy 按需读字段。"""
    code: str
    gene: GeneScore                     # 因子得分（涨停频次/封板率/溢价率/zt_count_250d）
    pool_item: dict | None              # 涨停池原始字段（lbc/zbc/fbt/zdp/hs/p/fund）
    indicators: IndicatorSet | None     # K线派生（max_high_pct/shadow_length_pct/ma_5_status）
    derived: dict | None                # S070 R7 分时派生（broken_duration_min/max_drop_pct/last_lock_time）
    weather_state: str | None          # 天气（软标注，不做硬开关）

@dataclass
class ConditionMatch:
    condition: str
    value: str
    description: str

class StrategyProtocol(Protocol):
    @property
    def code(self) -> str: ...
    @property
    def name(self) -> str: ...
    def match(self, ctx: StrategyContext) -> list[ConditionMatch]: ...
    def compute_confidence(self, matches: list[ConditionMatch], ctx: StrategyContext) -> float: ...
    def compute_entry_price(self, ctx: StrategyContext) -> float:
        """默认返回 pool_item.p（R2 锁定）；需特殊触发价可 override。"""
        ...
```

#### 调度器统一准备 derived（R8）

当前 `weak_turn_strong` 的 derived fallback（`limitup_strategy.py:833-851`，20 行）在 Strategy 内部调 `get_snapshots_by_code` + `compute_derived_features`。上提到调度器：

```python
# 调度器统一准备 derived
def _prepare_derived(card_derived: dict | None, code: str) -> dict | None:
    """调度器统一准备 derived，T-1 vs 今日由调用方传参决定。"""
    if card_derived is not None:
        return card_derived  # 调用方传了 T-1 值
    # fallback：取今日 snapshots
    try:
        from risk.seal_intraday_collector import get_snapshots_by_code
        from strategies.intraday_features import compute_derived_features
        from datetime import datetime as _dt
        _snaps = get_snapshots_by_code(code, _dt.now().strftime("%Y-%m-%d"))
        if not _snaps:
            return None
        derived = compute_derived_features(_snaps)
        return None if derived.get("data_status") == "missing" else derived
    except Exception:
        return None
```

Strategy 类只读 `ctx.derived`，不再自己取数。

### 5.2 单一注册表（合并 STRATEGY_REGISTRY + STRATEGY_FUNNEL_REGISTRY）

```python
@dataclass
class StrategyConfig:
    """单一注册表项：参数 + 指向 Strategy 实现。"""
    code: str
    name: str
    strategy_impl: StrategyProtocol      # 指向 Strategy 实现
    # 仓位参数
    stop_loss_pct: float
    take_profit_pct: float
    max_hold_days: int
    position_scale: float = 1.0          # 仓位缩放（建议，不强制）
    # 漏斗参数
    funnel_type: str = "limitup"
    weight_set: str = "limitup"
    weather_regimes: list[str] = field(default_factory=list)  # 软标注
    is_primary: bool = True
    fallback: bool = False
    activation_note: str | None = None   # 非空=当前不可用
    # 文本
    entry_type: str = ""
    entry_condition: str = ""
    stop_loss_condition: str = ""
    take_profit_condition: str = ""
    exit_condition: str = ""
    note: str = ""
    aliases: list[str] = field(default_factory=list)
    quality_standards: list[QualityCheck] = field(default_factory=list)

STRATEGY_REGISTRY: list[StrategyConfig] = [...]  # 12 项（含 storm_reversal）
```

### 5.3 调度器（strategy_base.py）

```python
def dispatch_match(ctx: StrategyContext, registry: list[StrategyConfig]) -> list[StrategySignal]:
    """调度器：遍历注册表，各 Strategy.match → 组装 StrategySignal。"""
    signals = []
    for cfg in registry:
        impl = cfg.strategy_impl
        matches = impl.match(ctx)
        if not matches:
            continue
        confidence = impl.compute_confidence(matches, ctx)
        if confidence == 0.0:
            continue
        entry_price = impl.compute_entry_price(ctx)
        # 调度器统一组装（止损/止盈/历史统计/disclaimer）
        stop_loss = round(entry_price * (1 + cfg.stop_loss_pct / 100), 2)
        take_profit = round(entry_price * (1 + cfg.take_profit_pct / 100), 2)
        historical_win_rate = min(confidence * 0.8 + 0.2, 0.95)
        historical_avg_return = round((cfg.take_profit_pct - cfg.stop_loss_pct) / 2 * historical_win_rate, 2)
        signals.append(StrategySignal(
            code=ctx.code, name=ctx.gene.name,
            strategy_name=cfg.name, strategy_code=cfg.code,
            score=ctx.gene.total_score,
            signal_strength=int(confidence * 100),
            confidence=round(confidence, 2),
            matches=matches,
            entry_price=entry_price,
            stop_loss=stop_loss, take_profit=take_profit,
            # ... 其余字段统一填
        ))
    signals.sort(key=lambda s: s.risk_reward_ratio * s.historical_win_rate, reverse=True)
    return signals
```

### 5.4 各 Strategy 实现（strategies/impl/）

按**数据依赖维度**拆 4 个文件，同组战法读同一组数据源：

| 文件 | 拆分原则 | 战法 | 共性 |
|---|---|---|---|
| `impl/gene_based.py` | 只读 gene 因子，不读任何外部数据源 | first_plate / consecutive_relay / break_reseal / end_of_day_sneak / n_shape_counterattack / platform_breakout / dragon_head | 7 个，match 逻辑各 3-8 行，条件全来自 GeneScore |
| `impl/pool_based.py` | 读 pool_item 涨停池原始字段 | storm_reversal（fbt 封板时间） | 1 个，条件来自涨停池 raw dict |
| `impl/indicator_based.py` | 读 IndicatorSet K线派生因子，需漏斗 R2 产出 | weak_turn_strong / pattern_reversal | 2 个，5 因子硬阈值，依赖 K线扩展 |
| `impl/db_based.py` | 读私有数据库（seal_intraday.db） | reverse_package | 1 个，条件来自分时快照 DB |

拆分原则：按 StrategyContext 的数据依赖维度分组，同组战法读同一组数据源。

理由：
1. 可测试性——同组战法共享 fixture（gene_based 只需 mock GeneScore；indicator_based 需 mock IndicatorSet + pool_item）
2. 可演进——新增战法时按数据依赖归入对应文件
3. 避免循环依赖——db_based 的 reverse_package 依赖 sqlite + config，和 gene_based 纯因子计算无关
4. 文件不过碎——4 个文件，gene_based 7 个类（各 3-8 行合理），其他各 1-2 个类

各战法 match 条件 + confidence：

| 战法 | 文件 | match 条件 | confidence |
|---|---|---|---|
| first_plate | `impl/first_plate.py` | score≥60 ∧ 涨停频次>20 | 动态 score/100 |
| consecutive_relay | `impl/consecutive_relay.py` | zt≥2 ∧ 封板率≥60% | 动态 封板率/100 |
| break_reseal | `impl/break_reseal.py` | 3≤zt≤5 ∧ 封板率≥80% | 固定 0.7 |
| low_absorption | `impl/low_absorption.py` | score≥65 ∧ 溢价率>50% | 固定 0.5 |
| reverse_package | `impl/reverse_package.py` | 炸板池 open_count≥2 | 固定 0.4 |
| n_shape_counterattack | `impl/n_shape_counterattack.py` | 2≤zt≤10 | 固定 0.5 |
| platform_breakout | `impl/platform_breakout.py` | score≥60 ∧ 涨停频次>40 | 固定 0.5 |
| end_of_day_sneak | `impl/end_of_day_sneak.py` | 封板率≥40% ∧ 溢价率>40% | 固定 0.4 |
| dragon_head | `impl/dragon_head.py` | 无 match 分支（无条件放行） | 固定 0.5 |
| storm_reversal | `impl/storm_reversal.py` | 封板时间≤10:30（`pool_item["fbt"]`≤103000） | 固定 0.7 |
| weak_turn_strong | `impl/weak_turn_strong.py` | 5 因子硬阈值（lbc/broken/drop/lock/vol_ratio）≥4 命中 | 1.0/0.7 |
| pattern_reversal | `impl/pattern_reversal.py` | 5 因子硬阈值（close/high/shadow/vol/ma5）≥4 命中 | 1.0/0.7 |

### 5.5 暴风雨硬开关移除

| 位置 | 现状 | 改为 |
|---|---|---|
| `sentiment_context.py:226-227` | `if 暴风雨: return ["storm_reversal"], [其余 forbidden]` | 删除，全 allowed |
| `strategy_funnel_registry.py:448` | `if storm_reversal and weather != 暴风雨: continue` | 删除 |
| `sentiment_context.py:239` | `r1_triggered = weather == 暴风雨` | 改软标注（fuse_state 标 "建议降仓"，不阻断） |
| `position_advisor.py` | `position_scale=0.3` 强制 | 改建议提示（`position_advice_note: "暴风雨天建议仓位×0.3"`） |

### 5.6 入场价统一

`match_strategies` 的 line 988-990 删除（`gene.total_score` 代理），调度器统一调 `impl.compute_entry_price(ctx)`，默认返回 `pool_item.p`。`pattern_reversal` override 返回 `pool_item.p + 0.01`。

### 5.7 取舍

- **不选独立 pipeline**：候选池/诊断/结算三环统一（grill 确认），独立 pipeline 重复造轮子
- **不选保留 switch dispatch**：350 行函数 + 注册表分裂 + 白名单兜底，维护成本随战法数线性增长
- **match 只返回 ConditionMatch**：Strategy 类不管信号组装，避免 12 份重复的止损/止盈/disclaimer 代码
- **天气不做硬开关**：S072 去天气决议的延续，暴风雨例外移除（用户确认）

## 6. 验收标准

- [ ] A1：`match_strategies` 函数删除，替换为 `dispatch_match(ctx, registry)`
- [ ] A2：`STRATEGY_REGISTRY` 和 `STRATEGY_FUNNEL_REGISTRY` 合并为单一 `STRATEGY_REGISTRY: list[StrategyConfig]`，12 项（含 storm_reversal）
- [ ] A3：`_MATCHED_STRATEGY_CODES` 白名单删除
- [ ] A4：`sentiment_context.py` 暴风雨硬开关移除，全天气 allowed
- [ ] A5：`strategy_funnel_registry.py:448` 暴风雨守卫删除
- [ ] A6：暴风雨仓位缩放降为建议提示（PositionAdvisor 层不强制）
- [ ] A7：入场价全部用 `pool_item.p`（`gene.total_score` 代理删除）；`pool_item` 缺失时 fallback `gene.total_score` + 标注"价格代理"
- [ ] A8：`score_candidates` 增加 `pool_item_map` 入参，调度器用其构造 `StrategyContext.pool_item`
- [ ] A9：storm_reversal 有 match 分支（封板时间≤10:30，读 `pool_item["fbt"]`）
- [ ] A10：`derived` fallback 上提到调度器（`_prepare_derived`），Strategy 类不再自己取数
- [ ] A11：`reverse_package` 的 `activation_note` 清除（数据已就绪，标注过时）
- [ ] A12：`break_reseal` / `reverse_package` / `n_shape_counterattack` 三个过时 note 清除
- [ ] A13：Strategy 实现按数据依赖拆 4 个文件（`gene_based` / `pool_based` / `indicator_based` / `db_based`）
- [ ] A14：既有测试全绿（`test_s053` / `test_s062` / `test_s081` / `test_s084` / `test_strategy_funnel_registry`）
- [ ] A15：新增测试：`dispatch_match` 调度器单测 + 各 Strategy 实现 match 单测 + `_prepare_derived` 单测

## 7. 合规与工程底线自查

- [ ] 研判/推荐/买卖时机属系统能力（2026-07-30 新口径）；用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」
- [ ] 判断可复现：涉及数据的跑验算，禁臆造/心算
- [ ] 涨停四池/连板股榜个股属公开榜单客观事实；聚合指标 vs 客观榜单分层仅作推荐，非硬约束
- [ ] 用户私有数据（持仓/研报/key）未进 git、未上传
- [ ] 新增东财端点走 `em_get()` 限流（本 spec 不新增端点）

## 8. 测试计划

- [ ] `pytest backend/tests/test_s053_rebound_factor.py`（break_reseal 条件）
- [ ] `pytest backend/tests/test_s062_strategy_card_content.py`（dragon_head 注册表 schema）
- [ ] `pytest backend/tests/test_s081_prd_strategies.py`（weak_turn_strong / pattern_reversal）
- [ ] `pytest backend/tests/test_s084_match_card.py`（match card 传递）
- [ ] `pytest backend/tests/test_strategy_funnel_registry.py`（注册表 + 天气推荐）
- [ ] `pytest backend/tests/test_s031_strategy_backtest.py`（回测，8→12 战法断言更新）
- [ ] 新增 `pytest backend/tests/test_s086_dispatch.py`（调度器 + 各 Strategy 实现）

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 12 个 Strategy 文件改动面大 | 中 | 分批迁移：旧 5 战法 → S081 2 战法 → storm_reversal → dragon_head，每批跑测试 |
| `pool_item.p` 可能缺失（非涨停池路径） | 中 | `compute_entry_price` fallback：`pool_item.p` 缺失时返回 `gene.total_score` + 标注"价格代理" |
| 暴风雨硬开关移除后，storm_reversal 在非暴风雨天也跑 | 低 | storm_reversal 的 match 条件（封板≤10:30）自然过滤大部分候选；仓位建议提示保留 |
| 既有测试断言更新（8→12 战法） | 低 | 测试文件逐个更新 |
| `STRATEGY_REGISTRY` 引用方多（7 文件） | 中 | 保留 `from limitup_strategy import STRATEGY_REGISTRY` 导出路径，内部改为新注册表 |

回滚：git revert，无数据迁移（纯代码重构）。

## 10. 实现记录（2026-08-20）

实现期核实发现 spec/implementation-prompt 与代码实情 8 项偏差，处置如下（均经独立判断，决议可从 spec 自身验收标准复现）：

1. **low_absorption 遗漏**（CRITICAL）：implementation-prompt B1 列 7 个 gene_based 战法，遗漏 low_absorption。但 low_absorption 在旧 dict STRATEGY_REGISTRY（:546）+ 旧 STRATEGY_FUNNEL_REGISTRY（:204）均有注册且有 match 分支（:754-761）；A2 要求"12 项"。**处置**：gene_based.py 含 8 个战法（含 LowAbsorptionStrategy），"7 个"为 off-by-one 笔误。
2. **B5.3 兼容导出签名不匹配**（CRITICAL）：`dispatch_match(ctx, registry)` ≠ `match_strategies(code, gene, pool_item, indicators, card)`，裸 re-export 破坏 ~15 调用方 + 测试。**处置**：strategy_base 提供 `match_strategies` 真兼容包装（建 ctx → dispatch_match），limitup_strategy re-export 之，签名不变。
3. **C9 文件标错**（MEDIUM）：pre_market_workflow 用 StrategyMatcher.match（已传 pool_item），不调 score_candidates；真调用方是 routers/workflow.py:167 + forward_test.py:475（无 pool_item 数据）。**处置**：score_candidates 加可选 `pool_item_map=None`（C8）；pre_market 无需改（已透传）；不往 routers/workflow 新接 fetch_zt_pool（超 spec 范围，A7 fallback 兜底）。
4. **position_advisor 0.3 位置**（MEDIUM）：§5.5 称 position_advisor.py `position_scale=0.3 强制`，实情是 `return None` 硬阻断（0.3 在 funnel storm_reversal PositionParams）。**处置**：`return None` → 软 0.3 cap + advice note（R4）；storm_reversal.position_scale=0.3 作建议参数保留。
5. **dict 访问消费方远超 §4 所列**（MEDIUM）：routers/strategy.py:84、ai/tools/strategy_tools.py、sentiment_context.py:223 + 5 测试文件做 `s["code"]`/`s.get(...)`；test_advisory/test_s085 monkeypatch 纯 dict mock。**处置**：StrategyConfig 为 dataclass **同时支持 dict 访问**（`__getitem__`/`get`/`__contains__`/`keys` + `position_params` property），令所有 dict 消费方 + dict mock 零改动；消费方（prediction_ingest/intraday_coach/routers/strategy/ai/tools/strategy_backtest/strategy_matcher/position_advisor_v2）均不改。
6. **dragon_head 无条件放行改变 backtest 行为**（MEDIUM）：旧 match_strategies 无 dragon_head 分支（backtest sample_size=0）；B1.7 使其无条件命中 → backtest 命中（sample_size>0），破 test_s031:52-53。§2.1 称无分支状态"是 bug 不是设计"。**处置**：从 B1.7（无条件放行）；test_s031 断言更新（E9 授权）。副作用：live match_strategies 现为每候选出 dragon_head 信号（spec 设计的 catch-all）。
7. **storm_reversal.md 卡片缺失**（LOW）：test_s062:115-122 + test_s058:94-101 要求每注册表项有卡片。**处置**：新建 strategies/cards/storm_reversal.md。
8. **测试断言更新**（§9 + E8/E9 授权）：test_s081:51 11→12；test_strategy_funnel_registry:90 10→12 + storm 全 allowed + storm_reversal fbt 驱动；test_s031:46 11→12 + dragon_head 排除；test_s081_strategy_matcher_pool_item:300-307 排除 storm_reversal；另 test_s063 storm_blocks_opening→soft_cap（R4）、test_non_limitup_funnel storm→允许非涨停类（R3）。

**对抗审计**（3 并行 agent）：阈值/字符串迁移逐条核对 git HEAD limitup_strategy.py:725-962——10 战法条件/阈值/confidence/ConditionMatch 文本 EXACT 保留，无 drift；消费方兼容成立（165 相关测试通过）；A1-A15 验收 PASS。2 项 low 修已落地（first_plate/consecutive_relay weather_regimes 去多余"未知"恢复旧 calc_weather_fit 行为；weak_turn_strong 不再造永不输出的"missing_s070_r7" ConditionMatch——行为不变，设计更简洁）。2 项 medium（_strat_params/_strategy_meta 注解 `->dict` 不实）已改 `-> Any`。

**已知遗留**（非 S086 回归）：test_s040_backfill::test_run_backtest_async_passes_kline_cache 全量套件偶发失败（孤立运行通过；backtest_lite 不 import 任何 S086 模块，隔离于本 spec），为既有 ordering/pollution flake。
