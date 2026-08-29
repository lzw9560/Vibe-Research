# Spec: S102 — 战法卡片运行时拼接历史战绩段

> 状态：草案
> 作者：lzw9560  日期：2026-08-29
> 关联：S100（战法卡片对齐）/ S052（strategy_backtest 12h 缓存）/ §44 口径（CLAUDE.md §1.2）

## 1. 问题 / 目标

`query_strategy_card` 当前只返回静态卡片文本（适用天气/核心逻辑/入场/退出/风险点），AI 三出口（chat/MCP/cli_runtime）解读战法时**看不到历史表现**——无法判断「这个战法过去 60 天到底赚不赚钱、样本够不够」。

目标：卡片查询时**运行时拼接**一段「历史战绩」（win_rate / avg_return / sample_size + §44 口径判定），让 AI 解读战法逻辑的同时拿到历史表现证据，且**不阻塞卡片查询热路径**（回测算一次 ~2min，卡片查询是高频调用，不能等）。

## 2. 背景

- 战法卡片静态文本在 `backend/strategies/cards/<code>.md`，`query_strategy_card`（`backend/ai/tools/strategy_tools.py`）读文件返回。
- 历史战绩已在 `backend/strategies/strategy_backtest.py` 的 `run_strategy_backtest(lookback_days=60)` 实现，结果带 12h 缓存（`_CACHE` / `_CACHE_TS` / `_CACHE_TTL=43200`），返回 8 战法各一个 `StrategyBacktestResult`（`strategy_code`/`win_rate`(0-1)/`avg_return`(百分比)/`sample_size`）。
- §44 口径（CLAUDE.md §1.2 + memory `section44-pre-conclusion-gate`）：出胜率/收益前须报 n + 样本不足判定；`win<50% 且 n>=30` 是战绩差的诚实标注，不是出 winrate/r/verdict 结论（本 spec 不出 r/lift/verdict，只标注口径，未 validated）。
- 卡片查询是 AI 解析战法的高频热路径（chat 每轮可能调）。

## 3. 需求清单

- [ ] R1 `query_strategy_card` 返回的 `card` 含「## 历史战绩」段（插在「## 风险点」段前，不破坏尾部风险提醒）
- [ ] R2 缓存命中：战绩段显 `胜率 X% · 均值收益 Y% · 样本 n` + §44 口径标注
- [ ] R3 §44 口径三态：`n<30` 标「样本不足，不下结论」（不标红）；`n>=30 且 win<50%` 标「⚠️ 战绩偏弱」；`n>=30 且 win>=50%` 标「历史正胜率」
- [ ] R4 缓存未命中：显「战绩计算中（首次查询触发，约 2min，12h 缓存后秒回）」+ **异步触发** `run_strategy_backtest(60)` 预计算填缓存，不阻塞本次返回
- [ ] R5 无样本（`sample_size=0` 或战法不在结果列表）：显「无样本（该战法在回测窗口内未命中）」
- [ ] R6 异步触发节流：同一战法 5min 内不重复触发（`_BACKTEST_TRIGGER_COOLDOWN=300`）
- [ ] R7 任何回测/导入失败不阻塞卡片查询（降级为不拼战绩段或显「待算」）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/ai/tools/strategy_tools.py` | 新增 `_build_backtest_section` / `_trigger_backtest_async` / `_insert_before_section`；`query_strategy_card` 调用拼接 |
| `backend/tests/test_s102_strategy_card_backtest.py` | 新增（已写，135 行，9 用例） |

## 5. 设计方案

**运行时拼接（非预生成落盘）**：卡片文本保持静态文件为单一事实源，战绩段在 `query_strategy_card` 调用时拼接——战绩随 12h 缓存刷新自动更新，无需改卡片文件。

**不阻塞热路径**：`_build_backtest_section` 先查 `_CACHE`，命中直接拼；未命中返「计算中」+ fire-and-forget 守护线程跑 `run_strategy_backtest(60)` 填缓存，下次查询命中。节流防同一战法高频查询重复触发。

**§44 口径标注（非出结论）**：本 spec 不出 r/lift/verdict，只标注 n + 三态判定 + 「未 validated」——符合 §44「报 n + 样本不足不下结论」要求，不触发 §44 的 lift<2x=噪声 gate（那是出 r/verdict 才需过的，本 spec 不出）。

**插入点**：`_insert_before_section(card, "风险点", section)`——找 `## 风险点` 段插其前；8 张卡片均有 `## 风险点` 段（已核实），找不到则追加末尾（兜底）。确保尾部风险提醒「历史统计特征，市场有风险，研究参考。」始终在末尾。

**备选不选**：
- 预生成落盘到卡片文件——否，战绩 12h 变，落盘需定时回写，双事实源。
- 同步等回测——否，卡片查询是热路径，~2min 阻塞不可接受。
- 战绩段放卡片尾部（风险点后）——否，风险提醒应在末尾收尾，战绩段插风险点前。

## 6. 验收标准

- [ ] A1 `pytest tests/test_s102_strategy_card_backtest.py -v` 9 用例全过（已验证 PASS）
- [ ] A2 真实缓存命中时 `query_strategy_card("first_plate")` 返回 card 含「## 历史战绩」+ 胜率/n + §44 口径
- [ ] A3 战绩段在「## 风险点」段前；尾部「研究参考。」仍在末尾
- [ ] A4 缓存未命中时不阻塞（秒回「计算中」）+ 后台异步填缓存
- [ ] A5 8 张卡片任一查不崩（dragon_head 尾部结构略不同也兜底）

## 7. 合规与工程底线自查

- [x] 研判属系统能力（2026-07-30 口径）；战绩段是历史统计特征呈现，挂「未 validated」+ 尾部风险提醒仍在
- [x] 可复现：win_rate/avg_return/n 来自 `run_strategy_backtest` 既定规则重算（读 gene_scores DB + K 线回测），非臆造；§44 口径标注 n，n<30 不下结论
- [x] 不出 r/lift/verdict 结论（只标口径），未触发 §44 lift gate
- [x] 涨停四池个股未直接呈现（战绩段只给聚合 win_rate/n，非个股名单）
- [x] 私有数据未进 git（读 `.vibe-research/` DB，未上传）
- [x] 无新增东财端点（回测走 astock/mootdx，非裸 requests）

## 8. 测试计划

- `pytest tests/test_s102_strategy_card_backtest.py -v`（离线，monkeypatch _CACHE，已 9 PASS）
- 真实回测冒烟：`run_strategy_backtest(60)` 填缓存后查 `query_strategy_card`（后台跑中，验证 A2/A3）
- 全量回归：`pytest -m "not live" --deselect tests/test_s032_refresh_loop.py --deselect` newsradar 联网测试（按 memory）

## 9. 风险与回滚

- **风险**：异步触发若 `run_strategy_backtest` 失败（DB 空/mootdx 断），缓存填不上——每次查询都返「计算中」+ 重复触发（5min 节流内不重复）。可接受：用户至少看到「计算中」而非崩；5min 节流防雪崩。
- **风险**：`_CACHE` 是模块级 dict，monkeypatch 测试改模块属性——已用 `monkeypatch.setattr(sb, "_CACHE", ...)` 处理。
- **回滚**：`query_strategy_card` 加 `backtest_section = ""` 一行即退回纯静态卡片；或删 `_build_backtest_section` 调用。

## 10. 冲突审查表

无历史 spec 冲突。S100（卡片对齐）只对齐静态卡片文本结构，本 spec 运行时拼接不改动静态文件，共存。S052 的 `_CACHE`/`run_strategy_backtest` 是复用非改动。
