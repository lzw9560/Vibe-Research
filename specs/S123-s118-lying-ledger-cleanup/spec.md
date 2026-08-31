# Spec: S123 — S118 撒谎账本收尾（剩 5 条 confirmed_lying 全清）

> 状态：已实现(2026-08-31)
> 作者：lzw9560  日期：2026-08-31
> 关联：S118 scan 残留 5 条 confirmed_lying（全 M/LOW，worth_fixing，见 `../S111-真实裂缝登记册/registry.md` S118 节）；S119-S122 已清 4 条 HIGH

## 1. 问题 / 目标

S118 scan 判 9 条 confirmed_lying，S119-S122 已修 4 条 HIGH。**剩 5 条 M/LOW 待修**，本 spec 一次清掉，关账本（26/26 全修）。其中 #1/#4 是真承重链/§44 腿（非纯"非承重链"，registry 框架略保守）：

| # | crack | where | sev | 承重链 |
|---|---|---|---|---|
| 1 | realtime-capital-flow-no-date-provenance-carryforward-as-fresh | risk_models.py:670 | MEDIUM | capital_flow→flow_adjustment→dynamic_score→risk_score |
| 2 | hot-money-seats-partial-fetch-silent | hot_money_seats.py:109 | MEDIUM | seat 画像→multi_seat_signal→factors |
| 3 | seal-intraday-cron-misses-1500-close-auction-final | scheduled_tasks.py:2214 | MEDIUM | 盘中时序数据完整性（cron 注释撒谎） |
| 4 | backtest-daily-snapshot-degraded-hit-rate-no-provenance | backtest_lite.py:78 | MEDIUM | §44 胜率数字为真（hit_rate 落盘） |
| 5 | storm-daemon-news-items-no-provenance | storm_daemon.py:40 | LOW | storm 风暴预测 news 因子 |

目标：5 条全修，每条加测试钉死，全量 pytest 0 回归，registry 账本 26/26 全清。

## 2. 背景

- **#1**：`_get_realtime_capital_flow`(620-706) 取 `latest=history[-1]`(670) 当"今日"资金流，戳 `data_status='ok'`+`data_time=now`(704-705)。但盘前/盘中当日 bar 未出时 `history[-1]` 实为 T-1 carry-forward，被标成今日实时。`stock_fund_flow_120d` 行有 `"date"` 字段（eastmoney.py:556）。`vr_paths.last_trading_date_str()` 既有（返今日若交易日否则前一交易日）。
- **#2**：`fetch_billboard_for_date`(102-125) 循环 buy+sell 两榜，单侧 `except:continue`(123) 静默返半截。下游 `update_hot_money_seats`(99-116) 逐日累积→`build_seat_profiles`(139) 在残缺数据上算 `next_day_sell_rate`→席位分类错。仓内 `_meta` 范式：`_calculate_concentration_risk_meta`(risk_models.py:487) 返 `tuple[float,str]` + 非 meta 版向后兼容包一层。
- **#3**：`seal_intraday_collect` seed cron `* 9-14 * * 0-4`(2214) 末次触发 14:59，**漏采 15:00 收盘集合竞价终态**涨停/炸板。注释(2207-2208)谎称"加上 15:00-15:05 的 5 分钟，门控由 is_intraday_trading_time 兜底"——但 cron 14:59 停，门控无从跑。`is_intraday_trading_time`(seal_intraday_collector.py:80)→`vr_paths.INTRADAY_PERIODS`=09:25-11:30/13:01-**15:05**，门控本身覆盖 15:00-15:05。`collect_once` 第一行 `if not is_intraday_trading_time: return skipped` 在 em_get 之前（防封安全，已实锤）。
- **#4**：`_calc_next_day_return`(65-92) 取数失败（无 bars:78 / 日期未命中:88-89 / 异常:91）静默返 0.0，喂 `routers/win_rate.py:205,341` 算 hit_rate → `scheduled_tasks.py:382 INSERT INTO backtest_daily_snapshots`。0.0 当真 0% 收益→hit_rate 分母含失效样本→胜率失真（§44 承重链）。仓内 `backfill_winrate_samples.py:54` 已有 `float|None`（None=无数据）范式。`test_s050_shadow_comparison.py:84` 注释"K 线缺失 0.0→missing_kline 计数，missed 桶排除"——shadow 路径已处理，win_rate 路径未处理。
- **#5**：`fetch_snapshot`(31-87) 的 news_items(64-71) 无 provenance（对比 global_indices 已有 `fetch_ok`/`is_degraded`:55-56，S116）。`storm_predictor._collect_news_factor`(235-271) 读 `snap["news_items"]`(250)，空则 fallback_current(265)。T-1 快照 news 失败 vs 无快照不可区分。

