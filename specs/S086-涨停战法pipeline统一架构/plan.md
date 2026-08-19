# 技术方案 · S086 涨停战法 pipeline 统一架构

> 对应 spec.md（2026-08-19，两轮 grill 锁定 10 项需求）
> 分阶段：A 基础设施 → B 战法迁移 → C 硬开关移除 → D 清理过时标注 → E 测试

---

## 0. 依据与复用清单

| spec 需求 | 复用的现有能力 | 代码事实 |
|---|---|---|
| R1 抽 Strategy 协议 | `match_strategies` 的 if/elif 各分支已有完整逻辑 | limitup_strategy.py:720-962，10 个分支逐个迁移 |
| R2 入场价统一 | `pool_item.p` 已是涨停价（S081 两个战法已用） | limitup_strategy.py:973-987，pattern_reversal 已有 `pool_item.p+0.01` override |
| R3 暴风雨硬开关移除 | grill Q7 已降级为软标注（非暴风雨全 allowed） | sentiment_context.py:214-230，只剩暴风雨例外 |
| R5 注册表合并 | `StrategyFunnelConfig` 是 dict 超集 | strategy_funnel_registry.py:130-276，dataclass 已含大部分字段 |
| R7 pool_item_map 传入 | pre_market_workflow.py:152 已构建 pool_item_map | score_candidates:439 没传 pool_item，需补 |
| R8 derived fallback 上提 | weak_turn_strong 的 20 行 fallback 已有 | limitup_strategy.py:833-851，移到调度器 |
| R9 清过时标注 | S053 已修完（commit 907b5d1 + 7fdf88b） | 3 个 note + 1 个 activation_note 过时 |

---

## 1. 目录结构

### 1.1 新增文件
```
backend/strategies/
├── strategy_base.py              # 【新】Strategy 协议 + StrategyContext + ConditionMatch + dispatch_match 调度器 + _prepare_derived
└── impl/
    ├── __init__.py               # 【新】导出所有 Strategy 实现
    ├── gene_based.py             # 【新】7 个只读 gene 因子的 Strategy（first_plate/consecutive_relay/break_reseal/end_of_day_sneak/n_shape_counterattack/platform_breakout/dragon_head）
    ├── pool_based.py             # 【新】1 个读 pool_item 的 Strategy（storm_reversal）
    ├── indicator_based.py        # 【新】2 个读 IndicatorSet 的 Strategy（weak_turn_strong/pattern_reversal）
    └── db_based.py               # 【新】1 个读 seal_intraday.db 的 Strategy（reverse_package）
```

### 1.2 改动文件
```
backend/
├── limitup_strategy.py           # 【改】STRATEGY_REGISTRY 合并；match_strategies 删除（改为 re-export dispatch_match 兼容）；入场价统一 pool_item.p
├── strategies/
│   ├── strategy_funnel_registry.py  # 【改】STRATEGY_FUNNEL_REGISTRY 合并到单一注册表；_MATCHED_STRATEGY_CODES 删除；line 448 暴风雨守卫删除；score_candidates 增加 pool_item_map 入参
│   ├── strategy_matcher.py          # 【改】适配新 Strategy 协议（内部调 dispatch_match）
│   ├── position_advisor.py          # 【改】暴风雨 position_scale=0.3 改建议提示
│   └── position_advisor_v2.py      # 【改】同上 + _lookup_strategy 从新注册表读参数
├── sentiment_context.py          # 【改】line 226-227 暴风雨硬开关删除（全 allowed）；line 239 熔断改软标注
├── pre_market_workflow.py         # 【改】pool_item_map 传入 score_candidates
├── intraday_coach.py              # 【改】STRATEGY_REGISTRY 引用改为新注册表
├── prediction_ingest.py           # 【改】同上
└── strategies/strategy_backtest.py # 【改】同上 + 回测从新注册表读参数
```

---

## 2. 分阶段计划

### 阶段 A：基础设施（strategy_base.py）

**目标**：建立 Strategy 协议 + 调度器，不动既有代码。

| 任务 | 文件 | 内容 | 对应需求 |
|---|---|---|---|
| A1 | `strategy_base.py` | 定义 `StrategyContext` dataclass（code/gene/pool_item/indicators/derived/weather_state） | R1 |
| A2 | `strategy_base.py` | 定义 `ConditionMatch` dataclass（condition/value/description） | R1 |
| A3 | `strategy_base.py` | 定义 `StrategyProtocol`（code/name 属性 + match/compute_confidence/compute_entry_price 方法） | R1 |
| A4 | `strategy_base.py` | 定义 `StrategyConfig` dataclass（参数 + strategy_impl 指向 Strategy 实现） | R5 |
| A5 | `strategy_base.py` | 实现 `dispatch_match(ctx, registry) → list[StrategySignal]` 调度器（遍历注册表 → 各 Strategy.match → 组装 StrategySignal） | R6 |
| A6 | `strategy_base.py` | 实现 `_prepare_derived(card_derived, code) → dict | None`（derived fallback 上提） | R8 |
| A7 | `strategy_base.py` | 实现 `_prepare_pool_item(pool_item_map, code) → dict | None`（从 map 取 pool_item） | R7 |

