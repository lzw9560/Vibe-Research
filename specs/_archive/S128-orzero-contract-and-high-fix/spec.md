# Spec: S128 — or-zero 契约（NEVER_ZERO + CI lint）+ 3 HIGH 承重链 + 头条 MEDIUM

> 状态：已实现(2026-09-01)
> 作者：lzw9560  日期：2026-09-01
> 关联：S127 or-zero sweep（registry S127 节）3 HIGH + 头条 MEDIUM；S121（被 bidding_monitor 反吞）

## 1. 问题 / 目标

S127 or-zero sweep 扫 55 处 → 13 承重链 confirmed_lying。本 spec 实现契约级治理（NEVER_ZERO frozenset + CI grep-lint 防复发）+ 修 3 HIGH（bidding_monitor 反吞 S121→假交易信号）+ 头条 MEDIUM（limitup_screener seal_time→gene score 25% 权重 / intraday_sentiment→AI 出口）。其余 MEDIUM/LOW 登记 follow-up。

| # | crack | where | sev | 承重链 |
|---|---|---|---|---|
| 契约 | NEVER_ZERO frozenset + CI lint | mappers.py + scripts/ | - | 防未来 S121→consumer 反吞复发 |
| R1 | bidding_monitor 反吞 S121 | bidding_monitor.py:114-118 | HIGH | open_premium=0→"缩量平开"假交易信号 + market_cap=0→错 tier→错"爆量高开"阈值 |
| R2 | limitup_screener seal_time→gene score | models.py:115 | MEDIUM | seal_time None→0→avg_fbt=0→seal_rate=100(MAX 假封板率，25% gene 权重) |
| R3 | intraday_sentiment seal_rate/break_rate→AI 出口 | intraday_sentiment.py:116-117 | MEDIUM | break_rate None→0→break_score=100(假看涨)→sentiment score→AI 出口 |

## 2. 背景

- **S121 契约**：mappers.py:62,69,76-87,244,249,251-254,257 逐字段 `or None # 0 永不合法`（price/open/high/low/last_close/market_cap/pe_ttm/pb/ps_ttm/pcf_ttm/forward_pe/limit_up/down/pe_static/mcap_yi）。但**未成可查集合**，consumer 不知哪些字段不该 or 0。
- **R1 bidding_monitor**：:114-118 `model.{last_close,open,turnover,vol_ratio,market_cap} or 0` **反吞 S121 五字段 None→0** → :121 open_premium=0（last_close=0 guard）→ :166 `open_premium<0.01 and vol_ratio<1.0` → "缩量平开"信号从无数据触发。:118 market_cap=0→:149 _market_cap_tier(0)→错 tier→错 _AUCTION_THRESHOLDS→distort "爆量高开"。**在信号生成 chokepoint 反转已建立契约（S121 commit 8ff760f）。**
- **R2 limitup_screener**：:115 `fbt_values=[h.seal_time or 0 for h in history]`——seal_time (封板时间 fbt) fetched，_numf(models.py:17) '-'→None。None→0→:116 avg_fbt=0→:117 `(1-(0-92500)/(145000-92500))*100`=`(1-(-1.76))*100`=276→min(100)=**100(MAX 假封板率)**→seal_rate 25% 权重进 gene score（calc_total_score）→候选评分虚高→打板承重链。
- **R3 intraday_sentiment**：:116-117 `seal_rate/break_rate = float(emo.get(...) or 0)`——market.py:324-325 seal_rate/break_rate None 当源断。None→0→_compute_score：break_rate=0<0.15→break_score=100（假看涨）→sentiment score→AI 出口（chat.TOOLS）。**S093 R11 已为 zb_count/ladder/dt_count 立 None-passthrough（:122-124），seal_rate/break_rate 同文件未守约**。

## 3. 需求清单

### 契约 NEVER_ZERO + CI lint
- [ ] C1 mappers.py 模块级 `NEVER_ZERO: frozenset[str]` = {"market_cap","price","pe_ttm","pb","limit_up_price","limit_down_price","last_close","open","high","low","pe_static","ps_ttm","pcf_ttm","forward_pe","mcap_yi"}（从现有 `or None # 0 永不合法` 注释抽成可查集合，附 docstring 说明契约语义+consumer 不可 or 0）。
- [ ] C2 `scripts/check_or_zero_contract.py` CI grep-lint：扫全 backend .py，flag `model|quote|val|\w+\.(NEVER_ZERO 字段)\s+or\s+0` 模式（consumer 反吞 NEVER_ZERO 字段）。返非零退出码若发现违例。可 `python scripts/check_or_zero_contract.py` 手跑 + 留 CI wire 位（README 注释）。

