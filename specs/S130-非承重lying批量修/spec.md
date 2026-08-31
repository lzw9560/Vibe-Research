# Spec: S130 — 非承重 confirmed_lying 批量修（conc/dt factors + market/sentiment_weather or-0）

> 状态：待实现
> 作者：lzw9560  日期：2026-09-01
> 关联：S129 critic residual（conc/dt factors-text）+ S127 or-zero sweep 残留（market.py or-0 / sentiment_weather:1174 or-0）。均非承重链 M/LOW，registry 撒谎账本"4 待修"内。本 spec 闭合 3 项；lockup-expiry + concept_blocks + em-zt-topic-pool 下游属 #6 em_get 消费者维度，留 S131（scan 确认后）。

## 1. 问题 / 目标

3 条非承重 confirmed_lying，不同文件，可并行 impl：

| # | crack | where | sev | 撒谎机制 |
|---|---|---|---|---|
| 1 | conc/dt factors-text blind-to-status | risk_models.py:632,:646 | MEDIUM | `_build_risk_factors` 对 `dt_status`/`conc_status` 盲——dt/conc fetch 失败→0.0→`dragon_tiger_risk>30`/`concentration_risk>60` 恒假→factor 静默不报→走"当前风险因素较少"兜底（S129 critic residual：trio 已修，conc/dt 同款盲态留此 spec） |
| 2 | market.py lianban_stocks or-0 | market.py:313,:314,:319 | LOW | `lianban_stocks` 喂 AI：`price=(_numf(p.get("p")) or 0`/`pct=... or 0`/`amount=... or 0`——缺失字段→0.0 当真价 0/涨跌 0/额 0 喂 LLM（对齐 S121 tencent 0→None 范式，0→None 让 AI 见 null 辨缺失） |
| 3 | sentiment_weather:1174 MA or-0 | routers/sentiment_weather.py:1174 | LOW | `closes=[float(b.get("close") or 0) for b in bars]`——缺失 close→0→均价偏低→`below_ma` 判定错（exit signal 承重链，但 §44 已降参考性，且 try/except 兜底 ma_price=None） |

**严重度**：均非 risk_score 腐败（#1 trio 不进 risk_score，S129 实锤；#2/#3 是 display/signal 字段）。#1 的 data_status 已 backstop（conc/dt 进 _merge_data_status，S129 critic 确认），本 spec 只补 factors-text 诚实；#2/#3 是 or-0→None/过滤 范式。全非承重链。

**目标**：3 条全修，每条加测试钉死，全量 pytest 0 回归。

## 2. 背景

- **#1**：S129 R3 给 `_build_risk_factors` 加了 `vol_status/dd_status/liq_status`（trio 失败显"数据缺失"），但 `conc_status`/`dt_status` 未传（S129 spec §5 登记 residual）。本 spec 补：签名加 `conc_status="ok"`/`dt_status="ok"`，调用处 :202-214 传，factor 条件改 status 感知。
- **#2**：S121 `mappers.quote_from_tencent` 已立 `0→None` 范式（"0 永不合法"字段 `or None`）。market.py lianban_stocks 同款但未修（S127 sweep 列 5 待修）。`lianban_stocks` 是公开榜单（弱合规下可如实呈现个股），但 price/pct/amount 缺失应 `None` 非 `0`。
- **#3**：`b.get("close") or 0` 在 MA 计算（EXIT_SIGNAL_MA_DAYS 日均价）——个别 bar 缺 close→0 拉低均价。修法：过滤 None close（`[float(b["close"]) for b in bars[-N:] if b.get("close") is not None]`）+ 不足 N 则 ma_price=None（已 try/except 兜底）。

## 3. 需求清单

### R1 conc/dt/seat/cf factors-text status 感知（risk_models.py:610-654，S129 critic residual + scan #3 finding #1 扩展）
- [ ] R1.1 `_build_risk_factors` 签名加 `conc_status: str = "ok"` + `dt_status: str = "ok"` + `seat_status: str = "ok"` + `cf_status: str = "ok"`（默认 ok 向后兼容；scan 实锤不只 conc/dt，seat+cf 同款盲态——dt/conc 失败→0.0→`>30`/`>60` 恒假；seat 失败→multi_seat_signal=False；cf 失败→trend="震荡"→`=="流出"` 假，四维 factor 全静默→"较少"）。
- [ ] R1.2 四 factor 条件改 status 感知（对齐 S129 R3 trio 范式 `if X_status in ("degraded","missing"): factors.append("X数据缺失") elif 原条件: 原文本`）：dt（"龙虎榜数据缺失" / `dragon_tiger_risk > 30`）、conc（"席位集中度数据缺失" / `concentration_risk > 60`）、seat（"席位数据缺失" / `multi_seat_signal`）、cf（"资金流数据缺失" / `capital_flow_trend == "流出"`）。
- [ ] R1.3 调用处 :202-214 传 `conc_status=conc_status, dt_status=dt_status, seat_status=seat_status, cf_status=cf_status`（变量已在 :186 dt, :189-193 seat, :199 conc, :215 cf 解构，S129 只传了 trio）。
- [ ] R1.4 测试钉死：①conc missing→"席位集中度数据缺失"；②dt degraded→"龙虎榜数据缺失"；③seat missing→"席位数据缺失"；④cf missing→"资金流数据缺失"；⑤全 ok+超阈→原文本不破；⑥四维全 missing→factors 含四"数据缺失"非"较少"。

