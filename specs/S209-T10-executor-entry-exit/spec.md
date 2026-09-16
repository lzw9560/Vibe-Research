# S209 — T10 executor entry/exit 规则（post-首板 trade edge 探索）

> 状态：spec（2026-09-16，SDD workflow `wc0abcmv8` 综合 5 专家 + synth；4 readers schema bug 挂了，专家补位）
> 关联：S208 scanner（`f3beae9`）、S201 breakout 证否、[[s207-non-manifesting-grill-verdict]]、[[breakout-trade-profitable-despite-falsified-selection]]

## 1. 问题 + 前提证否

T10 executor 须有 entry/exit 规则从 S208 post-首板候选（lbc==1）提 trade edge。

**前提证否（ashare-practitioner 戳破）**：原假设"breakout +0.36%/笔 net 证明 entry/exit 规则可在弱选股下创造正 EV"——**本仓 S201 spec 已证否**：
- 5元佣金门是真凶（96% entry 触发 5元下限，median ¥23.80→佣金 0.42%/side→round-trip 0.76%，gross 仅 0.47%→**net=-0.30%** 即使 RTC=0）。
- +0.36% 是 regime 池化假象（4-6月牛 +7月熊混均），Q1 backfill 1月多头 bull-trap -1.74% 戳破，4 MA filter OOS 全失败。
- S201 spec:101："+0.36% 撤为 regime artifact，3 独立否定（net 负/T+0 无 edge/selection 证否）cost-independent"。

**存活事实**：entry/exit 规则创 **GROSS 正 EV**（41% winrate > 35% gross 盈亏平衡），但 5元佣金门吃成 net 负。

**真问题**：post-首板的 gross edge 够不够大到吃掉 0.62-0.76% round-trip 成本 + T+1 可买性逆向选择（赢家一字板买不到，买到的偏输家）会不会把 gross edge 也吃掉。

## 2. 目标
建 T10 executor entry/exit 规则作**探索性 PAPER 臂**（非已证 net edge 实盘臂）——继承 breakout 冻结 config，§44 自证 net edge（预期 underpowered，~46 天样本）。不继承 breakout 假阳性。

## 3. 需求（synth Phase 1，pre-registered frozen no sweep——~46 天样本唯一统计可辩护）

- R1 ENTRY：T+1 open（T1OpenFill, fill_policies.py:52, offset≥1 反前视，已建）+ is_unbuyable_next_bar 过滤（bar_utils:47, board-aware ST4.8%/主9.8%/创19.8%/北29.8%，已接 Executor:56）——**tradability 过滤**（一字板封死买不到，不交易）。
- R2 STOP/TAKE/HOLD：-4/+8/3 固定（继承 breakout DEFAULT_PATH_PARAMS，74295b9 冻结）——**不新 sweep**（小样本，sweep=overfit）。
- R3 REGIME：MA20 3-way（bull/bear/range）**regime-reported 非 gate**——硬过滤已 OOS 证伪（1月 bull-trap）；regime 只走 §44 分层报告 + 仓位缩放（drawdown_breaker ×0.5 熊市）。
- R4 POSITION SIZING：four-layer（arm × portfolio × lift × intraday），exploratory cap（lift=0.5 underpowered / intraday=1.0 MVP），base 1手。
- R5 诚实标注：'exploratory PAPER arm'，不 claim net edge，lift_mult ×0.5 直到 §44 walk-forward 验。

## 4. 受影响文件 + build tasks
- T1 pctChg 注入（S204 R14）——**✅ DONE**（`ccdb3fb`/`7e75465`，enrich_pctchg + _load_kline_cache）。
- T2 post_first_board 处理加 journal_recorder.py（mirror _process_breakout，调 scan_pre_limitup）。
- T3 DIM_ARM_MAP['post_first_board'] + DIMENSION_LIFT_REGISTRY entry（lift=None, status='探索性', weight_multiplier=0.5）。
- T4 **P0**：4-layer compute_final_size 接 PaperPortfolio.final_size（当前 3-layer 漏 intraday_mult）——intraday_loss_breaker backstop 失效。
- T5 **P0**：exploratory_arm_floor=0.05 加 PaperPortfolio（bayesian arm size floor <30 trades）。
- T6 backend/tools/s209_t10_executor_harness.py（§44 验证，DRY 复用 path_return + regime_stratified + wire_verdict）。
- T7 跑 harness ~46 天 → **预期 underpowered**（诚实）。若 'robust_edge' → 查 bug（pctChg 注入错？cost 算错？）。

## 5. 验收
- T10 executor entry/exit 规则建好（T+1 open + is_unbuyable + -4/+8/3 + regime-reported + four-layer）
- 标 'exploratory PAPER arm'，lift_mult=0.5
- §44 harness 跑出 'underpowered' verdict（~46 天 < 60 天 R6 gate）——诚实，不造假 robust_edge
- 4-layer sizing 接通（T4 P0 fix）+ intraday_loss_breaker backstop 生效

## 6. defer
- §44 walk-forward 验证——须 backfill ≥120 天（walk_train=100/test=20）
- sweep（gap bounds / stop / take 邻近 config）——须 edge 在 ≥2/4 邻近 config 都成立（S203 R2 sweep gate）
- 实盘启用——须 §44 verdict robust_edge + 用户确认（当前 exploratory paper）
- gap filter [-2%,+4%] 作 entry signal——v2（须 sweep 验证，当前继承 -4/+8/3 不加 gap filter）

## 7. open questions
- post-首板 gross edge 够不够吃 0.62-0.76% round-trip 成本？（须 §44 实测）
- T+1 可买性逆向选择（赢家一字板买不到）会不会吃 gross edge？（is_unbuyable 过滤后的 selection bias）
- T4 4-layer sizing 是否真缺 intraday_mult？（须核 PaperPortfolio.final_size 当前实现）
