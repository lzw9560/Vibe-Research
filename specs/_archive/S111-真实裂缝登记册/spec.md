# Spec: S111 — 真实裂缝登记册 + 打板风险承重链诚实化（Tier-1）

> 状态：已实现(2026-08-30，代码 R2-R8 + 10 测试落地、全量 2416 passed 无 S111 回归；改动在工作树未提交，仓库处 cherry-pick in-progress，待用户决定提交)
> 作者：lzw9560  日期：2026-08-30
> 级别：medium（Tier-1 承重切片：6 条直污打板 risk/score 的撒谎裂缝 + data_status 字段使能 + 登记册，碰 risk_models/fallback/eastmoney/first_board_filter，对齐 S103/S109 承重切片范式）
> 分支：待定（medium 级，off develop；若 review 判 large 则升 feature 分支 + grill + playwright 验收）
> 关联：grill「坚实数据底座」第 5 层 / S103+S109（缓存治理，第 1 层）/ S106+S108（孤儿接线，第 3 层）/ S104+S105（hithink 补源，第 4 层）/ S111 scan workflow（6 路扫描 + 综合 + 对抗核实，18 裂缝全档见同目录 `registry.md`）

## 1. 问题 / 目标

5 层底座第 1/3/4 层主体完成后，第 5 层「真实裂缝登记册」启动。S111 scan workflow（6 路并行扫描 + 综合 + 对抗核实）发现**远超预期**：不是原以为的 3 条诚实返空裂缝待登记，而是 **18 条裂缝里 14 条在静默撒谎**（全经对抗核实 confirmed_lying，代码实锤）+ 1 条诚实但崩(500，健壮性缺陷)。对抗核实起了作用：`premarket-selection-unguarded-cache-read` 原判"撒谎"，被 verify 查实为 loud crash（异常一路冒泡到 `app.py:255` 全局 handler 返干净 500，零替代数据），推翻归入"诚实但健壮性缺陷"——这正是对抗核实防的假阳性，差点把崩错当撒谎去缝补。

撒谎集中在 `risk_models` / `fallback` / `eastmoney` / `first_board_filter` / `gstock` / `extreme_market_detector` / `sector_divergence` / `newsradar`，把**断源 / 陈旧缓存 / 跨源降级**伪装成**实时中性信号或正常行情**，直接污染打板风险评分（risk_level / recommendation）、选股 score、情绪面板与天气熔断。

**根因高度集中**：`fallback.py:135-137` `get_with_fallback` 实时 fetch 失败时原样返 ≤TTL 缓存、返回值无 stale/degraded/from_cache 元数据，调用方无法区分 live 与缓存；下游还戳 `last_updated=now` 把陈旧标成"刚算完"。这一条根级联污染 6 个消费方（risk-trio + extreme + sector）。

**ethos**：坚实数据地基不缝补，绝不让数据源静默撒谎污染胜率/估值/打板信号（CLAUDE.md §1.2 工程底线：判断须可复现不臆造）。

**目标**：
1. 建登记册（活文档 + 可执行测试断言）把 18 条全入册
2. 修 Tier-1 承重链（6 条直污打板 risk/score 的撒谎裂缝 + data_status 字段使能）
3. 余 8 条撒谎裂缝 + 3 条诚实但健壮性/防封缺陷条目入册标"登记待后续切片"（Tier-2，承重切片范式）

> **⚠ 范围决策（待用户拍板）**：本 spec 取 Tier-1 承重切片（6 条），对齐 S103/S109 各做一片的范式。理由：一次 spec 修 14 条撒谎裂缝跨 10 文件 + 改 4 模型是大坑，承重切片更稳。若用户要全扫 14 条撒谎，升级为 large（feature 分支 + grill + playwright 验收）。其余开放问题见 §10。

## 2. 背景

### 诚实裂缝（3 条，仅登记）
| crack_id | where | 现状 |
|---|---|---|
| `fund-flow-120d-dual-break-honest-empty` | `eastmoney.py:432-467` | 东财双 host + 新浪都断→诚实返 []，撒谎发生在下游消费层 |
| `chip-breaker-permanent-no-recovery` | `akshare_src.py:149,184` | 手搓熔断永久 OPEN 返 {}（诚实但不可恢复，可用性悬崖，单列 Tier-2 修复项） |
| `chip-data-bypasses-generic-em-breaker` | `akshare_src.py:164` | 裸 requests 无 timeout/熔断（诚实 {} 但防封缺口，Tier-2 自建 cyq 走 em_get） |

