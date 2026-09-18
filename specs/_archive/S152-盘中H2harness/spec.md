# Spec: S152 — 盘中 H2 harness（baostock 5min 历史补，封板时间×开板次数 lift）

> 状态：已实现 + verdict 出（2026-09-05，5432af5）——H2 早封板 lift=0.7843 劣于随机，盘中封板时间证否
> 作者：Claude  日期：2026-09-05
> 关联：S151（评价层）、S153（量化验证）、[edge-in-intraday-not-selection memory]、S150（采集修复）

## 0. Verdict（2026-09-05 跑出）

**H2 证否**——baostock 5min 历史补（突破 seal_intraday 30 天 live 卡点），41 日 / 606 features（top 15/day preliminary）：
- **early_lock（早封板 ≤10:00）: n=311, lift=0.7843 < 1.0 → 劣于随机**, null_p95=1.083, pass_filter_edge=False
- one_word（一字板）: n=1（top15 多非一字板，检测严）, 探索性
- overall: **未validated/劣于随机**

**"唯一未证伪维度" H2 现证否**——盘中封板时间也无 edge，与选股无 edge（forward lift=0.983）一致。"edge 在盘中"对封板时间维度不成立。

**T2.3 扩展（5 组，Bonferroni K=5）**：开板（reverse_package 近似）/晚封板（end_of_day_sneak 近似）/大回撤（weak_turn_strong 候选）：

**Full run verdict（2717 features / 31 日，--full 全量）**：
- early_lock: n=1125 lift=0.8273 劣于随机（确认无 edge）
- open_board（开板 reverse_package 近似）: n=2537 lift=0.9976 劣于随机（确认无 edge）
- **late_lock（晚封板>14:00 end_of_day_sneak 近似）: n=422 lift=1.3559 > null_p95=1.1165 pass_filter_edge=True——ROBUST 弱正**（preliminary 1.33 n=94 → full 1.36 n=422，4.5x 数据下信号 HELD；但<2 未validated ×0.5）
- high_drop: n=0（5min 粒度对涨停股 max_drop>3% 太粗，探索性）
- one_word: n=1 探索性

**late_lock（尾盘突袭）是整个测试空间（选股+盘中5min族）唯一 >1 的 robust 弱正**——1.36x n=422 pass_filter_edge，但<2x 未validated，不驱动交易（raw-shadow 观察）。DIMENSION_LIFT_REGISTRY 加 first_plate_h2（劣于随机×0.1）+ late_lock（未validated×0.5）。

**交互验证（workflow 审计后补 auction_open_pct，preliminary top15/day）**：
- late_x_auction（晚封×竞价高开>3%）：n=44 lift=1.1064 null_p95=1.38 pass_filter_edge=False
- **加竞价 context 反而弱化 late_lock（1.33→1.10）**，Bonferroni 膨胀（K=5→6）让 null_p95 升高——印证 synthesis 警告"多维交互让显著性更难过非更容易"。
- 5min 可测盘中族全探索完（单一+交互），无 edge。

caveat: T+0 o2c（未剔 unbuyable 一字板，S144 口径 follow-up）+ 5min 粒度（60s→5min coarser，broken_duration<5min 漏标）+ top15/day 采样（full run 后续，但 n=311-548 robust）。

## 1. 问题 / 目标

§44 证否选股（forward lift=0.983 劣于随机，dimension lifts 全<2x），但 **edge 在盘中不在选股**（未测 60%）。
唯一未证伪维度 = first_plate **H2 质量门（封板时间×开板次数）**。

**数据卡点**：seal_intraday_snapshots（60s 封单轮询）仅 4 天（08-13~08-17 + 09-04），东财涨停池是 **live intraday 端点无历史时序可回补**，到 30 天需 ~5-6 周 live 积累。

**突破**：封板时间/开板次数可从 **baostock 5min kline（历史可回溯数年）** 推导——不依赖 60s 封单时序。本 spec 建 harness：baostock 5min → H2 特征 → day_paired_lift（封板时间早/开板少 是否预测次日溢价）。

**目标**：用历史 5min kline（42 日 eastmoney_live 涨停股 universe）测 H2 是否有 edge，诚实 verdict（不事后调参）。

## 2. 背景

- baostock `query_history_k_data_plus(frequency="5")` 提供 5min kline（历史数年，qfq 复权）——已验证 002820/300684 08-17 各 48 bars（9:35~15:00）
- H2 特征从 5min bars 推导：涨停价=max(close)；封板时间=首 bar close==涨停价；开板次数=封板后 close<涨停价 的 bar 数；broken_duration=开板数×5min
- §44 harness 范式（platform_breakout_lift.py / low_absorption_c3_lift.py）：day_paired_lift + within-day survivor resampling + Bonferroni
- S153 阶段 1 全无 edge（H1-H4）；S152 是阶段 2 起步（盘中 H2，唯一未证伪维度）

