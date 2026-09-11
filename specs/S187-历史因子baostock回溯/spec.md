# Spec: S187 — 历史因子 baostock 回溯

> 状态：⛔ 阻塞（seal_time 数据墙）—— 2026-09-11 实测验证 Path A 不可行
> 作者：Claude  日期：2026-09-11
> 关联：[[../S184-kline-refresh性能/spec.md]]、[[../S185-Turso多源数据湖/spec.md]]、P1-3 forward_test 0 picks、r3-enforce 30 天阈值

## 1. 问题 / 目标

forward_test 历史回补 07-09~08-14（27 天）全 0 picks，卡住 r3-enforce 30 天阈值（当前仅 20 天 picks，08-17~09-11）。

**根因链**（P1-3 调查结论，详见 memory `p1-3-forward-test-zero-picks-root-cause-2026-09-11`）：
1. 07-09~08-14 gene_scores 因子全零（total_score/封板率/涨停频次/zt_count_250d 全 0）——完美相关：`gene_nonzero>0 ⟺ picks>0`。
2. 零因子根因：`limitup_screener/service.py:_collect_zt_history_batch`（算 seal/red/freq 的 30 天回溯）em-only，东财涨停池滚 ~14 天，老日期全空 → 因子算零。
3. `get_screener_result` 先查 DB 缓存返零、不重算；`service.py:_fetch_zt_pool` em-only 历史空池 → 重算也 0 行。

**已有 baostock 路径**（`limitup_screener/kline_rebuild.py:rebuild_date`）从 K 线重建 3 因子（次日溢价率/红盘率/涨停频次，`weights="rebuild"`），但 `_get_kline_bars` 主源 mootdx 当前挂（返空），TickFlow 兜底也空 → 0 bars → 0 涨停股。

**目标**：接 baostock fallback 到 `_get_kline_bars` → rebuild_date 对历史日期产非零因子 → 回补 07-09~08-14 gene_scores → 重跑 forward_test → 解锁 30 天阈值。

## 2. 背景

- baostock（已装 0.9.3，`engine/bars_provider._baostock_a_share_hist` 已实现）不封 IP、有数年日 K 线历史 + pctChg（涨停判定用）。实测 002414 07-09 bar `pctChg=10.0` 涨停 ✓。
- `kline_rebuild.rebuild_date(date, codes)` 从 K 线算 `compute_factors(history, [], [])` → boards/limit_pct/pool_date 真值，封板率/炸板后溢价标 None（missing，`weights="rebuild"` 3 因子）。
- backfill_history `--source kline` 走 rebuild_date；但 codes=None 扫全 DB（数百只）慢 + mootdx 挂 → 需 per-date 当日涨停 codes + baostock fallback。

## 3. 需求清单

