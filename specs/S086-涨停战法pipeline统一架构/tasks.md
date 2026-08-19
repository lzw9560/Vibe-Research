# 任务拆分 · S086 涨停战法 pipeline 统一架构

> 对应 spec.md + plan.md（分阶段 A/B/C/D/E）
> 规则：每阶段完成即跑单测；不臆造；向后兼容（保留 `from limitup_strategy import STRATEGY_REGISTRY, match_strategies` 导出路径）。

---

## 阶段 A · 基础设施（strategy_base.py）

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| A1 | 定义 `StrategyContext` dataclass（code/gene/pool_item/indicators/derived/weather_state） | strategies/strategy_base.py | import 无报错 |
| A2 | 定义 `ConditionMatch` dataclass（condition/value/description） | strategies/strategy_base.py | import 无报错 |
| A3 | 定义 `StrategyProtocol`（code/name 属性 + match/compute_confidence/compute_entry_price 方法） | strategies/strategy_base.py | import 无报错 |
| A4 | 定义 `StrategyConfig` dataclass（参数 + strategy_impl 指向 Strategy 实现） | strategies/strategy_base.py | import 无报错 |
| A5 | 实现 `dispatch_match(ctx, registry) → list[StrategySignal]` 调度器 | strategies/strategy_base.py | 空注册表 → 空列表；mock ctx + 1 Strategy → 预期 Signal |
| A6 | 实现 `_prepare_derived(card_derived, code) → dict | None`（derived fallback 上提） | strategies/strategy_base.py | card_derived 非空 → 直接返回；None → fallback snapshots |
| A7 | 实现 `_prepare_pool_item(pool_item_map, code) → dict | None` | strategies/strategy_base.py | map 有 code → 返回 dict；无 → None |

---

## 阶段 B · 战法迁移 + 注册表合并

### B1：gene_based.py（7 个简单战法）

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| B1.1 | `FirstPlateStrategy`：match=score≥60 ∧ 涨停频次>20，confidence=动态 score/100 | strategies/impl/gene_based.py | mock gene → 预期 ConditionMatch |
| B1.2 | `ConsecutiveRelayStrategy`：match=zt≥2 ∧ 封板率≥60%，confidence=动态 封板率/100 | strategies/impl/gene_based.py | mock gene → 预期 ConditionMatch |
| B1.3 | `BreakResealStrategy`：match=3≤zt≤5 ∧ 封板率≥80%，confidence=固定 0.7 | strategies/impl/gene_based.py | mock gene → 预期 ConditionMatch |
| B1.4 | `EndOfDaySneakStrategy`：match=封板率≥40% ∧ 溢价率>40%，confidence=固定 0.4 | strategies/impl/gene_based.py | mock gene → 预期 ConditionMatch |
| B1.5 | `NShapeCounterattackStrategy`：match=2≤zt≤10，confidence=固定 0.5 | strategies/impl/gene_based.py | mock gene → 预期 ConditionMatch |
| B1.6 | `PlatformBreakoutStrategy`：match=score≥60 ∧ 涨停频次>40，confidence=固定 0.5 | strategies/impl/gene_based.py | mock gene → 预期 ConditionMatch |
| B1.7 | `DragonHeadStrategy`：无条件放行（match 返回单条"无条件"+ confidence=0.5） | strategies/impl/gene_based.py | mock gene → 预期 ConditionMatch |

### B2：pool_based.py（storm_reversal）

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| B2.1 | `StormReversalStrategy`：match=pool_item["fbt"]≤103000（封板≤10:30），confidence=固定 0.7 | strategies/impl/pool_based.py | mock pool_item fbt=93000 → 命中；fbt=140000 → 不命中 |

### B3：indicator_based.py（2 个复杂战法）

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| B3.1 | `WeakTurnStrongStrategy`：5 因子硬阈值（lbc/broken/drop/lock/vol_ratio）≥4 命中，confidence=1.0/0.7；derived 从 ctx 读（不上提取数） | strategies/impl/indicator_based.py | mock ctx 5 因子全命中 → confidence=1.0；3 命中 → 不输出 |
| B3.2 | `PatternReversalStrategy`：5 因子硬阈值（close/high/shadow/vol/ma5）≥4 命中，confidence=1.0/0.7；override compute_entry_price 返回 pool_item.p+0.01 | strategies/impl/indicator_based.py | mock ctx 5 因子全命中 → confidence=1.0；entry_price=p+0.01 |

### B4：db_based.py（reverse_package）

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| B4.1 | `ReversePackageStrategy`：match=seal_intraday.db open_count≥2 的票包含 gene.code，confidence=固定 0.4 | strategies/impl/db_based.py | mock db 有 code → 命中；无 → 不命中 |

