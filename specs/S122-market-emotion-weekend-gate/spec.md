# Spec: S122 — market._emotion(date=None) 周末交易日历门控（不把周五池标成周六实时情绪）

> 状态：已实现(2026-08-31)
> 作者：lzw9560  日期：2026-08-31
> 关联：S118 scan #5 `market-emotion-realttime-weekend-silent-fallback-no-calendar-gate`（HIGH confirmed_lying, worth_fixing）

## 1. 问题 / 目标

S118 scan 判 `market-emotion-realttime-weekend-silent-fallback-no-calendar-gate` confirmed_lying：`market._emotion(date=None)`（market.py:216-225）实时分支 `for back in range(8)` 循环**无 `is_trading_day` 守卫**。`em_zt_topic_pool` 在非交易日查询时**静默回退返最近交易日池**（实测 08-21 周五/08-22 周六/08-23 周日三天查询均返字节级相同的周五 54 条涨停池）→ 周末 back=0 查周六即命中周五非空池 → `resolved="周六"` → 返 `{date:"周六", zt_count:54(周五的), max_boards/lianban_stocks:周五个股}`，**周五池标成周六实时短线情绪**，无 `is_delayed`/`trade_date` 标，下游无法区分。`_cached` 5min TTL 放大错位。

作者 line 162-163 注释声称 date=None 路径"只在有数据的交易日 resolve，不触发回退"——与同函数 line 155-157 实测 docstring 矛盾，推理错误被自身实证证伪。

目标：date=None 循环加 `is_trading_day` 跳过非交易日 + 盘前当日跳过，让 resolved 落到真实最近交易日（周末→周五），date 字段与池数据一致；对齐同函数 P0-2/P0-3 守卫 + 全仓既有范式。

## 2. 背景

- `em_zt_topic_pool` 静默回退：非交易日查询返最近交易日池（实测三处独立坐实：_emotion docstring 08-21/22/23、topology.py:129-131 注释、limitup/metrics.py:49-54 注释）。
- 全仓 `em_zt_topic_pool` 调用方均 `is_trading_day` 守卫（daily_review.py:135 / extreme_market_detector.py:120 / auction_screener.py:143 / routers/topology.py:134,331 / limitup_screener/service.py:514 / backfill_history.py:165）——**唯 market._emotion(date=None) 是裸漏的唯一缺口**。
- 同函数已有两守卫（仅 `if date is not None` 命中，date=None 实时路径不命中）：P0-2（line 177-189）守显式 date 非交易日、P0-3（line 191-201）守显式 date 盘前回退。
- `vr_paths.is_trading_day(d)`（vr_paths.py:78）+ `last_trading_date`（:113）既有 helper；market.py:180 已局部 import `is_trading_day`（date≠None 分支）。
- 实时入口：`routers/market.py:46 market_emotion()` → `market.py:350 get_short_term_emotion()` → `_cached("emotion", _emotion)` → `_emotion(None)`。

## 3. 需求清单

- [ ] R1 `market._emotion` date=None 循环（market.py:218-225）加守卫：`d = today - timedelta(days=back); if not is_trading_day(d): continue`（跳非交易日，防 em 静默回退误标周末）；`if back == 0 and datetime.now(BEIJING).hour < 15: continue`（盘前当日池未生成，em 回退 T-1 误标今日，对齐 P0-3）；其余不变。
- [ ] R2 同函数 ths 降级回退循环（market.py:228-237 `if not resolved:` 内）加同款 `is_trading_day` 跳过，防 ths_limit_up_pool 同型静默回退（一致性，未 confirmed 但同 pattern）。
- [ ] R3 `is_trading_day` 在 else 分支 import（对齐 line 180 局部 import 范式）。
- [ ] R4 测试钉死：①周末（mock today=周六 + em 返周五池 on 周六查询）→ _emotion(None) 返 `date=周五`（非周六）；②盘前交易日（mock hour<15）→ resolved=昨日（T-1），date=昨日；③交易日盘后（hour≥15）→ resolved=今日，date=今日。
- [ ] R5 全量 `pytest -m "not live" --deselect` newsradar/s032/spec_consistency 0 回归（test_s040 偶发 flaky 非本 spec）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/market.py` | _emotion date=None 循环 + ths 回退循环加 is_trading_day 跳过 + 盘前当日跳过 + import |
| `backend/tests/test_fixes.py` 或 market 测 | R4 三测试钉死（mock datetime.now + em_zt_topic_pool） |

## 5. 设计方案

**逐迭代加 is_trading_day 跳过**（verify 提案）而非"计算 last_trading_date 后单查"：逐迭代复用既有 `for back in range(8)` 结构 + 与同函数 P0-2/P0-3 + 全仓 6 处守卫范式一致；`last_trading_date` 单查方案否决（绕过 em 的"最近有数据日"语义——长假后首日 em 可能仍空，逐迭代能继续回溯到有数据日，单查 last_trading_date 则不可）。

盘前阈值 `hour < 15`：涨停池是收盘数据集，15:00 后生成；< 15:00 em 返 T-1（实测 08-21 盘前返 08-20 的 79 条）。对齐 P0-3。

备选加 `is_delayed`/`data_status` 字段：date 字段修对后已可辨"哪日数据"，is_delayed 是额外语义（registry 提"返 stale 或标 is_delayed"，本 spec 选"返 stale + date 诚实"最小路径）；留后续若下游需"陈旧度"再加。

## 6. 验收标准

- [ ] A1 周末（周六）_emotion(None) → `date=周五`（非周六），池数据=周五的
- [ ] A2 盘前交易日（hour<15）→ `date=昨日`（T-1，非今日）
- [ ] A3 交易日盘后（hour≥15）→ `date=今日`
- [ ] A4 长假 8 日全非交易日 + em 空 → 仍走 ths 回退（不崩），resolved 诚实
- [ ] A5 全量 pytest 0 回归

## 7. 合规与工程底线自查

- [x] 研判/推荐：date 字段诚实标真实数据日（周五/昨日），不伪装周末实时；系统能力，无新方向建议
- [x] 判断可复现：纯代码逻辑 + 实测 docstring 坐实 em 静默回退；测试 mock 钉死
- [x] 涨停四池/连板：本修复让 lianban_stocks 的 date 标对（公开榜单个股属客观事实，date 诚实呈现）
- [x] 私有数据：不涉
- [x] em_get 防封：em_zt_topic_pool 已走 em_get 限流（本 spec 不改取数路径，仅加日期守卫）

## 8. 测试计划

`pytest -m "not live"` + R4 三测试（mock `datetime.now(BEIJING)` + `astock.em_zt_topic_pool`）。`--deselect` 既有 flaky（newsradar/s032/spec_consistency；test_s040 偶发 flaky 非本 spec）。

## 9. 风险与回滚

- **风险**：mock datetime.now 测试隔离（freezegun 不可用则 monkeypatch market.datetime）；is_trading_day 依赖 trading_calendar.json（既有，vr_paths 已用）。
- **回滚**：循环改回原 `d = (today - timedelta(days=back)).strftime(...)` 无守卫（一行）。
