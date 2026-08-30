# Spec: S112 — Tier-2 撒谎裂缝诚实化（S111 承重切片续）

> 状态：已实现(2026-08-30，代码 R1-R9 + 18 测试落地、全量 2424 passed 无 S112 回归；改动在工作树未提交)
> 作者：lzw9560  日期：2026-08-30
> 级别：medium（8 条撒谎裂缝跨 6 文件，honesty 承重续切片，对齐 S111 Tier-1 范式）
> 分支：develop（medium，off develop）
> 关联：S111（真实裂缝登记册，Tier-1 已实现 ed2a84c）/ `registry.md`（18 条全档，Tier-2 8 撒谎 + 3 诚实缺陷项 修法已列，本 spec 不重复）/ grill「坚实数据底座」第 5 层

## 1. 问题 / 目标

S111 Tier-1 修了 6 条承重链（资金流陈旧/跨源 + chip-structure + fallback 根 + base-score）+ data_status 字段使能，余 **8 条撒谎裂缝仍开**。本切片修这 8 条——risk-trio silent-zero + extreme/sector silent-empty + score-dim4-chip 50→-1 + gstock latch + newsradar TTL。

risk-trio（dragon_tiger/seat/concentration）级联自 fallback 根（S111 R2 已修 `get_with_fallback_meta`），本切片让它们消费 meta 或加 data_status + logger，关 silent-zero 毒窗口。extreme/sector 同 silent-empty 模式。score-dim4-chip latent 50→-1（防 chip 权重启用即引爆）。gstock 永久 latch 加 is_delayed 标记。newsradar load_cache 加 TTL。

ethos 同 S111：坚实数据地基不缝补，不让数据源静默撒谎。

## 2. 背景

每条裂缝的 what_breaks / 修法 / 范式引用见 `registry.md` Tier-2 节（不重复）。诚实化范式同 S111：`data_status:ok|missing|degraded`、source provenance、精确匹配、缺失不加权、缓存 TTL/空不写。Tier-1 已建 `get_with_fallback_meta` 旁路 + OneDayRisk/ExtremeMarketSignal data_status 字段，本切片复用。

## 3. 需求清单（修法详 `registry.md`，此列仅 scope）

- [x] R1 `risk_models._get_dragon_tiger_risk` 0.0→data_status=missing + logger（对齐 :347/:371/:391 warning sibling；级联自 fallback 根，消费 meta 或加 data_status）
- [x] R2 `risk_models._get_seat_info` 空 dict→data_status=missing + logger
- [x] R3 `risk_models._calculate_concentration_risk` 套 `get_with_fallback` 缓存层（对齐 dragon_tiger）+ 0.0→missing + logger
- [x] R4 `sector_divergence.calculate_sector_divergence` []→data_status=missing + logger（:172/:227/:313 三处）；last_updated 源断不戳 now
- [x] R5 `extreme_market_detector` 空池（源断）→data_status=missing/degraded 不判"正常"，与"真平静"区分（ExtremeMarketSignal 已有 data_status 字段 S111 R5）
- [x] R6 `first_board_filter.score_dim4_chip` 50.0→-1 对齐 `score_dim_turnover:1274` sibling（缺失不参与加权）
- [x] R7 `gstock._push2_stock_get` 保留 latch 但加 is_delayed 标记透传 _quote_from/global_indices（对齐 market._emotion data_source；§10 Q4 选此非 per-call 重试，保 fast-fail）
- [x] R8 `newsradar.load_cache` 加 TTL 比较 + 过期返 skeleton（诚实空，对齐 fallback.py TTL 范式）
- [x] R9 `test_data_honesty.py` 扩 8 条 Tier-2 断言（每裂缝一条：源断→missing/degraded/is_delayed）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/risk_models.py` | R1/R2/R3 risk-trio |
| `backend/sector_divergence.py` | R4 |
| `backend/extreme_market_detector.py` | R5 |
| `backend/strategies/first_board_filter.py` | R6 |
| `backend/gstock.py` | R7 |
| `backend/newsradar.py` | R8 |
| `backend/tests/test_data_honesty.py` | R9 扩 |
| `specs/S112-Tier2撒谎诚实化/spec.md` | 本 spec |

## 5. 设计方案

同 S111 三层（registry 已建活文档 + `test_data_honesty` 可执行诚实门 + health 可选后续）。诚实化范式复用 S111 已建。risk-trio 级联自 fallback 根，优先消费 `get_with_fallback_meta`（如 capital_flow R4 范式）+ data_status；concentration 未走缓存层先套。gstock 选 is_delayed 标记（保 fast-fail，对齐 market._emotion）。

**YAGNI 边界**：chip-cyq 自建走 em_get（非平凡）+ chip-breaker 自愈 + premarket 裸读守卫 = availability/防封切片 **S113** 后续，不在本 spec（这些是诚实但健壮性缺陷，非性质撒谎）。

## 6. 验收标准

- [x] A1 8 条撒谎全修，`registry.md` 状态→已修
- [x] A2 risk-trio 源断→data_status=missing + logger（非 silent 0.0/空 dict）
- [x] A3 extreme 空池→missing/degraded 不判"正常"；sector 源断→missing + 不戳 now
- [x] A4 score-dim4-chip 缺数据→-1 不加权（非 50）
- [x] A5 gstock push2delay latch 时返 is_delayed 标记
- [x] A6 newsradar 缓存过期→skeleton（非旧缓存当新）
- [x] A7 `test_data_honesty` 扩 8 断言全绿；全量 pytest 不回归（对齐 S111 后 2416 passed 基线）
- [x] A8 §44 胜率路径不受影响

## 7. 合规与工程底线自查

- [x] 不臆造（断源标 missing/degraded 不编值）
- [x] 私有数据隔离（无新增落盘）
- [x] em_get 防封（gstock 非 em_get；本 spec 不动 cyq，cyq 走 em_get 留 S113）
- [x] §44 口径（不出 winrate/r/verdict，仅诚实化通道）

## 8. 测试计划

`pytest test_data_honesty.py`（扩 8）+ 全量 `pytest -m "not live" --deselect test_s032_refresh_loop --deselect test_fetch_global_intel_wm_import_fails`。

## 9. 风险与回滚

data_status 加性兼容；risk-trio 改动若致 risk_level 变化，回滚返 silent 0.0（但那是 bug）；gstock is_delayed 加性；newsradar TTL 改动若致返 skeleton 频繁，调 TTL 即恢复。影响面=打板 risk/情绪/资讯，回滚恢复撒谎行为不致崩。

**实现后 review 补修 3 项（2026-08-30，详见 registry.md「S112 实现后状态」）**：
- extreme detector 漏补"不缓存 missing"守卫（MEDIUM）→ 加 `if data_status!='missing': _set_cached` 对齐 sector
- SOX dict 缺 is_delayed 字段（LOW）→ 加 is_delayed=False
- newsradar skeleton 裸读 + load_cache except 窄（LOW）→ skeleton 包 try/except + except 扩

**⚠ 已知限制（未修，待后续切片决策）**：
- **risk-trio over-report 'missing'**（头部）：get_with_fallback_meta 的 _is_empty 分不开"源断返空"vs"未上榜返空"→ 99% 非上榜股永久 missing，原 crack 不可区分诉求未真解决。修需 fetch_ok 标志或 risk-trio 重构。
- **gstock is_delayed 无消费者**：backend 真标但全仓零 reader，前端未消费→前端任务。
- **DRY _resolve_*_provenance**：两 helper 重复→抽共享（纯质量）。