**验证**：`strategy_base.py` 可 import 无报错；`dispatch_match` 空注册表返回空列表。

---

### 阶段 B：战法迁移（impl/ 4 文件 + 注册表合并）

**目标**：把 `match_strategies` 的 10 个分支逐个迁移到 Strategy 类，合并两套注册表。

#### B1：gene_based.py（7 个简单战法）

| 任务 | 战法 | match 条件（从 limitup_strategy.py 迁移） | confidence | 对应行 |
|---|---|---|---|---|
| B1.1 | first_plate | `total_score>=60 ∧ 涨停频次>20` | 动态 `score/100` | :725-732 |
| B1.2 | consecutive_relay | `zt_count>=2 ∧ 封板率>=60%` | 动态 `封板率/100` | :734-741 |
| B1.3 | break_reseal | `3<=zt_count<=5 ∧ 封板率>=80%` | 固定 0.7 | :743-752 |
| B1.4 | end_of_day_sneak | `封板率>=40% ∧ 溢价率>40%` | 固定 0.4 | :809-816 |
| B1.5 | n_shape_counterattack | `2<=zt_count<=10` | 固定 0.5 | :789-798 |
| B1.6 | platform_breakout | `total_score>=60 ∧ 涨停频次>40` | 固定 0.5 | :800-807 |
| B1.7 | dragon_head | 无条件放行（match 返回单条 "无条件" + confidence=0.5） | 固定 0.5 | 无（新实现） |

#### B2：pool_based.py（storm_reversal）

| 任务 | match 条件 | confidence | 对应需求 |
|---|---|---|---|
| B2.1 | `pool_item["fbt"] <= 103000`（封板时间≤10:30） | 固定 0.7 | R3（新纳入 match） |

#### B3：indicator_based.py（2 个复杂战法）

| 任务 | 战法 | match 条件 | confidence | 对应行 |
|---|---|---|---|---|
| B3.1 | weak_turn_strong | 5 因子硬阈值（lbc/broken/drop/lock/vol_ratio）≥4 命中 | 1.0/0.7 | :822-906 |
| B3.2 | pattern_reversal | 5 因子硬阈值（close/high/shadow/vol/ma5）≥4 命中 | 1.0/0.7 | :908-962 |

**注意**：B3.1 的 derived 取数逻辑不上提（阶段 A 的 _prepare_derived 已做），Strategy 类只读 `ctx.derived`。

#### B4：db_based.py（reverse_package）

| 任务 | match 条件 | confidence | 对应行 |
|---|---|---|---|
| B4.1 | `seal_intraday.db` open_count>=2 的票包含 gene.code | 固定 0.4 | :763-787 |

#### B5：注册表合并

| 任务 | 文件 | 内容 | 对应需求 |
|---|---|---|---|
| B5.1 | `strategy_funnel_registry.py` | 合并 `STRATEGY_REGISTRY`(dict) + `STRATEGY_FUNNEL_REGISTRY`(dataclass) 为单一 `STRATEGY_REGISTRY: list[StrategyConfig]`，12 项 | R5 |
| B5.2 | `strategy_funnel_registry.py` | 删除 `_MATCHED_STRATEGY_CODES` 白名单 | R5 |
| B5.3 | `limitup_strategy.py` | 删除旧 `match_strategies` 函数；保留 `from strategies.strategy_base import dispatch_match as match_strategies` 兼容导出 | R1 |
| B5.4 | `limitup_strategy.py` | 删除旧 `STRATEGY_REGISTRY`（dict 版），改为 `from strategies.strategy_funnel_registry import STRATEGY_REGISTRY` 兼容导出 | R5 |

**验证**：`dispatch_match` 用 mock ctx 跑全部 12 个 Strategy，各返回预期 ConditionMatch；既有 `from limitup_strategy import STRATEGY_REGISTRY, match_strategies` 导出路径不变。

---

### 阶段 C：硬开关移除 + 入场价统一

**目标**：移除暴风雨硬开关，统一入场价。

| 任务 | 文件 | 内容 | 对应需求 |
|---|---|---|---|
| C1 | `sentiment_context.py:226-227` | 删除 `if weather_state == "暴风雨": return ["storm_reversal"], [其余 forbidden]`；改为全 allowed | R3 |
| C2 | `strategy_funnel_registry.py:448` | 删除 `if cfg.code == "storm_reversal" and weather_state != "暴风雨": continue` | R3 |
| C3 | `sentiment_context.py:239` | `r1_triggered = weather_state == "暴风雨"` 改为软标注（fuse_state 标"建议降仓"，不阻断） | R3 |
| C4 | `position_advisor.py` | 暴风雨 `position_scale=0.3` 改建议提示（`position_advice_note: "暴风雨天建议仓位×0.3"`） | R4 |
| C5 | `position_advisor_v2.py` | 同 C4；`_lookup_strategy` 从新注册表读参数 | R4 |
| C6 | `strategy_base.py` 调度器 | `compute_entry_price` 默认返回 `pool_item.p`；`pool_item` 缺失时 fallback `gene.total_score` + 标注"价格代理" | R2 |
| C7 | `impl/indicator_based.py` pattern_reversal | override `compute_entry_price` 返回 `pool_item.p + 0.01` | R2 |
| C8 | `strategy_funnel_registry.py` score_candidates | 增加 `pool_item_map: dict[str, dict] | None = None` 入参；调用 dispatch_match 时传完整 ctx | R7 |
| C9 | `pre_market_workflow.py` | 调 score_candidates 时传入 `pool_item_map` | R7 |