## 3. 需求清单

### R1 realtime-capital-flow-carryforward 诚实化（risk_models.py:670）
- [ ] R1.1 `_get_realtime_capital_flow` live fetch 成功路径(668-706)：取 `latest_date=(latest.get("date") or "")[:10]`，比对 `last_trading_date_str()`（vr_paths）。若 `latest_date != current_td`（carry-forward，盘前/盘中当日 bar 未出）→ `data_status='degraded'` + `data_time=latest_date`（不戳 now）；否则维持原 `ok`+`data_time=now`。
- [ ] R1.2 `cross_source` degraded 与 carry-forward degraded 合取（任一为真→degraded）；`data_time`：carry-forward 用 bar date，仅 cross_source 用 now。
- [ ] R1.3 测试钉死（test_data_honesty.py）：①history 末条 date=T-1（carry-forward）→ data_status=degraded, data_time=T-1（非 now）；②末条 date=今日 → ok, data_time=now；③cross_source + carry-forward 同存 → degraded。

### R2 hot-money-seats-partial-fetch 诚实化（hot_money_seats.py:102-125）
- [ ] R2.1 加 `fetch_billboard_for_date_meta(trade_date) -> dict` 返 `{"rows": list, "buy_ok": bool, "sell_ok": bool}`（逐侧记成功=不抛异常）。`fetch_billboard_for_date` 改为调 `_meta` 返 `rows`（向后兼容，签名不变）。
- [ ] R2.2 `update_hot_money_seats`(99-116) 切 `_meta`：`if not (buy_ok and sell_ok)` → `logger.warning` + **跳过该日不纳入 all_data 聚合**（残缺日不喂 build_seat_profiles）。
- [ ] R2.3 `compute_seat_risk_factor`(27) 切 `_meta`：partial → `logger.warning` + 用可用 rows best-effort（不臆造，单 code 单日残缺属降级非聚合场景）。
- [ ] R2.4 `strategy_funnel_registry.py:605` 切 `_meta`（live 承重链，partial 标 degraded）。`tools/build_hot_money_seats.py:32` 留 list 版（一次性 batch 脚本，非 live）。
- [ ] R2.5 测试钉死（test_hot_money_seats.py）：①`_meta` buy 成功 sell 抛异常 → `{rows:[...buy...], buy_ok:True, sell_ok:False}`；②`update_hot_money_seats` 残缺日跳过聚合（all_data 不含该日）；③`fetch_billboard_for_date` 仍返 list（向后兼容，既有 test_s079 测过）。

### R3 seal-intraday-cron-1500 覆盖（scheduled_tasks.py:2207-2218）
- [ ] R3.1 seed cron `* 9-14 * * 0-4` → `* 9-15 * * 0-4`（末次触发延至 15:59，`is_intraday_trading_time` 门 15:06+ 早返 skipped，collect_once 已实锤门在 em_get 前；6 次有用采集 15:00-15:05）。
- [ ] R3.2 修注释(2207-2208)为诚实表述：cron `* 9-15` 触发 09:00-15:59，实际写入由 `is_intraday_trading_time`(09:25-15:05) 门控，含 15:00 收盘集合竞价终态。
- [ ] R3.3 **既有 DB 迁移**：seed 仅 `if not in existing` 建任务，既有 DB 仍存旧 cron。加幂等更新：seed 块后 `if existing task seal_intraday_collect 的 cron_expr == "* 9-14 * * 0-4": update → "* 9-15 * * 0-4"`（对齐既有 cron 迁移范式，幂等）。
- [ ] R3.4 测试钉死（test_scheduled_tasks.py）：①fresh DB seed → cron=`* 9-15 * * 0-4`；②既有 DB 旧 cron `* 9-14` → 迁移后=`* 9-15`；③既有已是新 cron → 不重复迁移（幂等）。

