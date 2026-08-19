# 实现提示词 · S086 涨停战法 pipeline 统一架构

> 直接贴给新 Claude session 执行。spec/plan/tasks 在 `specs/S086-涨停战法pipeline统一架构/`。

---

## 任务

实现 S086 涨停战法 pipeline 统一架构。先读 `specs/S086-涨停战法pipeline统一架构/` 下的 spec.md + plan.md + tasks.md。

## 执行顺序（严格按依赖）

### 阶段 A · 基础设施（strategy_base.py）

建 `backend/strategies/strategy_base.py`：
- `StrategyContext` dataclass（code/gene/pool_item/indicators/derived/weather_state）
- `ConditionMatch` dataclass（condition/value/description）
- `StrategyProtocol`（code/name 属性 + match/compute_confidence/compute_entry_price 方法）
- `StrategyConfig` dataclass（参数 + strategy_impl 指向 Strategy 实现）
- `dispatch_match(ctx, registry) → list[StrategySignal]` 调度器
- `_prepare_derived(card_derived, code) → dict | None`（derived fallback 上提）
- `_prepare_pool_item(pool_item_map, code) → dict | None`

不动既有代码，只新建。完成后 `import strategies.strategy_base` 无报错。

### 阶段 B1-B4 · 战法迁移（4 文件，可并行）

**B1 `strategies/impl/gene_based.py`**（7 个简单战法）：
- `FirstPlateStrategy`：match=score≥60 ∧ 涨停频次>20，confidence=动态 score/100
- `ConsecutiveRelayStrategy`：match=zt≥2 ∧ 封板率≥60%，confidence=动态 封板率/100
- `BreakResealStrategy`：match=3≤zt≤5 ∧ 封板率≥80%，confidence=固定 0.7
- `EndOfDaySneakStrategy`：match=封板率≥40% ∧ 溢价率>40%，confidence=固定 0.4
- `NShapeCounterattackStrategy`：match=2≤zt≤10，confidence=固定 0.5
- `PlatformBreakoutStrategy`：match=score≥60 ∧ 涨停频次>40，confidence=固定 0.5
- `DragonHeadStrategy`：无条件放行，confidence=固定 0.5

各 match 逻辑从 `limitup_strategy.py:725-816` 迁移，不改阈值。

**B2 `strategies/impl/pool_based.py`**（storm_reversal）：
- `StormReversalStrategy`：match=pool_item["fbt"]≤103000（封板≤10:30），confidence=固定 0.7

**B3 `strategies/impl/indicator_based.py`**（2 个复杂战法）：
- `WeakTurnStrongStrategy`：5 因子硬阈值（lbc/broken/drop/lock/vol_ratio）≥4 命中，confidence=1.0/0.7；**derived 不上提取数**（调度器 _prepare_derived 已做），只读 ctx.derived
- `PatternReversalStrategy`：5 因子硬阈值（close/high/shadow/vol/ma5）≥4 命中，confidence=1.0/0.7；override compute_entry_price 返回 pool_item.p+0.01

从 `limitup_strategy.py:822-962` 迁移。

**B4 `strategies/impl/db_based.py`**（reverse_package）：
- `ReversePackageStrategy`：match=seal_intraday.db open_count≥2 的票包含 gene.code，confidence=固定 0.4

从 `limitup_strategy.py:763-787` 迁移。

### 阶段 B5 · 注册表合并

- `strategy_funnel_registry.py`：合并 `STRATEGY_FUNNEL_REGISTRY` + `STRATEGY_REGISTRY` 为单一 `list[StrategyConfig]` 12 项
- 删除 `_MATCHED_STRATEGY_CODES` 白名单
- `limitup_strategy.py`：删旧 `match_strategies` + 旧 `STRATEGY_REGISTRY`（dict 版）；加兼容导出：
  - `from strategies.strategy_base import dispatch_match as match_strategies`
  - `from strategies.strategy_funnel_registry import STRATEGY_REGISTRY`
- `strategies/impl/__init__.py`：导出 12 个 Strategy 实现

### 阶段 C · 硬开关移除 + 入场价统一

- 删 `sentiment_context.py:226-227` 暴风雨硬开关（改全 allowed）
- 删 `strategy_funnel_registry.py:448` 暴风雨守卫
- `sentiment_context.py:239` 熔断改软标注（不阻断）
- `position_advisor.py` + `position_advisor_v2.py`：暴风雨仓位×0.3 改建议提示
- `dispatch_match` 入场价默认 `pool_item.p`（缺失 fallback gene.total_score+标注"价格代理"）
- `pattern_reversal` override 返回 p+0.01
- `score_candidates` 加 `pool_item_map: dict[str, dict] | None = None` 入参
- `pre_market_workflow.py` 调 score_candidates 时传入 pool_item_map

### 阶段 D · 清理过时标注

- 清 reverse_package 的 `activation_note="待 S055 激活"`
- 清 break_reseal 的 note "60日无信号：炸板后溢价因子疑似缺供"
- 清 reverse_package 的 note "60日无信号：match 逻辑依赖「炸板后溢价」因子缺供"
- 清 n_shape_counterattack 的 note "60日无信号：条件定义待重定义"

### 阶段 E · 测试

- 新增 `tests/test_s086_dispatch.py`：调度器单测 + _prepare_derived 单测
- 新增 `tests/test_s086_strategy_impl.py`：12 个 Strategy match 单测
- 既有测试全绿：test_s053 / test_s062 / test_s081 / test_s084 / test_strategy_funnel_registry / test_s031_strategy_backtest

## 硬约束

- **向后兼容**：`from limitup_strategy import STRATEGY_REGISTRY, match_strategies` 导出路径必须保留（7 个文件引用）
- **每阶段完成即跑测试**：`pytest backend/tests/ -k "s086 or s053 or s062 or s081 or s084 or strategy_funnel or s031_strategy" -m "not live"`
- **不臆造**：match 条件/阈值/confidence 严格按 limitup_strategy.py 既有分支迁移，不改阈值
- **提交纪律**：每阶段一个 commit（`wip(S086): 阶段X`），全绿后 squash 为 `feat(S086): 涨停战法pipeline统一架构`
- **语言**：commit message 中文，代码英文

## 关键代码事实

- `match_strategies` 在 `limitup_strategy.py:696-1043`（350 行 if/elif）
- 旧 STRATEGY_REGISTRY 在 `limitup_strategy.py:501-671`（11 项 dict）
- 旧 STRATEGY_FUNNEL_REGISTRY 在 `strategy_funnel_registry.py:130-276`（10 项 dataclass）
- `_MATCHED_STRATEGY_CODES` 白名单在 `strategy_funnel_registry.py:425-429`
- 暴风雨硬开关三处：`sentiment_context.py:226-227` + `strategy_funnel_registry.py:448` + `sentiment_context.py:239`
- weak_turn_strong 的 derived fallback 在 `limitup_strategy.py:833-851`（上提到调度器 _prepare_derived）
- pool_item 字段：c/n/lbc/zbc/fbt/zdp/hs/p/fund（p=涨停价，fbt=首封时间数字 92500-145000）
- StrategySignal 在 `limitup_strategy.py` 定义，调度器组装时复用
- GeneScore 在 `limitup_screener/models.py` 定义
- IndicatorSet 在 `candidate_funnel/models.py` 定义

开始，从阶段 A。