**验证**：暴风雨天所有战法 allowed（不强禁）；入场价全部用 `pool_item.p`（mock pool_item.p=10.0 → stop_loss=9.7 不是 72.75）。

---

### 阶段 D：清理过时标注

| 任务 | 文件 | 内容 | 对应需求 |
|---|---|---|---|
| D1 | `strategy_funnel_registry.py:231` | 清除 `reverse_package` 的 `activation_note="待 S055 激活"` | R9 |
| D2 | `limitup_strategy.py:541` | 清除 `break_reseal` 的 note "60日无信号：炸板后溢价因子疑似缺供" | R9 |
| D3 | `limitup_strategy.py:572` | 清除 `reverse_package` 的 note "60日无信号：match 逻辑依赖「炸板后溢价」因子缺供" | R9 |
| D4 | `limitup_strategy.py:587` | 清除 `n_shape_counterattack` 的 note "60日无信号：条件定义待重定义" | R9 |

**验证**：注册表 12 项无过时 note / activation_note。

---

### 阶段 E：测试

| 任务 | 文件 | 内容 | 对应需求 |
|---|---|---|---|
| E1 | `tests/test_s086_dispatch.py` | 调度器单测：空注册表 → 空列表；mock ctx + 12 Strategy → 预期 ConditionMatch | A15 |
| E2 | `tests/test_s086_dispatch.py` | `_prepare_derived` 单测：card_derived 非空 → 直接返回；None → fallback 取今日 snapshots；异常 → None | A15 |
| E3 | `tests/test_s086_strategy_impl.py` | 各 Strategy match 单测：gene_based 7 个 + pool_based 1 个 + indicator_based 2 个 + db_based 1 个 | A15 |
| E4 | 既有测试 | `test_s053_rebound_factor.py` 跑通（break_reseal 条件不变） | A14 |
| E5 | 既有测试 | `test_s062_strategy_card_content.py` 跑通（dragon_head 注册表 schema 适配新 dataclass） | A14 |
| E6 | 既有测试 | `test_s081_prd_strategies.py` 跑通（weak_turn_strong / pattern_reversal 逻辑不变） | A14 |
| E7 | 既有测试 | `test_s084_match_card.py` 跑通（match card 传递） | A14 |
| E8 | 既有测试 | `test_strategy_funnel_registry.py` 跑通（注册表合并后 12 项，暴风雨不再 forbidden） | A14 |
| E9 | 既有测试 | `test_s031_strategy_backtest.py` 跑通（回测，8→12 战法断言更新） | A14 |

**验证**：`pytest backend/tests/ -k "s086 or s053 or s062 or s081 or s084 or strategy_funnel or s031_strategy" -m "not live"` 全绿。

---

## 3. 依赖顺序

```
阶段 A（基础设施）—— 无依赖，可独立完成
    ↓
阶段 B（战法迁移 + 注册表合并）—— 依赖 A 的 StrategyProtocol + dispatch_match
    ↓
阶段 C（硬开关移除 + 入场价统一）—— 依赖 B 的注册表合并（storm_reversal 已在注册表）
    ↓
阶段 D（清理过时标注）—— 依赖 B（note 在新注册表里清）
    ↓
阶段 E（测试）—— 依赖 A+B+C+D 全完成
```

阶段 A 和阶段 D 理论上可并行（D 只改 note 字符串），但 D 依赖 B 的注册表合并（note 在新注册表里），所以 D 在 B 之后。

---

## 4. 回滚

纯代码重构，无数据迁移。git revert 即可回滚。

---

## 5. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 12 个 Strategy 迁移面大 | 中 | 分批：B1（7 简单）→ B2+B4（各 1）→ B3（2 复杂），每批跑测试 |
| `pool_item.p` 可能缺失（非涨停池路径） | 中 | `compute_entry_price` fallback `gene.total_score` + 标注"价格代理" |
| 暴风雨硬开关移除后 storm_reversal 在非暴风雨天也跑 | 低 | match 条件（封板≤10:30）自然过滤；仓位建议提示保留 |
| 既有测试断言更新（8→12 战法） | 低 | 测试文件逐个更新（E4-E9） |
| `STRATEGY_REGISTRY` 引用方多（7 文件） | 中 | 保留 `from limitup_strategy import STRATEGY_REGISTRY` 导出路径（B5.4） |
| `match_strategies` 引用方多 | 中 | 保留 `from limitup_strategy import match_strategies` 兼容导出（B5.3） |