### R4 backtest hit-rate degraded 诚实化（backtest_lite.py:65-92，§44 承重链）
- [ ] R4.1 加 `_calc_next_day_return_meta(code, date_str, kline_cache) -> tuple[float, bool]` 返 `(return_value, fetch_ok)`。fetch_ok=False on：无 bars / 日期未命中 / 异常。`_calc_next_day_return` 改调 `_meta` 返 float（!fetch_ok 返 0.0，向后兼容 5+ 调用方 + 测试 mock）。
- [ ] R4.2 `routers/win_rate.py:205,341` 切 `_meta`：`if not fetch_ok: degraded_kline_count+=1; continue`（**排除出 hit/miss 分母**，hit_rate 分母仅含 fetch_ok 样本）。
- [ ] R4.3 `prediction_verify.py:32` 切 `_meta`：!fetch_ok → 预测标 unverified（不计 miss）。
- [ ] R4.4 `generate_scatter_data`(backtest_lite.py:111) 切 `_meta`：!fetch_ok → 跳过该 point（不喂 hit_rate）。
- [ ] R4.5 `backfill_winrate_samples.py` 已 `float|None` 范式，**不动**（已诚实）。
- [ ] R4.6 测试钉死（新 test_s123_backtest_hitrate.py）：①`_meta` 成功→(0.05,True)；无 bars→(0.0,False)；日期未命中→(0.0,False)；异常→(0.0,False)；②win_rate 路径 !fetch_ok 样本排除出 hit_rate 分母（degraded_kline 计数，hit_rate=hit/(hit+miss) 不含 degraded）；③`_calc_next_day_return` 仍返 float 0.0（向后兼容，既有 test_s050/test_s054 mock 不破）。