### Tier-1 撒谎裂缝（6 条，全治，承重链）
| # | crack_id | where | 毒窗口 | 修法 |
|---|---|---|---|---|
| 1 | `fallback-get-with-fallback-stale-cache-as-fresh` | `fallback.py:135-137` | **根**：fetch 失败返缓存无 meta，6 消费方级联 | R2 旁路 `get_with_fallback_meta` 返 (data, meta{from_cache,is_stale}) |
| 2 | `realtime-capital-flow-stale-cache-mask` | `risk_models.py:473-488` | 陈旧缓存当实时资金流算 signal，last_updated=now 伪标 | R4 消费 meta→data_status=degraded，不戳 now，不返非零 signal |
| 3 | `risk-realtime-capital-flow-empty-as-neutral-signal` | `risk_models.py:492-498` | fetch 空+缓存也空→伪装中性 0.0 信号 | R4 空 history→data_status=missing 不伪装中性 dict |
| 4 | `fund-flow-120d-sina-cross-source-silent-substitute` | `eastmoney.py:464` | 东财断静默切新浪，无 source 标记，跨源口径混算 | R3 新浪降级路径加 source provenance |
| 5 | `chip-structure-stale-nearest-bar-fallback` | `first_board_filter.py:316` | `<=` 取邻近 bar，当日 bar 缺静默返昨日值打分 | R6 `<=`→`==` 精确匹配，缺当日 bar 返 {} |
| 6 | `risk-base-score-silent-50` | `risk_models.py:109-111` | bare `except:pass`→返 50.0，把故障压成中性先验 | R7 收窄 except / 裸失败设 data_status=missing |

### Tier-2 撒谎裂缝（8 条，入册待后续切片，全 confirmed_lying）
`risk-dragon-tiger-silent-zero` / `risk-seat-info-silent-empty` / `risk-concentration-silent-zero` / `sector-divergence-silent-empty` / `extreme-market-broken-zt-pool-as-normal` / `score-dim4-chip-silent-50-neutral-fallback` / `gstock-push2delay-permanent-latch-no-delay-flag` / `newsradar-cache-no-ttl-stale-as-fresh`。详情见 `registry.md`。

### 诚实但缺陷（3 条，Tier-2 健壮性/防封修复项，非性质修复）
`chip-breaker-permanent-no-recovery`（熔断不可自愈）/ `chip-data-bypasses-generic-em-breaker`（裸 requests 防封缺口）/ `premarket-selection-unguarded-cache-read`（裸读崩 500，verify 推翻撒谎指控，违 S069 优雅降级；附带 `scheduled_tasks.py:1860` 同型裸读）。

### 诚实化范式 gold standard（全仓已建，本 spec 复用不发明）
- `data_status: ok|missing|degraded` — `sentiment_context.py:45` / `intraday_features.py:84`
- source provenance — `kline_resolver.py:146` (bars, source_name) 元组 / `market._emotion data_source='ths_fallback'` (`market.py:260`)
- 精确匹配口径 — `_bar_close` 用 `==` 缺则跳过 (`scheduled_tasks.py:1885`)
- 缺失不参与加权 — `score_dim_turnover:1274` 返 -1.0 不加权
- 缓存 TTL/空不写 — `fallback.py` S046 `_is_empty` 空不写 + 损坏自愈
- S109 五段式承重切片表 / S110 测试断言对齐降级行为 (`2d29a14`) / health `{ok,detail}`+peek_state 只读 (S022)

### 受影响既有范式缺口
- `OneDayRisk` / `ExtremeMarketSignal` / `SectorDivergence` 模型无 `data_status` 字段
- `last_updated` 一律戳 now（`risk_models:218` / `extreme:164` / `sector:165`，4 处 grep 确认）