### R2 market.py lianban_stocks or-0→None（market.py:313-319）
- [ ] R2.1 `price`/`pct`/`amount` 三字段 `or 0` → `or None`（`astock._numf(...) or None`，0.0 falsy→None，真值不变，对齐 S121）。`float_cap`/`industry` 不动（非 0-lying）。
- [ ] R2.2 排序 key `-(x["amount"] or 0)` → `-(x["amount"] or 0)` 保留（sort 需数值，None→0 排序兜底可接受，非呈现字段；或 `-(x["amount"] or -inf)` 把缺失排尾——择 KISS 保 `or 0`）。
- [ ] R2.3 测试钉死（新 test_s130_market_lianban.py）：①bar 缺 price（`p` 缺）→ `price is None`（非 0）；②真值不变（`19.92 or None`=19.92）；③排序不崩（amount=None 排序兜底）。

### R3 sentiment_weather MA or-0 过滤（routers/sentiment_weather.py:1174）
- [ ] R3.1 `closes = [float(b.get("close") or 0) for b in bars[-EXIT_SIGNAL_MA_DAYS:]]` → 过滤 None：`closes = [float(b["close"]) for b in bars[-EXIT_SIGNAL_MA_DAYS:] if b.get("close") is not None]`（不把缺失 close 当 0）。
- [ ] R3.2 `ma_price = sum(closes)/len(closes) if closes else None`——已 `if closes` 兜底，过滤后 closes 空则 None（原 `or 0` 时 closes 恒非空因 0 填充，现需显式 None 兜底，已存在）。
- [ ] R3.3 测试钉死（新 test_s130_sentiment_weather_ma.py）：①bars 含 1 个 None close → ma_price 只用非 None bar 算（不被 0 拉低）；②全 None close → ma_price=None（below_ma 不触发）；③全有效 close → 原行为不变。

### R4 registry + 回归
- [ ] R4.1 registry 加 S130 节标注 3 条闭合（conc/dt factors + market or-0 + sentiment_weather MA or-0）。
- [ ] R4.2 全量 `pytest -m "not live"` 0 回归（gate 应仍 2503 passed + 本 spec 新测）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/risk_models.py` | R1 `_build_risk_factors` 加 conc_status/dt_status + status 感知 + 调用处传 |
| `backend/market.py` | R2 lianban_stocks price/pct/amount `or 0`→`or None` |
| `backend/routers/sentiment_weather.py` | R3 MA close 过滤 None |
| `backend/tests/test_s129_risk_trio_provenance.py` 或新 `test_s130_*.py` | R1.4/R2.3/R3.3 测试 |
| `specs/S111-真实裂缝登记册/registry.md` | R4.1 S130 节 |

> R1/R2/R3 不同文件，可并行 impl（无冲突）。lockup-expiry/concept_blocks/em-zt-topic-pool 下游 + #3/#5/#6 scan 确认项留 S131。

## 5. 设计方案

**R1 对齐 S129 R3 范式**：trio 已加 status 感知，conc/dt 同款补。`_build_risk_factors` 签名再加 2 status 参数（conc/dt），factor 条件 if-status-then-"数据缺失"-elif-threshold-原文本。调用处传 conc_status/dt_status（变量已存在 :186,:199）。

**R2 对齐 S121 `or None` 范式**：`_numf(x) or None`——0.0 falsy→None、真值不变、None→None 三态正确。lianban_stocks 是公开榜单可如实呈现（弱合规），但缺失字段 0 当真价 0 喂 LLM 是 lie，0→None 让 AI 见 null 辨缺失。排序 key 保 `or 0`（排序需数值，非呈现，KISS）。

**R3 过滤非 coerce**：MA 计算 bar 缺 close 时，过滤（不纳入均价）比 coerce-0（拉低均价）诚实。已 try/except + `if closes` 兜底，过滤后 closes 空显式 None。

**scope 守 3 项非承重**：lockup-expiry（间接 em_get 消费者）+ concept_blocks + em-zt-topic-pool 下游 + #3 顶层聚合 + #5 AI工具 + #6 em_get 消费者——留 S131（scan wf_wyjag35s5 确认后起草），不在本 spec。

## 6. 验收标准

- [ ] A1 R1：conc/dt 失败→factors 显"数据缺失"非"较少"；ok+超阈→原文本不破
- [ ] A2 R2：lianban_stocks 缺 price→price=None（非 0）；真值不变；排序不崩
- [ ] A3 R3：bars 含 None close→ma_price 只用有效 bar；全 None→None
- [ ] A4 全量 `pytest -m "not live"` 0 回归
- [ ] A5 registry S130 节 3 条闭合

## 7. 合规与工程底线自查

- [x] 不臆造：#1 conc/dt 失败显"数据缺失"非"较少"；#2 缺失 0→None 非 0 当真；#3 缺失 close 过滤非 coerce 0
- [x] 判断可复现：纯代码 + 测试 mock 钉死
- [x] 私有数据：不涉
- [x] em_get 防封：不涉（#2 用已取的 zt pool，#3 用 astock.kline mootdx，#1 纯 factors）
- [x] §44：均非 risk_score/胜率数字承重链；#1 data_status 已 backstop，#2/#3 display/signal 字段

## 8. 测试计划

`pytest -m "not live"` + 新测（R1.4 四测 / R2.3 三测 / R3.3 三测 ≈ 10 测）。

## 9. 风险与回滚

- **风险**：R2 `or None` 若前端 lianban_stocks 渲染不处理 null → 显示空（但前端 S126 已做 winrate=0→"数据缺失"诚实渲染，price=null 应已兜底；须 PR 说明）。R3 过滤后 closes 不足 N → ma_price=None → below_ma 不触发（保守，非 lie）。
- **回滚**：R1 撤 conc/dt status 参数（默认 ok 不破）；R2 `or None` 改回 `or 0`；R3 过滤改回 `or 0`。