### R5 storm-daemon news provenance（storm_daemon.py:40-71，LOW）
- [ ] R5.1 `fetch_snapshot` 加 `news_fetch_ok`/`news_is_degraded`（mirror global_indices:55-56）：`news_fetch_ok=bool(snap["news_items"])`，异常路径(69-71)同样置 False。
- [ ] R5.2 `_collect_news_factor`(storm_predictor.py:250) 读 `snap.get("news_fetch_ok")`：T-1 快照存在但 `news_fetch_ok=False`（快照 news 失败）→ `data_status='degraded'`（区分"无快照→fallback_current"）；快照 `news_fetch_ok=True` → 维持 ok。
- [ ] R5.3 测试钉死（新 test_s123_storm_news.py）：①`fetch_snapshot` news 失败→`news_fetch_ok=False/is_degraded=True` 落盘；②`_collect_news_factor` T-1 快照 news_fetch_ok=False → data_status=degraded（非 fallback_current）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/risk_models.py` | R1 _get_realtime_capital_flow 加 carry-forward date 校验 |
| `backend/strategies/hot_money_seats.py` | R2.1 加 _meta variant + R2.2 update_hot_money_seats 跳残缺日 |
| `backend/strategies/strategy_funnel_registry.py` | R2.4 切 _meta |
| `backend/scheduled_tasks.py` | R3 cron 改 `* 9-15` + 注释修诚实 + 既有 DB 幂等迁移 |
| `backend/backtest_lite.py` | R4.1 加 _calc_next_day_return_meta + R4.4 generate_scatter_data 切 _meta |
| `backend/routers/win_rate.py` | R4.2 切 _meta + 排除 degraded 出 hit_rate 分母 |
| `backend/prediction_verify.py` | R4.3 切 _meta + !fetch_ok 标 unverified |
| `backend/strategies/storm_daemon.py` | R5.1 加 news_fetch_ok/is_degraded |
| `backend/strategies/storm_predictor.py` | R5.2 _collect_news_factor 读 news_fetch_ok |
| `backend/tests/test_data_honesty.py` | R1.3 三测试 |
| `backend/tests/test_hot_money_seats.py` | R2.5 三测试 |
| `backend/tests/test_scheduled_tasks.py` | R3.4 三测试 |
| `backend/tests/test_s123_backtest_hitrate.py` | R4.6 新建三测试 |
| `backend/tests/test_s123_storm_news.py` | R5.3 新建二测试 |

> 测试文件分派**互不重叠**（R1→test_data_honesty / R2→test_hot_money_seats / R3→test_scheduled_tasks / R4→test_s123_backtest_hitrate 新建 / R5→test_s123_storm_news 新建），允许多 agent 并行 impl 不冲突。

## 5. 设计方案

**统一范式**：能走 `_meta` sibling 的（R2/R4）一律走，不改既有返回签名（向后兼容，blast radius 最小，对齐仓内 `_calculate_concentration_risk_meta`/`get_with_fallback_meta`）。R1（单值 date 校验）+ R3（cron 改）+ R5（加 provenance 字段）各自最小路径。

**R3 cron 选 `* 9-15` 而非"专项 15:00 task"**：`collect_once` 第一行 `is_intraday_trading_time` 早返在 em_get 之前（已实锤），15:06-15:59 的 54 次 no-op 触发是廉价门控检查不触 em_get（防封安全）。专项 task 方案（keep `* 9-14` + 加 `0-5 15` task）虽零浪费但需加 task type+executor 接线+迁移，KISS 否决。

**R4 hit_rate 诚实化用排除分母而非加 schema 字段**：`_calc_next_day_return_meta` 返 `(float, fetch_ok)`，!fetch_ok 样本**排除出 hit/miss 分母** + degraded_kline 计数（运维可见）。`backtest_daily_snapshots` 表不加 schema 字段（避免迁移），hit_rate 落盘值即诚实（degraded 不进分母）。对齐 `test_s050_shadow_comparison` 既有"K 线缺失排除 missed 桶"范式。

**R2 残缺日跳过聚合 vs 标 degraded**：聚合层（build_seat_profiles 60日画像）残缺日整日跳过（不纳入 next_day_sell_rate 分母）；单 code 单日（compute_seat_risk_factor）partial 用可用 rows best-effort + warning（不整日跳过，单日单 code 残缺不致画像系统性偏差）。

**R5 最小 provenance**：`news_fetch_ok=bool(items)`（与 global_indices `global_fetch_ok=bool(snap["global_indices"])` 对齐）。部分源失败（items 非空但残缺）fetch_radar 不暴露 per-source ok，无法检测——留后续 newsradar 加 per-source provenance 再深化（YAGNI，当前 empty vs non-empty 已闭合"快照 news 失败 vs 无快照"区分）。

## 6. 验收标准

- [ ] A1 R1：carry-forward（末条 date≠今日交易日）→ degraded+data_time=bar date；当日 → ok+now
- [ ] A2 R2：partial fetch（buy_ok≠sell_ok）→ 聚合跳过该日；`fetch_billboard_for_date` 向后兼容仍返 list
- [ ] A3 R3：fresh+既有 DB 均 cron=`* 9-15 * * 0-4`；注释诚实；迁移幂等
- [ ] A4 R4：!fetch_ok 样本排除出 hit_rate 分母；`_calc_next_day_return` 向后兼容返 float
- [ ] A5 R5：news 失败→news_fetch_ok=False 落盘；_collect_news_factor 据此标 degraded
- [ ] A6 全量 `pytest -m "not live" --deselect` 既有 flaky（newsradar/s032/spec_consistency/test_s040/test_market_degrades_without_akshare）0 回归
- [ ] A7 撒谎账本 26/26 全修（registry S123 节更新）

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐：5 条均诚实化修复（不臆造/不伪装 fresh/不压失效为真值），系统能力，无新方向建议
- [x] 判断可复现：纯代码逻辑 + 已抽验实锤；测试 mock 钉死（不依赖 live 数据）
- [x] 涨停四池/连板：本 spec 不涉个股呈现（#3 是时序采集完整性，非个股展示）
- [x] 私有数据：不涉
- [x] em_get 防封：R3 cron 扩 `* 9-15` 已实锤 `collect_once` 门在 em_get 前（防封安全）；R2 fetch_billboard 已走 em_get（S079 AC6，不改取数路径）

## 8. 测试计划

`pytest -m "not live"` + 14 新测试（R1.3×3 / R2.5×3 / R3.4×3 / R4.6×3 / R5.3×2）。`--deselect` 既有 flaky：
- `tests/test_fixes.py::test_market_degrades_without_akshare`（S122 网络 flaky）
- newsradar / s032 refresh / spec_consistency / test_s040 偶发 flaky（按 registry 既有集）

## 9. 风险与回滚

- **风险**：
  - R4 win_rate.py hit_rate 分母语义改→既有 win_rate 数值会变（degraded 排除后分母小，hit_rate 可能升/降）——这是**诚实化预期效果**（§44 让胜率为真），非回归；须在 PR 说明 "历史 hit_rate 数值因排除失效样本而变"。
  - R2 `fetch_billboard_for_date` 向后兼容包 _meta → 若 _meta 返 dict 被误当 list 用→严格测试钉死返回类型。
  - R3 既有 DB 迁移须幂等（旧 cron 才改，新 cron 不重复改）。
- **回滚**：每 R 独立 commit，可单独 revert。R1 撤 date 校验；R2 撤 _meta 用回 list；R3 cron 改回 `* 9-14`；R4 撤 _meta 用回 float；R5 撤 news_fetch_ok 字段。