## 3. 需求清单（R1-R4）

- [ ] R1 universe：取 gene_scores eastmoney_live 信号日（07-09~09-04，42 日）的涨停股 code 清单（每日涨停池），去重成 (date, code) pairs
- [ ] R2 baostock 5min fetch：每 (date, code) 取当日 5min bars + 次日 5min bars（次日 open/close 算次日收益）。baostock login→fetch→logout，限流 sleep（防封底线不适用 baostock，但礼貌间隔）。缺数据标 None 不臆造
- [ ] R3 H2 特征计算（纯函数 `compute_h2_features(bars_today, bars_next)`）：
  - 涨停价 = max(close) 当日（涨停股必触涨停价）
  - first_lock_time = 首 bar close>=涨停价 的 time（09:35=开盘封死=一字板）
  - open_count = 封板后 close<涨停价 的 bar 数
  - broken_duration_min = open_count × 5
  - is_one_word = first_lock 为 09:35 且 open_count==0
  - next_day_return = (次日 close - 次日 open) / 次日 open（T+0 intraday 基线，对齐 S144 o2c）
- [ ] R4 day_paired_lift + honest verdict：
  - 分组：早封板（first_lock <= 10:00）vs 晚封板/开板（first_lock > 10:00 或 open_count>0）
  - day_paired_lift（非池化，复用 platform_breakout_lift.day_paired_lift 范式）：同日早封板组 vs 同日全体涨停股（random baseline）
  - Bonferroni K=2（早封板 / 低开板 两组）
  - verdict：lift>=2 + CI 不重叠 + n>=30 → validated；1<=lift<2 → 未validated；<1 robust → 劣于随机；n<30 → 探索性
  - 诚实标注（不事后调参）：结果写 stdout + evaluation_lifts.db（DIMENSION_LIFT_REGISTRY 升级 DB-backed）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/tools/first_plate_h2_lift.py（新） | R1-R4：baostock 5min fetch + H2 特征 + day_paired_lift + verdict |
| backend/candidate_funnel/evaluation.py | R4：DIMENSION_LIFT_REGISTRY 加 "first_plate_h2" 维度（初始冻结值来自本 harness 输出） |

## 5. 设计方案

**A. universe 取数**：gene_scores eastmoney_live 信号日 → 每日涨停股 code（从 gene_scores 的 code 字段，date+code 去重）。42 日 × ~10 涨停股/日 ≈ 420 (date, code) pairs。

**B. baostock 5min fetch**：`bs.query_history_k_data_plus(bc, 'date,time,open,high,low,close,volume', start, end, frequency='5', adjustflag='2')`。6 位 code → baostock 9 位（sh./sz. 前缀）。次日 bars 取 start=signal_date+1, end=signal_date+2（T+1 收益）。baostock 限流：每 fetch sleep 0.1s（礼貌，非防封必需）。

**C. H2 特征纯函数**：`compute_h2_features(today_bars, next_bars)` → {zt_price, first_lock_time, open_count, broken_duration_min, is_one_word, next_day_return}。缺数据返 None。

**D. day_paired_lift**：复用 platform_breakout_lift.day_paired_lift 范式——per-day 配对（同日早封板组 vs 同日全体），非池化防 4.686x→1.723x 假象。within-day survivor resampling（同日多涨停股不独立）。Bonferroni K=2。

**E. verdict + 诚实标注**：四态（validated/未validated/劣于随机/探索性）。结果写 evaluation_lifts.db（vr_paths 隔离）+ DIMENSION_LIFT_REGISTRY 加 first_plate_h2 维度。lift<2x 标"未validated"×0.5；<1 robust 标"劣于随机"×0.1（对齐 S151 降权梯度）。

## 6. 验收标准

- [ ] A1 compute_h2_features(一字板 bars) → first_lock=09:35, open_count=0, is_one_word=True
- [ ] A2 compute_h2_features(开板 bars) → open_count>0, broken_duration_min>0
- [ ] A3 baostock fetch 缺数据（非交易日/停牌）→ None 不臆造
- [ ] A4 day_paired_lift 输出 lift/n/CI/四态
- [ ] A5 verdict 诚实（n<30 标探索性；不事后调参）
- [ ] A6 pytest -m "not live" --deselect (newsradar+s032+s040) 全绿 + 新增 test_first_plate_h2_lift

## 7. 合规与工程底线自查

- [x] 不臆造：H2 特征全从 baostock 5min bars 实算，禁心算；缺数据标 None
- [x] 私有数据隔离：evaluation_lifts.db 写 VR_DATA_DIR（vr_paths.resolve_data_dir）不进 git
- [x] em_get 防封：本 harness 走 baostock（非东财），不触防封底线；baostock 限流礼貌 sleep
- [x] §44 已降级参考性建议：H2 verdict 不阻塞实现，标注用非门；lift<2 不阻断