## 3. 需求清单
- [x] R1 建 `registry.md`（活文档，五段式表，18 条全入册：crack_id/where/毒窗口/is_honest_empty/needs_fix/状态/修法/fix-ref）
- [x] R2 `fallback.get_with_fallback` 加旁路 `get_with_fallback_meta(key,fetch,ttl,fallback)` 返 `(data, meta{from_cache,is_stale})`（渐进，不破坏既有 6 调用方签名）
- [x] R3 `eastmoney.stock_fund_flow_120d` 新浪降级路径加 source provenance（对齐 `kline_resolver` source_name）
- [x] R4 `risk_models._get_realtime_capital_flow` 消费 meta → `OneDayRisk.data_status=degraded/missing`，断源/陈旧不戳 `last_updated=now`，不伪装中性 dict
- [x] R5 `OneDayRisk` + `ExtremeMarketSignal` 模型加 `data_status: ok|missing|degraded` 字段（默认 ok，加性兼容，对齐 `sentiment_context:45`）
- [x] R6 `first_board_filter.extract_chip_structure` `<=`→`==` 精确匹配（对齐 `_bar_close:1885`），缺当日 bar 返 {}
- [x] R7 `risk_models.calculate_base_risk` 收窄 except / 裸失败设 `data_status=missing`（区分无 gene-score 中性先验 vs 取数故障）
- [x] R8 `backend/tests/test_data_honesty.py`（新）：Tier-1 每条加断言（源断 mock → missing/degraded，不戳 now，不返非零 signal）（对齐 S110）
- [x] R9 Tier-2 余 8 条撒谎 + 3 诚实但缺陷条目入册标"登记待后续切片"，给 fix-spec-ref 占位

## 4. 受影响文件
| 文件 | 改动 |
|---|---|
| `backend/fallback.py` | R2 加 `get_with_fallback_meta` 旁路（既有 `get_with_fallback` 零改动） |
| `backend/data/sources/eastmoney.py` | R3 `:464` 新浪降级加 source provenance |
| `backend/risk_models.py` | R4 `:473-498` 消费 meta + R7 `:109-111` 收窄 except + `OneDayRisk` 模型 R5 加 data_status |
| `backend/extreme_market_detector.py` | R5 `ExtremeMarketSignal` 模型加 data_status（为 Tier-2 extreme 铺路；Tier-1 不改 extreme 逻辑） |
| `backend/strategies/first_board_filter.py` | R6 `:316` `<=`→`==` |
| `specs/S111-真实裂缝登记册/spec.md` + `registry.md` | R1 新建 |
| `backend/tests/test_data_honesty.py` | R8 新建 |

## 5. 设计方案

三层结构，与既有范式直接衔接：

**L1 活文档（登记册本体）**：`registry.md` —— 照搬 S109 承重切片五段式表（crack_id / where / 毒窗口 / is_honest_empty / needs_fix / 状态[登记|修复中|已修] / 修法 / fix-spec-ref）。18 条全入册。活文档特性：比 spec.md 長命——S111 之后继续被后续切片追加 Tier-2/Tier-3 行。一条裂缝"已修" = L2 测试绿 + registry 行标状态，而非 spec 落地即闭。

**L2 可执行诚实门**：`test_data_honesty.py`（新）—— 一条 Tier-1 修复裂缝一条断言，断言源断（mock）→ 返 missing/degraded、不戳 last_updated=now、不返非零 signal。复用 S110 测试断言对齐降级行为范式。这是登记册的执行层 + 防回归——防止后续重构把诚实返空再改回静默兜底。

**L3 运行时可观测（可选/后续，YAGNI 不在 S111 核心）**：扩展 `routers/health.py` 加 `_check_data_honesty`（读 data_status 聚合），复用 `{ok,detail}`+peek_state 只读语义。仅在 R5 data_status 字段落地后才有数据可读，天然排在 Tier-1 之后。

**诚实化技术范式（全对齐仓内 gold standard，不发明新机制）**：
- 诚实返空口径：`data_status: ok|missing|degraded` → OneDayRisk/ExtremeMarketSignal/SectorDivergence 加此字段
- 来源 provenance：source_name 元组 / data_source 字段 → stock_fund_flow_120d 新浪降级 + gstock push2delay 加标记（后者 Tier-2）
- 精确匹配：`_bar_close` `==` → chip-structure `<=`→`==`
- 缺失不参与加权：`score_dim_turnover` -1 → score_dim4_chip 50→-1（Tier-2）
- 缓存 TTL/空不写：fallback S046 → newsradar load_cache 加 TTL（Tier-2）

**取舍**：
- `fallback` 用旁路新函数 `get_with_fallback_meta` 渐进迁移，不破坏 6 调用方签名（根因诚实化是加性，不应强制全量签名迁移）
- 前端暂不消费 data_status（YAGNI，后端先标诚实，前端 degraded 徽章待后续）
- 不抽离统一缓存工具（用户已判各源自治够）
- 不建独立 cracks/issues doc 体系（registry 作承重切片表延续即可，取代 ARCHITECTURE.md §"已知问题"分散登记角色并 cross-link）

