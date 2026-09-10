# S180 — r3 sizing 接线（R3-R4，用冻结值，不依赖 enforce 自动复验）

> 状态：实现中（2026-09-10）
> 关联：r3-enforce deferred（专家建议 R3-R6 sizing 接线先做，R8 enforce 等数据）/ S159 §44v2 / S175 PaperPortfolio
> 分级：medium（3 文件改 + 测试，不碰 R2 underpowered gate 三重 cap 源）

## 1. 问题/目标

r3-enforce 搁置（专家 CRITICAL：path_lift 没臂读 + forward_test 空表 + 三重 cap ×0.125 未承认）。但 **R3-R6 sizing 接线**（lift_to_multiplier 接 final_size）独立有用——让 ×0.5 cap 接 sizing 路径（当前默认 1.0 不咬）。用冻结 DIMENSION_LIFT_REGISTRY（DB 空降级冻结，R5-R6 DB 缓）。

north-star 胜率诚实前置：接口通，breakout 臂若上仓 ×0.5 cap 真咬（days<60）。当前空转（breakout paper_track 不 sizing，floor N/A cap=1.0）但接口接线，前瞻基建。

## 2. 需求

- **R3** `candidate_funnel/evaluation.py` 加 `lift_for_arm(arm)` + `DIM_ARM_MAP`（arm→dimension 映射：breakout→breakout，floor/gap/mock→N/A 1.0）。查冻结 DIMENSION_LIFT_REGISTRY + lift_to_multiplier（days<60→×0.5）。
- **R3** `engine/paper_portfolio.py` final_size 默认 lift_multiplier=None → 内部调 lift_for_arm(arm) 动态算。
- **R4** `recommendation_engine.py` floor_size 读 `pp.final_size('floor', ...)` 含 cap（floor N/A→1.0 数值同，接口接线）。

## 3. 不碰（搁置）

- R2 drawdown_breaker underpowered gate 1.0→0.5（三重 cap ×0.125 源，专家 MEDIUM 要决策乘 vs max，搁置）
- R5 evaluation_lifts.db DB-backed（用冻结值，DB 缓）
- R6 get_dimension_lift DB-first（用冻结 DIMENSION_LIFT_REGISTRY）
- R8 enforce 自动复验（forward_test 空表，搁置）

## 4. 验收

- `lift_for_arm('breakout')` = ×0.5（days<60，用冻结 registry breakout dim）
- `lift_for_arm('floor')` = 1.0（N/A cap 不作用）
- `paper_portfolio.final_size('breakout', 10000)` 含 ×0.5 cap
- recommendation floor_size 读 final_size（接口接，floor N/A 数值同）

## 5. 合规

- 不臆造：lift_for_arm 用冻结 DIMENSION_LIFT_REGISTRY（source_script 可追溯）
- 私有数据隔离：无涉
- em_get 防封：无涉
- §44 降级 vs enforce：R3-R4 是 sizing 接线非 enforce 阻塞门，一致