- [ ] R1：`kline_rebuild._get_kline_bars` 加 baostock fallback——mootdx 返空 → `_baostock_a_share_hist(code)` → 转 Bar 兼容对象（date/open/high/low/close）。
- [ ] R2：rebuild_date 处理 baostock dict bars（或 `_get_kline_bars` 统一返 Bar 对象）——`build_ztpool_items_from_klines` 读 `.date/.close/.high`，baostock dict 需适配。
- [ ] R3：per-date 当日涨停 codes 传入 rebuild_date（从 DB 已有零行 code 或 ths 日池），避免扫全 DB。
- [ ] R4：回补脚本 recompute 07-09~08-14（DELETE 旧零行 + rebuild_date + save_gene_scores）。
- [ ] R5：重跑 forward_test backfill 07-09~08-14 → forward_test_records ≥ 30 天。
- [ ] R6：验证 07-09 gene_scores 因子非零 + picks > 0。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/limitup_screener/kline_rebuild.py` | `_get_kline_bars` 加 baostock fallback（dict→Bar 适配）；`_bar_from_dict` 辅助 |
| `backend/tools/recompute_gene_scores_kline.py` | **新增**——per-date DELETE + rebuild_date(codes=DB当日) + save |
| `backend/tools/backfill_forward_test.py` | 已有，跑 07-09~08-14（无需改，只重跑）|

## 5. 设计方案

**接 baostock fallback（R1-R2）**：`_get_kline_bars` 职责链 mootdx → TickFlow → baostock。baostock 返 `list[dict]`，转轻量 Bar（dataclass 或 `types.SimpleNamespace`）保 `.date/.close/.high/.low/.open`，`build_ztpool_items_from_klines` 透明消费。不改 mootdx 主源（mootdx 恢复后仍首选，baostock 仅兜底）。

**per-date codes（R3）**：recompute 脚本对每个日期从 gene_scores DB 取该日已有 code 列表（07-09 有 75 只零行 code，是当日真涨停股——em 当日写时 pool 有值），传 rebuild_date(date, codes=当日codes)。避免扫全 DB 数百只。

**回补（R4）**：脚本逐日 `DELETE FROM gene_scores WHERE date=?` → `rebuild_date(date, codes)` → `save_gene_scores(date, scores)`。rebuild_date 自带 `is_limit_up` 过滤（baostock 验证真涨停），非涨停的旧 code 不写回（净表）。

**为何不选 ths fallback（fork 误诊路径）**：ths 字段映射近似（lbc 硬编码）→ 因子质量存疑；baostock K 线算 boards/limit_pct 是真值，可复现。符合「别做看起来正确但没用的事」。

## 6. 验收标准

- [ ] A1：`rebuild_date("2026-07-09", codes=当日75)` 产 ≥ 1 只非零 GeneScore（baostock fallback 生效）。
- [ ] A2：回补后 07-09 gene_scores `total_score>0` 行数 > 0（对比回补前 0/75）。
- [ ] A3：forward_test backfill 07-09~08-14 后 `forward_test_records` 覆盖 ≥ 30 天。
- [ ] A4：`pytest -m "not live" --deselect` 全绿（deselect 见 memory `newsradar-flaky-network-test`/`s032-refresh-loop-flaky`/`s040-flaky-kline-cache`）。

## 7. 合规与工程底线自查

- [x] 研判属系统能力，forward_test 是模拟盘统计非买卖指令（用户定盘）。
- [x] 判断可复现：baostock K 线 + `is_limit_up(close, prev_close, code)` 规则可重算，禁臆造/心算。
- [x] 因子诚实标注：封板率/炸板后溢价标 None（missing，`weights="rebuild"`），非臆造零值。
- [x] 私有数据未进 git（gene_scores.db 在 resolve_data_dir，.gitignore）。
- [x] baostock 不走东财 em_get，无防封顾虑；mootdx/baostock 均不封 IP。

## 8. 测试计划

- 单元：`rebuild_date("2026-07-09", codes=["002414"])` 断言非零 GeneScore（baostock mock 或 live）。
- 集成：recompute 脚本跑 07-09 → 查 DB `total_score>0` 行数。
- 离线：`cd backend && .venv/bin/python -m pytest -m "not live" --deselect <flaky 三条>`。
- 手动：forward_test backfill 07-09 → `SELECT count(*) FROM forward_test_records WHERE signal_date='2026-07-09'` > 0。

## 9. 风险与回滚

- baostock 登录失败/不可用 → fallback 跳过返空（同现状，不恶化）；recompute 脚本对失败日期记 failed 不阻断。
- rebuild_date baostock 路径慢（~75 code/日 × 27 日 baostock query）→ 串行约 30-60min，可接受（一次性回补）。
- 回滚：`git revert` kline_rebuild 改动；gene_scores 旧零行可 re-DELETE+backfill --source eastmoney 还原（虽仍零因子，不恶化）。

## 10. ⛔ 阻塞结论（2026-09-11 实测）

**Path A 不可行——seal_time（封板时间）数据墙**：

实测 08-17（有 picks 的日）被 pick 股的 gene 因子：
- 001229: total=34.7, **seal=87.84%**
- 002081: total=43.27, **seal=93.59%**
- 002172: total=41.97, **seal=88.38%**

封板率（seal_rate，`weights="full"` 25% 权重）对涨停股天然高（87-93%），是 total_score 大头。
算法（`compute_factors` :`fbt_values`）：历史涨停日的**平均首封时间** → 换算封板强度（92500=9:25 早封满分，145000=14:30 晚封 0 分）。
首封时间是**盘中数据**：
- 东财 push2ex getTopicZTPool 有 fbt —— 但只滚 ~14 天
- 同花顺 ths_limit_up_pool 只返 code/reason/high_days 3 字段（无 fbt，9 死字段精简）
- baostock 日 K 线无盘中
- **没有任何干净源能给历史封板时间**

故历史回补的 gene_scores 必 seal=None/0 → total 掉 ~22 分（25% × ~88）→ 全低于 first_plate 阈值 40 + consecutive_relay `seal>=60` 报 TypeError 被吞跳过 → **0 picks**。

实测验证：recompute 07-10 → 90 只非零 rebuild gene_scores（baostock fallback 生效）→ `run_daily_forward_test("2026-07-10")` 仍 recommendations=0（seal=None 战法不匹配）。

**结论**：30 天阈值只能靠 live 积累（~10 交易日，约 2026-09-25 到 30 天）。r3-enforce 30 天是软门槛非硬阻塞，晚两周解锁无妨。

**副产品（独立于 P1-3，保留待提交）**：
- `kline_rebuild._get_kline_bars` 加 baostock fallback + `_BAOSTOCK_LOCK`（baostock session 非线程安全，rebuild_date _CONCURRENCY=20 并发互踩返空）——修了 mootdx 挂时 kline rebuild 路径全废的真 bug。
- `tools/recompute_gene_scores_kline.py`——per-date DELETE + rebuild_date 工具（产 rebuild-path gene_scores，forward_test inert 但可用于历史基因分展示/分析）。

**Path A'（未实施，重活）**：baostock 5 分钟线（`frequency="5"`）检测首封时刻 → 历史 seal_time。~75 code × ~5 涨停日 × 27 日 ≈ 10000 查询，~小时级，质量待验。为软门槛不值当，留作未来选项。
