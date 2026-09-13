# Spec: S201 — CRITICAL bug 修复（cost 口径统一 + gap 前视修复）

> 状态：草案（quant-system-brainstorm verdict ww1bqpg70 2 CRITICAL bug，撞"判断须可复现"工程底线）
> 作者：Claude  日期：2026-09-13
> 分级：medium（承重 accounting.py + gap_classifier.py，影响 §44 net verdict + chat.TOOLS + fusion + R4）
> 关联：[[S200]] §6.9 优先 spec / [[S194-信号融合基线]] F3 / [[S193-缺口理论集成]] R5 / 对抗审 ww1bqpg70

## 1. 问题 / 目标（2 CRITICAL bug）

**Bug1：cost 口径不一致**（撞"判断须可复现"底线）
- `accounting.py:30 ROUND_TRIP_COST_PCT=0.70`（spread 0.60% + slippage 0.10%，不含佣金/印花）+ 印花 0.10%/0.05% + 佣金 5 元×2 → ~0.80%+ round-trip
- `run_s194_f3_verdict.py:26 A_SHARE_ROUND_TRIP_COST=0.002`（0.2% = 佣金 0.025%×2 + 印花 0.05% + 滑点 0.10%，**不含 spread 0.60%**）
- S194 注释明说"0.7% 是美股/过度假设"——accounting 的 spread 0.60% 是美股假设，A 股 bid-ask spread 实际小（主流股 0.01-0.10%）
- **影响**：§44 net verdict 用哪个成本决定结论——breakout arm net -1.14%（accounting 0.70%）vs +0.36%（S194 0.2%），S192 实盘评估 + S194 F3 verdict 都受影响，不可复现

**Bug2：gap_classifier 前视**（_is_filled D+1..D+3）
- `gap_classifier.py:81-95 _is_filled` 扫 idx+1..idx+3（未来 bar）判 D 日缺口是否 3 日回补
- 突破/持续分类（:178/:187）require `not filled`——D 日信号标签偷看 D+1..D+3 未来
- S193 R5 v3 对抗审 wn80mbbm6 Q4 CRITICAL：3 日准确率 61.9%/59.9% 被前视膨胀非 clean OOS
- **影响**：chat.TOOLS query_gap_regime + fusion_pipeline gap_regime + R4 gap_scan 推送 + S193 R5 准确率都吃前视标签

## 2. 需求

### R1：cost 口径统一（Bug1）
- [ ] R1a：确认 A 股真实成本（spread/佣金/印花/滑点各多少）——查 accounting.py + 实盘数据
- [ ] R1b：统一 ROUND_TRIP_COST_PCT——accounting 0.70% 含 spread 0.60%（美股假设）→ 改 A 股真实（spread 0.05-0.10% + slippage 0.10% + 印花 + 佣金 ≈ 0.20-0.30%），或 S194 改用 accounting 口径（若 spread 0.60% 合理）
- [ ] R1c：§44 net verdict 复算——cost 口径统一后，breakout arm net verdict 重跑（-1.14% 或 +0.36% 取决于口径），S192 实盘评估 + S194 F3 verdict 同步
- [ ] R1d：标 cost_caliber（mixed-caliber 不出 verdict，verdict §44v2 一致性门）

### R2：gap 前视修复（Bug2）
- [ ] R2a：`_is_filled` 训练可用未来（标签训练），实盘信号只用 T 及之前 bar 重算（verdict 方案）
- [ ] R2b：gap_classifier 分训练/实盘模式（训练 `_is_filled` 用未来，实盘不用或用 T 之前 bar 代理）
- [ ] R2c：S193 R5 v3 重跑（前视修复后，突破/持续 3 日准确率重算，确认非前视上界）
- [ ] R2d：chat.TOOLS query_gap_regime + fusion_pipeline + R4 gap_scan 同步（实盘模式）

