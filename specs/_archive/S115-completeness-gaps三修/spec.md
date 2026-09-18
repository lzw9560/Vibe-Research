# Spec: S115 — completeness-gaps 扫描 + 三撒谎修复（Layer 5 续扫）

> 状态：已实现(2026-08-30，代码 R1-R3 + 3 测试 + #4 fixture 对齐 + R3 logging，全量 2437 passed 无 S115 回归；改动在工作树未提交)
> 作者：lzw9560  日期：2026-08-30
> 级别：medium（S115 scan 扫 registry 未覆盖维度发现 18 裂缝，3 confirmed_lying 修 + 15 登记）
> 分支：develop
> 关联：S111-S114（Layer 5 主体收口 485c5cc）/ `registry.md`「本轮未覆盖维度」/ S115 scan workflow（wf_fe0ad61d，18 agent）

## 1. 问题 / 目标

S111-S114 修完 14 撒谎 + 3 诚实缺陷项，Layer 5 主体收口。registry「本轮未覆盖维度」登记 8 个未扫维度。S115 scan（7 路 + 综合 + 对抗核实，wf_fe0ad61d）扫这批维度，发现 **18 条裂缝**：

- **3 confirmed_lying**（对抗核实坐实，本 spec 修）
- **6 actually_honest**（合成 over-claim 撒谎，verify 推翻为诚实返空非 fabricate——防住 6 假阳性缝补）
- **1 uncertain**（gstock 周末日历，语义缺口非 lie）
- **8 honest_already**（多 worker/cron 时序竞态 latent，当前单 worker 诚实，登记）

**目标**：修 3 confirmed_lying（honesty 承重），15 非撒谎登记入册（诚实/latent/语义缺口）。

ethos：坚实数据地基不缝补，不让数据静默撒谎污染 AI 研判/胜率/打板信号。

## 2. 背景（scan + verify 结论）

**3 confirmed_lying**（verify 推翻失败，代码实锤撒谎）：

| # | crack_id | where | 毒窗口 | 修法 |
|---|---|---|---|---|
| 1 | `first-board-settlement-t0-bar-lte-fallback` | `backend/strategies/first_board_settlement.py:524` | `<=` 取邻近 bar 当 signal_date 当日 open 算 t1_return_pct；缺当日 bar（停牌/新股缺口/baostock 缓存未含）静默用前一个 bar（可能数日/周前）→ wildly wrong return_pct 喂 lift/胜率/verdict（§44 承重链） | `<=`→`==` 精确匹配（对齐 S111 R6 _bar_close），缺当日 bar→t0_bar=None→t1_return_pct=None 跳过；记录 t0_date provenance |
| 2 | `sina-fallback-no-min-bars-maxabs-drift` | `backend/data/sources/eastmoney.py:475` | 东财路径有 len>=5 门（:466），新浪降级路径无门；新浪返 1-4 条当 120d 历史，risk_models 在退化序列算 max_abs→signal 满格 ±1.0→adjustment=-signal×20 扭曲 risk_level ~25× | 新浪降级路径加对称 len>=5 门（<5 返 [] 落回 risk_models not history→missing），对齐东财 |
| 3 | `storm-predictor-internal-null-sti-as-zero-calm` | `backend/strategies/storm_predictor.py:162` | STI 降级日列 NULL（写侧诚实 source_ok=0 标记），storm_predictor `if ... is not None` 漏 NULL→保持 0.0+data_status='ok'，降级日看起来像真平静日→内部因子(权重0.35)假性偏低→风暴概率低估→suggested_position 偏高 | NULL 列/source_ok=0/no-row → data_status='missing' + score 50.0（中性基线，函数已用），非 0.0+ok |

**6 actually_honest**（verify 推翻，登记非修）：
- `hithink-trio-bare-empty-on-source-failure`：hithink 源断返 [] 是诚实空（6 处 logger.warning + breaker.record_failure），非 fabricate。可选增强（非必须）：返 `{"unavailable":...}` 让 LLM 区分源宕 vs 真无
- `query-quote-bare-empty-on-tencent-soft-failure`：tencent 软故障返 {} 诚实（S109 空不缓存+立即重试），正确瞬态故障处理
- `mcp-iserror-false-on-bare-empty`：isError=False 是 labeling 限制非 fabrication（bare empty 透传真实空，无替代数据）。可选：扩 is_error 覆盖 bare empty
- `storm-predictor-global-discards-is-delayed`：storm 用真实 change_pct + 诚实标 missing/fallback_current；is_delayed 不传但 15min 延时对隔夜 T-1 快照无实质影响
- `storm-daemon-snapshot-no-provenance-last-write-wins`：**诚实但 defect**——storm_predictor 检测空+fallback_current 标签（诚实），但 last-write-wins 遮蔽好快照是可用性缺陷（verify 称"worth fixing independent of lying"）。**登记为诚实但缺陷，待 availability 切片或顺手修**（provenance marker + 过滤坏快照）
- `portfolio-realtime-pnl-no-calendar-gate`：周末返周五收盘是真实最新价（市场闭，最新=周五收盘）非伪造；updated=_now() 是计算时刻非伪造。可选 UX（market_closed 字段）

**1 uncertain**：
- `gstock-us-hk-no-calendar-gate`：周末返周五收盘 + is_delayed=False（无 trade_date 字段），live API 消费者无法区分"周五收盘"vs"今日实时"；但非 fabricate（fetch 失败返 None）。storm 读 T-1 快照正确（周五收盘是周一盘前隔夜信号）。语义缺口非 lie，可选修（gstock 请求 f86 date + surface trade_date）

**8 honest_already**（latent，登记）：
- `fallback-mem-shadows-disk-and-ts-provenance` / `funnel-mem-shadows-db`（多 worker 缓存分叉，当前单 worker 诚实，扩 gunicorn -w N 前必修）
- `premarket-funnel-cache-fdate-offbyone`（S101 整式空转，诚实但致系统降级）
- `first-board-filter-kline-race` / `forward-test-daily-gene-scores-race` / `forward-test-t1-settle-baostock-race` / `first-board-t1-review-kline-sametick`（cron 时序竞态，诚实空但结构竞态致相关任务系统性降级/空转；共同根因 baostock 当日 EOD 可得时点未定）
- `baostock-t1-stuck-mark-7d-slows-section44-lift`（§44 样本偏，诚实仅登记，§44 问题非工程底线，动否用户拍）

## 3. 需求清单

- [x] R1 `first_board_settlement.py:524` `<=`→`==` 精确匹配 signal_date，缺当日 bar→t0_bar=None→t1_return_pct=None 跳过（不取邻近 bar 冒充）；记录 t0_date/t1_date provenance
- [x] R2 `eastmoney.py:475` 新浪降级路径加对称 len>=5 门（<5 条返 []，落回 risk_models not history→missing 诚实返空），对齐东财 :466
- [x] R3 `storm_predictor.py:162` STI NULL 列/source_ok=0/no-row → data_status='missing' + score 50.0（中性基线），非 0.0+ok 假平静
- [x] R4 测试：3 条各一断言（#1 缺当日 bar→t1_return_pct=None 非邻近 bar 值；#2 sina<5 条→不进 signal；#3 NULL 列→missing+50.0 非 0.0+ok）
- [x] R5 15 非撒谎登记入 registry（6 honest + 1 uncertain + 8 honest_already）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/first_board_settlement.py` | R1 `<=`→`==` + t0_date provenance + None 跳过 |
| `backend/data/sources/eastmoney.py` | R2 新浪路径 len>=5 门 |
| `backend/strategies/storm_predictor.py` | R3 NULL→missing+50.0 |
| `backend/tests/test_data_honesty.py` | R4 扩 3 断言 |
| `specs/S111-真实裂缝登记册/registry.md` | R5 登记 15 非撒谎 + S115 状态节 |
| `specs/S115-completeness-gaps三修/spec.md` | 本 spec |

## 5. 设计方案

3 confirmed_lying 修复全对齐仓内 gold standard：R1 `==` 精确匹配（S111 R6 _bar_close:1885 范式）；R2 min-bars 门（东财 :466 对称）；R3 missing+中性 50.0（storm_predictor 自身已用 50.0 for acknowledged-missing + sentiment_context data_status 范式）。

15 非撒谎登记（诚实/latent/语义缺口），不修——避免过度报警（多 worker latent 当前单 worker 诚实；cron 时序竞态诚实空但结构竞态致降级，与诚实修复分开排期；§44 样本偏是 §44 问题非工程底线）。storm-daemon #7 诚实但 defect（last-write-wins 遮蔽），登记为待 availability 切片（provenance marker + 过滤坏快照，耦合 storm_predictor #3 同 cluster 可顺手）。

## 6. 验收标准

- [x] A1 first-board-settlement 缺当日 bar→t1_return_pct=None（非邻近 bar 冒充），t0_date provenance 记录
- [x] A2 sina 降级返<5 条→不进 max_abs/signal（落回 missing）
- [x] A3 storm NULL 列→data_status='missing'+score 50.0（非 0.0+ok）
- [x] A4 test_data_honesty 扩 3 断言全绿；全量 pytest 不回归（对齐 2434 passed 基线）
- [x] A5 15 非撒谎登记入 registry
- [x] A6 §44 胜率路径：#1 修后断源/缺 bar 不再喂错误 return_pct（A1 钉死）

## 7. 合规与工程底线自查

- [x] 不臆造（3 修复都让撒谎变诚实：缺 bar→None / <5 条→空 / NULL→missing）
- [x] 私有数据隔离（无新增落盘）
- [x] em_get 防封（本 spec 不动 em_get 端点）
- [x] §44 口径（#1 直污 §44 承重链 return_pct，修后断源/缺 bar 不喂错误 ret；本 spec 不出 winrate/r/verdict）

## 8. 测试计划

`pytest tests/test_data_honesty.py`（扩 3）+ 全量 `pytest -m "not live" --deselect test_s032_refresh_loop --deselect test_fetch_global_intel_wm_import_fails`。

## 9. 风险与回滚

R1 `==` 改动若致部分历史 signal_date（baostock 缓存未含该日）返 None 跳过——是诚实（非邻近 bar 冒充），回滚 `<=` 恢复（但 `<=` 是 §44 撒谎）。R2 sina 门若致新浪降级更频繁返空——是诚实（<5 条非有效历史）。R3 NULL→missing 若致风暴概率变化——是诚实（降级日非真平静）。影响面=§44 胜率(#1)/risk_level(#2)/仓位(#3)，回滚恢复撒谎不致崩。

**开放问题**（scan open_questions，待用户拍）：
- baostock 当日 EOD 可得时点（cron 时序竞态共同根因，需实测统一后移 kline 消费者 cron）
- 多 worker 缓存何时硬化（当前单 worker 诚实 latent，扩 gunicorn 前必修）
- baostock stuck-mark 7 日（§44 样本偏，动否用户拍）
- storm-daemon #7 last-write-wins（诚实但 defect，availability 切片或顺手修）
- premarket off-by-one（诚实但致 S101 空转，提 medium 级立即修 f_date/t_date 还是仅登记）