### R1 bidding_monitor 不反吞 S121
- [ ] R1.1 bidding_monitor.py:114-118 不 `or 0`：若 `model.last_close/open/turnover/market_cap` 任一 None（quote 失败）→ snapshot 标 `data_status="degraded"` + critical 字段保 None（不造 0）。
- [ ] R1.2 analyze_final_auction(137+)：读 `snap.get("data_status")`，degraded → **不生成信号**（返 AuctionSignal type="无信号"/data_unavailable，reason "行情取数失败"），不喂 0 触发 "缩量平开"/错 tier。

### R2 limitup_screener seal_time 不 coerce 0
- [ ] R2.1 models.py:115 `fbt_values = [h.seal_time for h in history if h.seal_time is not None]`（排除 None 不 coerce 0）。若 `fbt_values` 空 → seal_rate=None（不 100 假封板率），标 data_status=missing 进 gene score（对齐 S111 data_status 范式）。
- [ ] R2.2 测试钉死：seal_time 全 None → seal_rate None/missing（非 100）；有值 → 正常算。

### R3 intraday_sentiment None-passthrough
- [ ] R3.1 intraday_sentiment.py:116-117 `seal_rate = emo.get("seal_rate")` / `break_rate = emo.get("break_rate")`（保 None，对齐 S093 :122-124 zb_count/ladder 范式）。
- [ ] R3.2 _compute_score 接 None seal_rate/break_rate：None → 该维度 neutral 50.0（非 0 假看跌/非 100 假看涨）+ 标 data_status=missing；有值 → 原 _score_dimension 逻辑。
- [ ] R3.3 测试钉死：break_rate=None → break_score=50 neutral（非 100 假看涨）；seal_rate=None → neutral。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/mappers.py` | C1 NEVER_ZERO frozenset |
| `scripts/check_or_zero_contract.py` | C2 新建 CI lint |
| `backend/bidding_monitor.py` | R1.1 不反吞 + R1.2 degraded skip signal |
| `backend/limitup_screener/models.py` | R2.1 seal_time None 排除 |
| `backend/routers/intraday_sentiment.py` + `_compute_score` | R3.1 None-passthrough + R3.2 neutral |
| 测试 | R1.2/R2.2/R3.3 钉死 + C2 lint 自测 |

## 5. 设计方案

**契约 3 层**（critic 策略）：(1) NEVER_ZERO frozenset=mappers 已 inline 声明的"0 永不合法"字段集合化；(2) CI grep-lint flag `\.({NEVER_ZERO})\s+or\s+0` 防未来 consumer 反吞；(3) fix 13 承重链站点（本 spec 修 3 HIGH + 2 MEDIUM，其余 follow-up）。

**R1 degraded skip**（非 or 0 造假信号）：quote 失败→snapshot degraded→analyze_final_auction 不生成信号（"无信号"+reason），对齐 portfolio R1（S125）+ position_advisor degraded skip 范式。

**R2 排除 None 不 coerce 0**：`[h.seal_time for h in history if h.seal_time is not None]`，空→seal_rate None+missing（非 100 MAX 假封板率）。对齐 S111 R6 `<=`→`==` 精确匹配"缺当日 bar 返 {}"范式（排除缺失不参与加权）。

**R3 None-passthrough + neutral 50**：对齐 S093 :122-124 zb_count/ladder None 保范式；_compute_score None→50 neutral（非 0/100 极端），对齐 sentiment_context._empty_context + storm 50.0 中性基线范式。

## 6. 验收标准

- [ ] A1 R1：quote 失败（字段 None）→ 不生成"缩量平开"/"爆量高开"信号（"无信号"+data_status=degraded）
- [ ] A2 R2：seal_time 全 None → seal_rate None/missing（非 100）
- [ ] A3 R3：break_rate None → break_score=50 neutral（非 100 假看涨）
- [ ] A4 C2 lint：跑 `python scripts/check_or_zero_contract.py` 0 违例（修后 bidding_monitor 等 or 0 消除）
- [ ] A5 全量 pytest 0 回归 + tsc 0 error

## 7. 合规与工程底线自查

- [x] 不臆造（None 不 coerce 0 造假信号/假封板率/假看涨）/ 可复现（纯代码+测试）/ 不涉个股/私有/em_get（不改取数路径）

## 8. 测试计划

`pytest -m "not live"` + R1.2/R2.2/R3.3 + C2 lint 自测。`--deselect` 既有 flaky 集。

## 9. 风险与回滚

风险：R1 analyze_final_auction degraded skip 可能漏真信号（但比假"缩量平开"安全，保守误差非 lie）；R3 _compute_score 改签名接 None 需查所有 caller；C2 lint 正则须覆盖 `model.X or 0`/`quote.X or 0` 多形态。回滚：各 R 独立 revert；NEVER_ZERO frozenset 删；lint 脚本删。