### B5：注册表合并

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| B5.1 | 合并两套注册表为单一 `STRATEGY_REGISTRY: list[StrategyConfig]`，12 项（含 storm_reversal） | strategies/strategy_funnel_registry.py | len==12；storm_reversal 在内 |
| B5.2 | 删除 `_MATCHED_STRATEGY_CODES` 白名单 | strategies/strategy_funnel_registry.py | grep 无 _MATCHED_STRATEGY_CODES |
| B5.3 | 删除 limitup_strategy.py 旧 `match_strategies`；加 `from strategies.strategy_base import dispatch_match as match_strategies` 兼容导出 | limitup_strategy.py | `from limitup_strategy import match_strategies` 仍可用 |
| B5.4 | 删除 limitup_strategy.py 旧 `STRATEGY_REGISTRY`（dict 版）；加 `from strategies.strategy_funnel_registry import STRATEGY_REGISTRY` 兼容导出 | limitup_strategy.py | `from limitup_strategy import STRATEGY_REGISTRY` 仍可用 |
| B5.5 | impl/__init__.py 导出所有 12 个 Strategy 实现 | strategies/impl/__init__.py | `from strategies.impl import FirstPlateStrategy` 可用 |

---

## 阶段 C · 硬开关移除 + 入场价统一

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| C1 | 删除 sentiment_context.py:226-227 暴风雨硬开关（`if 暴风雨: return ["storm_reversal"], [其余 forbidden]`→全 allowed） | sentiment_context.py | 暴风雨天 allowed_styles 含全部 12 项 |
| C2 | 删除 strategy_funnel_registry.py:448 暴风雨守卫（`if storm_reversal and weather!=暴风雨: continue`） | strategies/strategy_funnel_registry.py | grep 无此行 |
| C3 | sentiment_context.py:239 熔断改软标注（`r1_triggered` 不再阻断，标"建议降仓"） | sentiment_context.py | fuse_state 标建议，不阻断 |
| C4 | position_advisor.py 暴风雨 position_scale=0.3 改建议提示 | strategies/position_advisor.py | 仓位不强制×0.3，标 advice_note |
| C5 | position_advisor_v2.py 同 C4；_lookup_strategy 从新注册表读参数 | strategies/position_advisor_v2.py | 同 C4 |
| C6 | dispatch_match 的 compute_entry_price 默认返回 pool_item.p；缺失时 fallback gene.total_score + 标注"价格代理" | strategies/strategy_base.py | mock pool_item.p=10 → entry_price=10；无 pool_item → fallback score |
| C7 | pattern_reversal override compute_entry_price 返回 pool_item.p+0.01 | strategies/impl/indicator_based.py | mock p=10 → entry_price=10.01 |
| C8 | score_candidates 增加 pool_item_map 入参；调用 dispatch_match 时传完整 ctx | strategies/strategy_funnel_registry.py | score_candidates(candidates, weather, date, pool_item_map={...}) 可用 |
| C9 | pre_market_workflow.py 调 score_candidates 时传入 pool_item_map | pre_market_workflow.py | pool_item_map 透传 |

---

## 阶段 D · 清理过时标注

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| D1 | 清除 reverse_package 的 activation_note="待 S055 激活" | strategies/strategy_funnel_registry.py | activation_note is None |
| D2 | 清除 break_reseal 的 note "60日无信号：炸板后溢价因子疑似缺供" | strategies/strategy_funnel_registry.py | note 不含此句 |
| D3 | 清除 reverse_package 的 note "60日无信号：match 逻辑依赖「炸板后溢价」因子缺供" | strategies/strategy_funnel_registry.py | note 不含此句 |
| D4 | 清除 n_shape_counterattack 的 note "60日无信号：条件定义待重定义" | strategies/strategy_funnel_registry.py | note 不含此句 |

---

## 阶段 E · 测试

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| E1 | 调度器单测：空注册表→空列表；mock ctx+12 Strategy→预期 ConditionMatch | tests/test_s086_dispatch.py | 全绿 |
| E2 | _prepare_derived 单测：card_derived 非空→直接返回；None→fallback；异常→None | tests/test_s086_dispatch.py | 全绿 |
| E3 | 各 Strategy match 单测：12 个实现各覆盖命中/不命中 | tests/test_s086_strategy_impl.py | 全绿 |
| E4 | 既有测试 test_s053_rebound_factor.py 跑通 | — | 全绿 |
| E5 | 既有测试 test_s062_strategy_card_content.py 跑通（适配新 dataclass） | tests/test_s062_strategy_card_content.py | 全绿 |
| E6 | 既有测试 test_s081_prd_strategies.py 跑通 | — | 全绿 |
| E7 | 既有测试 test_s084_match_card.py 跑通 | — | 全绿 |
| E8 | 既有测试 test_strategy_funnel_registry.py 跑通（12 项，暴风雨不再 forbidden） | tests/test_strategy_funnel_registry.py | 全绿 |
| E9 | 既有测试 test_s031_strategy_backtest.py 跑通（8→12 战法断言更新） | tests/test_s031_strategy_backtest.py | 全绿 |

---

## 依赖顺序

```
A（基础设施）→ B1+B2+B3+B4（战法迁移）→ B5（注册表合并）→ C（硬开关+入场价）→ D（清理标注）→ E（测试）
```

B1-B4 可并行（4 个文件独立），B5 依赖 B1-B4 全完成。C 依赖 B5。D 依赖 B5。E 依赖 A-D 全完成。