## 6. 验收标准
- [x] A1 18 条全入 `registry.md`（4 诚实标 honest + 14 撒谎标 needs_fix，状态=登记；Tier-1 6 条修复后状态=已修）
- [x] A2 Tier-1 6 裂缝修复：源断 mock → `OneDayRisk.data_status=degraded/missing`，last_updated 不戳 now，capital_flow_signal 不基于陈旧算
- [x] A3 `stock_fund_flow_120d` 新浪降级返回带 source 标记（下游可见来源）
- [x] A4 chip-structure 请求日 bar 不在 cache → 返 {} 非昨日值
- [x] A5 `test_data_honesty.py` 全绿，断言源断 → 诚实 missing/degraded
- [x] A6 全量 `pytest -m "not live" --deselect test_s032_refresh_loop --deselect test_fetch_global_intel_wm_import_fails` 不回归（0 failed，对齐 S110 后基线 2407 passed）
- [x] A7 §44 胜率路径不受影响：断源仍剔除样本不进缓存（fund_flow_validation 直连 + proxy_pool）

## 7. 合规与工程底线自查（逐条确认）
- [x] 判断可复现不臆造：断源标 missing/degraded 不编值不兜底（核心，本 spec 就是让撒谎变诚实）
- [x] 私有数据隔离：无新增落盘 VR_DATA_DIR，registry.md 是文档非数据
- [x] em_get 防封：sina 是非东财源不走 em_get；chip cyq 后续自建走 em_get 在 Tier-2，本 spec Tier-1 不动 cyq
- [x] §44 口径：本 spec 不出 winrate/r/verdict，仅诚实化数据通道；A7 验证胜率路径不受污染
- [x] 研判/推荐属系统能力（弱合规）：本 spec 是数据通道诚实化，不新增研判输出，无新增风险提醒要求

## 8. 测试计划
- `pytest backend/tests/test_data_honesty.py`（新）
- 全量 `pytest -m "not live" --deselect test_s032_refresh_loop --deselect test_fetch_global_intel_wm_import_fails`（flaky 隔离，见 memory）
- 手动验收：停东财 push2his + mock 新浪也断 → `/api/limitup/analysis` 返 risk 带 `data_status=degraded` 而非伪 fresh

## 9. 风险与回滚
- `data_status` 字段加性兼容（默认 ok），前端不消费暂不影响展示，可分步上线
- `get_with_fallback_meta` 是旁路新函数，既有 6 调用方零改动，回滚 = 删新函数 + 还原 risk_models 消费
- chip-structure `==` 改动若致部分历史回放缺数据，回滚 `<=` 即恢复（但 `<=` 本身是 bug）
- 影响面 = 打板 risk / 选股 score，回滚后恢复原（撒谎）行为，不致崩

**实现后 review 补修（2026-08-30，详见 registry.md「实现后修复记录」）**：
- R7 narrowed except 漏 sqlite3.OperationalError → DB 故障 propagate 502（MEDIUM）→ 改 broad `except Exception`+log+missing + 测试钉死
- #4 source provenance 孤立、_get_realtime_capital_flow 不读 source → 跨源毒窗口仍开（LOW，关毒窗口）→ 消费 source→sina 标 degraded + 测试钉死，#4 uncertain→confirmed_honest
- get_with_fallback_meta bare `except:pass` 无日志（LOW）→ 加 debug log，原 get_with_fallback 保持零改动
- _with_source source 键泄漏到所有 fund flow API 响应（LOW）→ 延后 Tier-2（加性兼容无碍，前端可后续消费）

## 10. 开放问题（待用户拍板，scan workflow synthesis 提出）
1. **范围**：Tier-1（6 条，本 spec 默认）vs 全扫 15 条（升 large）——**最关键**
2. `data_status` 透传前端否？本 spec 默认后端先标、前端不消费（YAGNI）
3. fallback 旁路新函数（默认）vs 改签名全量迁移——默认旁路渐进
4. gstock latch 修法：per-call 重试 push2 vs 保留 latch 加 is_delayed 标记——Tier-2 再定
5. chip cyq 防封缺口自建走 em_get：Tier-2（本 spec 不动）
6. `score-dim4-chip` 50→-1：Tier-2 与 chip 权重回测校准同批（本 spec 不动）
7. registry 位置：`specs/S111/registry.md`（默认，随 spec）vs `backend/KNOWN_CRACKS.md`
8. baostock T+1 stuck-mark 7 日：不入册（reader 自判非裂缝），仅注意拖慢 §44 样本积累