### R3：TDD + 对抗审
- [ ] R3a：6 视角对抗审修复方案（cost 口径对错 + 统一方案 + gap 前视修复 + 影响范围 + TDD 验收 + 时序）
- [ ] R3b：test_accounting + test_gap_classifier 加 cost 口径 + 前视修复 case

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/engine/accounting.py:30` | ROUND_TRIP_COST_PCT 0.70→A 股真实（待 R1a 确认）|
| `backend/engine/gap_classifier.py:81-95` | _is_filled 训练/实盘模式分（R2a/b）|
| `backend/tools/run_s194_f3_verdict.py:26` | A_SHARE_ROUND_TRIP_COST 与 accounting 统一（R1b）|
| `backend/s44_verifier/verifier.py` | cost_caliber 一致性门（R1d）|
| `backend/tests/test_accounting.py` + `test_gap_classifier.py` | cost 口径 + 前视修复 case（R3b）|

## 4. 验收

- [ ] A1：cost 口径统一（accounting + S194 同口径，标 cost_caliber）
- [ ] A2：§44 net verdict 复算（breakout arm net verdict 重跑，确认 -1.14% 或 +0.36%）
- [ ] A3：gap 前视修复（_is_filled 训练/实盘分模式）
- [ ] A4：S193 R5 v3 重跑（前视修复后突破/持续准确率重算）
- [ ] A5：pytest not live 全绿
- [ ] A6：6 视角对抗审修复方案过

## 5. 合规（撞工程底线"判断须可复现"）

- [x] 不臆造：cost 口径从 accounting.py + S194 实证 + A 股真实成本查证
- [x] 判断须可复现：cost 口径统一后 §44 net verdict 可复现（当前 0.70% vs 0.2% 不可复现）
- [x] gap 前视：修复后实盘信号无前视（训练/实盘分模式）

## 6. 关联

- [[S200]] §6.9 优先 spec（2 CRITICAL）
- [[S194-信号融合基线]] F3 verdict（cost 影响净收益结论）
- [[S193-缺口理论集成]] R5 v3（前视影响准确率）
- [[S198 衰竭翻转]]（gap 前视修复是独立 spec，非 S198 翻 label）
- 对抗审 ww1bqpg70（2 CRITICAL bug）+ 本 spec w7i1bugmm 6 视角审修复方案

## 7. verdict 修订（w7i1bugmm 6 视角 needs-revision，15 条）

S201 草案 DIAGNOSIS + FIX DIRECTION 都有缺陷，须修订后方可实现。**拆 3 子 spec**（不捆绑，不同爆炸半径+验证）：

### S201a：Bug1 可复现修复（立即，单文件低爆炸半径）
- rewire `run_s194_f3_verdict.py` 逐笔调 `accounting._cost_pct(entry_price, size, entry_date)`（读 journal record entry_price），传真实 mean cost 作 round_trip_cost（当前 0.0→floor 卡 min 0.003）
- 诚实结果：F3 verdict ~-1.0%（falsified/exploratory），与 journal 同口径可复现
- **INVERT framing**：S194 0.2% 是错的（忽略 5元门散户乐观），非"A股真实"；accounting 0.70% spread 美股过估但佣金模型真实/保守
- **绝不可 flatten 到 flat 0.20-0.30%**（重现 S182 4x 低价股偏差）。A 股真实成本 size-dependent：大流动股 ~0.15-0.35%，1手低价股（5元门）~1-2.75%

### S201b：Bug1 校准 spec（独立 large，不阻塞 S201a）
- (a) `ROUND_TRIP_COST_PCT` 0.70→~0.10-0.20%（T+1-open realistic，S189 grill 逻辑延伸——entry=bars[idx+1].open=真实开盘价，spread 0.60% 美股过估 double-charge）
- (b) **同 pass 修出场乐观**（accounting.py:178/188 精确水平成交→stop*(1-eps)/gap-through），否则降成本制造**假 robust_edge**（新 §44v1 式错误）
- (c) 扫 14 个独立硬编码 0.70 的 lift 脚本（lianban/gap_window/block_trade/index_ma20/first_board_layer/platform_breakout/first_plate_h2/low_absorption/valuation_pe/midline_pead/miaoban/zt_pool_seal_time/midline_st_removal/midline_event）
- (d) journal 1092/2888 case net_pnl 冻结，settle_pending 重结或加 cost_caliber 版本列
- (e) §44 cost-sweep 0.10/0.20/0.30/0.70 看 verdict 稳定性

### S201c：Bug2 gap 前视修复（独立 large）
- **R2a 反转**：检索/决策两侧都用 candidate 语义（去 _is_filled），非"训练留未来"（后者保留 fewshot train/serve skew——162 存活者标签污染 case 库→实盘检索偏乐观）
- 删除"T 之前 bar 代理"伪选项（不可实现——无过去 bar 测 3 日向前回补）
- **加 arity bug 修复**（query_gap_regime 死代码——`_baostock_a_share_hist` 1 参 vs 3 参调用，TypeError 被 except 吞返[]，classify_gap 恒返"baostock 无数据"）
- 模式判据 = `fill_window_realized ? confirmed : candidate`（非二分 train/live）。三态：历史已实现（confirmed）/ fusion+gap_scan 最新 bar（candidate，已静默退化 _is_filled=False 反偏非前视）/ classify_gap shell（死代码待修 arity）
- R5 验收阈值：突破/持续 3 日 cont rate 收敛到 ≤衰竭 ~56.5%（唯一 clean 类）；若 ≤baseline=无 clean 3 日力→维持调研候选不进融合权重
- 重写 test_breakaway_gap:103/test_continuation_gap:146（当前 ENCODE 前视）；拆 candidate/confirmed 两态；`_classify_gap_from_bars` 加 mode/allow_future 参；**新建 test_accounting.py**（当前不存在，TDD 地基缺失）
- 受影响加 reconstruct_s194_signals.py + run_s194_ablation.py + fewshot_retriever.py（前视传播 F1 消融+fewshot case 库）；删 forward_test.py（假阳性——零 accounting 引用，已 grep 确认）；S189 t0_cost 不受影响（用 T0_SLIPPAGE_PCT 非 ROUND_TRIP_COST_PCT）

### 关键判定
- **S200 不阻塞**：methodology 骨架（M1-M7+五域）bug-independent，可并行推进。3 子实体（cost-models/cost_model、signals/gap_signal、logic/防未来函数 rule）标"under calibration / pending S201"
- **S192 不翻案**：3 个独立否定（breakout net 负/T+0 无 edge/selection 证否）均 cost-independent，两口径下都无 validated edge。+0.36% 已撤为 regime artifact。S192 翻转只在 §44v2 robust_edge + days_robust≥60 + forward_test R3 enforce 时
- **S194 F3 verdict 确实变**（+0.36% robust_edge → ~-1.0% falsified）——独立融合 verdict 不可靠问题，非 S192 决策驱动
- **fix_order**：S201a 可复现先行（contained + decision-changing），S201c gap 并行，不捆绑，不严格串行。两者 large 级走 SDD（spec→plan→tasks+TDD+grill+verification）+ feature 分支

### 诚实判定
- cost 0.70% 的 spread 分量确是美股假设该降——但"改到 0.20-0.30% flat"是错的（5元门使真实成本 size-dependent 0.15-2.75%，flat 重现 S182 4x 低价偏差）。正解 = rewire F3 逐笔 _cost_pct（可复现立即）+ 独立校准 spec（降 spread+修出场乐观+cost-sweep）
- gap 前视"训练/实盘分模式"5 坑：arity bug 死代码 / "训练留未来" fewshot skew / "T 之前 bar 代理"不可实现 / 二分 train/live 粒度错 / live 已静默退化反偏非前视。正解 = candidate 语义两侧 + 重建 case 库 + 修 arity
- 6 视角共识：bug 真实但 spec 现状会让 cost 实际未统一（1.46%→~0.72% 非 0.20-0.30%）+ ablation/fewshot 残留前视 + 有制造假阳性风险。按上述修订 spec 后再实现


## 8. S201b 承重对抗审 verdict（w4ndolnj5 6 视角，needs-revision 7 CRITICAL）

**核心推翻**：S201b cost-sweep "+0.36% robust_edge at flat 0.10%" 是 **flat-vs-per-trade category error**——flat 减法每笔同减 0.10% 忽略 stamp 0.05% + 佣金 5元门 mean 0.7136% = undercharge 0.7636%。降 ROUND_TRIP_COST_PCT 0.70→0.15 是 per-trade 路径（_cost_pct line 89 = RTC+stamp+commission），每笔 cost 降 -0.55pp，day_mean -1.0%→~-0.45% **仍 falsified**。**诚实 per-trade route 不 unfalsify，+0.36% 是 flat-cost mirage**。

### 7 CRITICAL 执行错误（不可按 spec 直接实施）

1. **unfalsification 前提错**：cost-sweep +0.36% 来自 flat 减法（compute_net_at_levels 每笔同减 flat c，忽略 stamp+佣金 5元门 mean 0.7136%=undercharge 0.7636%）。降 RTC 是 per-trade flat addend（_cost_pct line 89），每笔 -0.55pp，day_mean -1.0%→~-0.45% 仍 falsified。**佣金门是结构性杀手非 spread**（96% entries 触发 5元 floor，median entry 23.80→佣金 0.42%，与 spread 无关）。即使 RTC=0 也 falsified（佣金门 0.7636%>gross 0.4655%→net=-0.30%）。
2. **出场乐观修错行**：spec 说 178/188 但这两行只设 PathReturn.exit_price（journal 元数据），不喂 net/cost。真正 gross 硬编码 line 172 `gross=float(stop_pct)` + line 181 `gross=float(take_profit_pct)`。只碰 178/188=NO-OP。须重写 stop/take 分支从 gap-through-aware fill 算 gross。
3. **take-side 修反了**：BREAKOUT_TAKE_PCT=8.0 是 limit sell（触及限价即成交），fill 在限价水平已 realistic。对 take gap-through 会 fill 限价之上=高估盈利=制造 spec 自己警告的 fake robust_edge。**只修 stop-side(172)，不碰 take-side(181)**。
4. **佣金门是杀手非 spread**：即使 RTC=0（零 spread+slippage），real mean cost=stamp(0.05)+commission(0.7136)=0.7636%>gross day_mean 0.4655%→net=-0.298% FALSIFIED。降 spread 不可能 unfalsify。
5. **14 脚本计数错**（11 非 ~5）+ 3 类须不同修法：A=6 flat-deduct（换 _cost_pct）/ B=4 gross无扣（加扣非换常量）/ C=1 event-flat（传 cost=None）。不 import ROUND_TRIP_COST_PCT，改 accounting alone=mixed-caliber。
6. **journal 策略错**：cost-only=read-only recompute（零 mutation，gross_return cost-independent，net=gross-_cost_pct 从冻结字段重算，S201a 已证明）；exit-optimism=re-run path_return + 版本保留（ALTER TABLE gross_return_v2+exit_model_version 或 fills_json append-only）。**绝不可 INSERT OR REPLACE**（journal_recorder.py:244 覆盖全字段无 before-image，违 reproducibility 底线）。settle_pending 只碰 is_realized=0 holds，不碰 2888 realized。
7. **多重比较未校正**：5 口径各 n_comparisons=1 无跨口径校正。BH 0.022×5=0.11>0.05 → flat 0.10% 降 exploratory 非 robust_edge。verdict 跨相邻口径翻转(robust→exploratory→falsified)说明 edge cost-marginal 非 robust。

### spread_target: 0.15%（微观结构 justified 非 verdict cherry-pick）

0.10% slippage（S189 T0_SLIPPAGE_PCT）+ 0.05% residual half-spread（tick-based A 股 0.02-0.20%）。价格依赖（5元 full-spread 0.20% vs 50元 0.02%），5元门佣金抵消低价 under-charge。须跑 fine sweep {0.10/0.12/0.15/0.18/0.20}+per-trade-lowered sweep 证明稳定性（预期全 falsified）。spec 须写"值来自微观结构非 verdict"防 researcher-DoF。

### exit_optimism_fix（4 CRITICAL 修正）

1. **修 gross 非 exit_price**：172/181 硬编码 gross，178/188 只元数据。须重写 stop/take 分支 gap-through-aware fill 算 gross。
2. **只 stop-side**：take 是 limit sell 已 realistic，gap-through 会高估。只修 stop（172）。
3. **gap-through 主项非 eps**：48% stop exits gap-through at open，mean -4.24% vs 硬编码 -4.0%。stop fill=if open<=stop→fill=open（gap-through worse）；elif low<=stop→fill=stop*(1-eps)。加 exit-day sellability check（一字跌停 locked→carry）+ bar contiguity guard。
4. **同 pass=sequencing 非 bundling**：production path 即使 0 spread 也 falsified（佣金门），无"造假 robust_edge"风险（只在 flat cost-sweep）。同 pass 真因=gross honesty（S201a -1.0% 低估 falsification ~1.2pp，诚实 -2.2%）+ cost-sweep honesty（flat-0.10% mirage 擦到 -0.85%）。最小干净 bundle=(a)降 RTC+(b1)fix stop-172 gap-through+(d)bulk re-settle 或 version column。

### journal_strategy（拆两类）

- **cost-only**（降 spread+扫 14 脚本+cost-sweep）=read-only recompute 零 mutation。gross_return cost-independent，net=gross-_cost_pct 从冻结字段重算。泛化 S201a 模式，cost_caliber 参数化 verdict 层，journal 冻结不动。
- **exit-optimism**（改 gross_return 本身）=须 re-run path_return+版本保留（ALTER TABLE gross_return_v2+exit_model_version 或 fills_json append-only 或 spec 文本归档旧 §44 verdict 数字标 superseded）。

### unfalsify_verdict: 0.15% 不 unfalsify

+0.36% robust_edge 是 flat-cost-sweep multiple-testing artifact，非真 edge。佣金门是结构性杀手。spec 须删"降 spread 可能 unfalsify"前提。

### s192_impact: 不翻案

0.10% robust_edge 是 flat-cost artifact 非 新证据。S192 有 3 cost-independent 否定（breakout falsified/T+0 无 edge/selection 证否），降 spread 改不了。

### 方向对（保留）

降 spread 方向对（entry=Executor 真实 T+1 open 非 0.60% spread 桥接）+ 修 stop 出场乐观方法论对 + 5元门绝不可 flatten + cost-sweep 诚实校准有独立价值（去 0.70% 美股假设）。修 7 CRITICAL 后可实施。
