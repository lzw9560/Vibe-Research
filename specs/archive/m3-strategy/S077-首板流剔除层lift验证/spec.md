# Spec: S077 — 首板流剔除层 §44 lift 验证（B1）

> 状态：草案（纯逻辑+离线单测+live main 接线完成 2026-08-18；30天 smoke 验管线通，初步剔除层 lift 1.01-1.06 全未validated，待 120 天全量复验）
> 作者：lzw9560  日期：2026-08-18
> 关联：S075-首板流/grill-decisions.md（硬剔除底线，待验证）/ S076（多源实测，正交）/ §44 复验窗口 / `tools/first_board_premium_baseline.py`（Phase 0 基线，复用数据路径）
> 级别：medium（独立研究脚本，零生产改动；day-cluster lift 若不复用现有需自实现）

## 1. 问题 / 目标

`grill-decisions.md` 锁定的**硬剔除底线**（层1 炸板≥2/封单<0.1%；层2 换手>30%；层3 孤板剔除/创业板不剔除）全是"待回测校准"占位阈值。用户 criterion："池大没问题，只要筛选合理"——但当前剔除**没一个阈值 validated**。本 spec **逐层算 §44 day-cluster lift**，判哪些剔除层真有 edge（留+校准）、哪些无 edge（砍/降展示）。**零风险研究脚本，不改生产，在实现新剔除阈值之前先验证。**

## 2. 背景

### 2.1 口径对齐（KEY 设计点，避免 apples-to-oranges）

| 口径 | 公式 | 来源 | B1 用？ |
|---|---|---|---|
| 隔夜溢价（Phase 0） | (D+1 open - D close)/D close | `first_board_premium_baseline.py` | ❌ 不直接比 |
| **策略标的收益** | (D+2 close - D+1 open)/D+1 open | `first_board_settlement.calc_target_return` | ✅ **B1 用此** |

D = 首板日（spec T-1）；D+1 = 建仓日（spec T，开盘买）；D+2 = 卖出日（spec T+1，收盘卖）。

Phase 0 的 +1.29%/50.4% 是**隔夜口径**（涨停价→次日开盘跳空），不是策略实际收益。**B1 用策略口径重算 raw 基线**，与剔除存活池同口径对比。

### 2.2 已核实事实

| 事实 | 来源 |
|---|---|
| em_zt_topic_pool 支持历史日期取涨停池 | Phase 0 `main()` 用 t_compact 取历史池 |
| baostock 日K缓存 `baostock_kline_cache.json` + 实时补 | Phase 0 `_load_kline_cache`/`_fetch_baostock_bars` |
| 交易日列表从 gene_scores.db eastmoney_live | Phase 0 `_trading_dates_from_db` |
| 策略标的收益口径 | `first_board_settlement.calc_target_return(t_open, t1_close)` |
| §44 lift 四态 | `first_board_settlement.judge_lift_four_states`（validated≥2x+n≥30 / 未validated 1≤lift<2x / 探索性 n<30 / 劣于随机<1） |
| 硬剔除底线（待验证） | `S075/grill-decisions.md` |
| 6位代码→baostock sh./sz. 前缀 | Phase 0 `_bs_code` |

### 2.3 §44 day-cluster lift 口径

池化 lift（全样本 strategy winrate / random winrate）会被 day-cluster 假象放大（存活股若簇聚在涨日，lift 虚高）。**B1 用 day-paired lift**：逐日算 (当日存活池 winrate/mean) vs (当日 raw 首板 winrate/mean)，再聚合（非池化）。复用 §44 现有 day-cluster lift 口径（S066/grill-reframe 用过，实现时定位）；若无可复用则按 day-paired 实现。

## 3. 需求清单

- [ ] R1 用**策略口径** (D+2 close - D+1 open)/D+1 open 算 **raw 首板基线**（全首板，不剔）的 N/mean/median/pos_ratio/成本后/t/p（复用 Phase 0 baostock 路径，扩展取 D+2 close）
- [ ] R2 从历史涨停池 + grill-decisions.md 硬剔除逻辑（standalone，镜像设计）算**逐层存活**：layer0=全首板 / layer1 存活 / layer2 存活 / layer3 存活
- [ ] R3 每层存活池算策略口径标的收益 + **day-cluster lift** vs raw 基线（day-paired）
- [ ] R4 每层判 §44 四态（≥2x+n≥30 validated / 1≤lift<2x 未validated / n<30 探索性 / <1 劣于随机）
- [ ] R5 输出矩阵 JSON：`{layer: {N, mean, median, pos_ratio, lift, validation_status, by_zt_count_4档}}`
- [ ] R6 不改生产代码（纯 `tools/` 脚本，只读 em_zt_topic_pool + baostock）
- [ ] R7 em_zt_topic_pool 走 `em_get` 限流（不裸调，复用现有 `astock.em_zt_topic_pool` 已包 em_get）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/first_board_layer_lift.py`（新建，与 Phase 0 baseline 同目录） | 逐层 lift 验证脚本 |
| `.scratch/s077-layer-lift/matrix.json`（新建） | 输出矩阵 + per-layer 四态 |
| `.scratch/s077-layer-lift/conclusion.md`（新建） | 人话结论：哪层留/砍/校准 |
| （无生产代码改动） | — |

## 5. 设计方案

### 5.1 流程（复用 Phase 0 数据路径）

1. 交易日列表（gene_scores.db eastmoney_live，默认 120 天）。
2. 每个 D：`em_zt_topic_pool(getTopicZTPool, D)` → 首板池（lbc=1）。
3. 逐层剔除（standalone 镜像 grill-decisions.md 硬剔除）：
   - layer1 封板质量：炸板≥2 / 封单/流通市值<0.1% 剔除
   - layer2 筹码结构：换手>30% 剔除（baostock turn）
   - layer3 市场环境：同板块涨停<2且无题材（孤板）剔除；创业板**不剔除**（grill-decisions.md 改分组展示，B1 标注创业板子群但不剔）
4. 每层存活 + raw 全首板：baostock 取 D+1 open + D+2 close，算策略标的收益。
5. day-paired lift：逐日 (存活 winrate/mean) vs (raw winrate/mean)，聚合。
6. 四态判定 + by zt_count 4档（冰点/普通/活跃/亢奋）分层。

### 5.2 取舍

- **standalone 镜像新剔除，不跑现有 filter**：现有 filter 用旧阈值（首封≥14:00/封单<0.5%/换手>25%/成交额>15亿/量比≥2.0/创业板剔除），不是 grill-decisions.md 新硬剔除。B1 验证**新设计**，故 standalone 镜像新逻辑，不依赖先改 filter。§44-honest：先验后实现。
- **不用隔夜口径**：Phase 0 隔夜 ≠ 策略实际收益，B1 用策略口径重算 raw 基线（R1）。
- **不复用现有 first_board_scores 快照**：那些是旧剔除产物，反映旧设计；B1 从 raw 涨停池 standalone 算新剔除逐层存活。

### 5.3 备选不选

- 验证旧剔除（现有快照）：旧剔除将被替换，验它无用。
- 池化 lift（非 day-paired）：§44 已证池化 lift 是假象（grill-reframe 4.686x→day-cluster 1.723x），不用。

## 6. 验收标准

- [ ] A1 策略口径 raw 首板基线算出（N/mean/median/pos_ratio/成本后/t/p），与 Phase 0 隔夜口径并列展示（不混用）
- [ ] A2 逐层存活重建（layer0/1/2/3 各 N 递减，符合剔除逻辑）
- [ ] A3 每层 day-cluster lift + §44 四态
- [ ] A4 n<30 标"探索性"（不分档下结论）；by zt_count 分层 n<30 同样标
- [ ] A5 不改生产代码（git diff 无生产文件）
- [ ] A6 结论明确：哪层 lift≥2x（留+校准阈值）/ 1≤lift<2x（降展示）/ <1（砍）；阈值往哪校准的方向性建议
- [ ] A7 矩阵 JSON 可复现（同 baostock 缓存 + 同交易日列表 → 同数字）

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机：研究脚本，无用户可见研判/推荐/买卖输出 → 合规无涉
- [x] 判断可复现：baostock 缓存 + 交易日列表可复算；涉及 lift 数字属统计口径，非市值/估值，`financial_rigor.py` 不适用
- [x] 涨停四池/个股：B1 不呈现个股 code/name 给用户（只统计聚合）→ 无涉
- [x] 用户私有数据：用公开行情源 + gene_scores.db（交易日列表，非私有持仓）；输出 `.scratch/`（不入 git）
- [x] 东财端点走 em_get 限流：R7，复用 `astock.em_zt_topic_pool`（已包 em_get 熔断+代理）

## 8. 测试计划

- **离线单测**（`pytest -m "not live"`）：合成涨停池 + 合成 baostock bars，验逐层剔除逻辑 + 策略口径标的收益计算 + day-paired lift 计算 + 四态判定。
- **live 跑**（主验收）：`python tools/first_board_layer_lift.py --days 120`，产出矩阵；sample 3 笔手工复核（baostock bars 对得上）。
- 不进默认 `pytest -m "not live"`（live 研究，按 newsradar 教训 deselect 或标 live）。

## 9. 风险与回滚

| 风险 | 处置 |
|---|---|
| 口径错（隔夜 vs 策略混用） | §2.1 钉死策略口径；A1 并列展示两口口径防混 |
| 样本不足（13 天/848 → 分层 n<30） | A4 标探索性不下结论；扩 days_back=120 取更多 |
| day-cluster lift 实现口径与 §44 现有不一致 | R3/§2.3 优先复用 S066/grill-reframe 现有 lift；自实现则 day-paired，文档标注口径 |
| baostock 缓存无 D+2 close | 复用 Phase 0 baostock 实时补路径（ wider window 取 D..D+5） |
| 创业板"不剔除改分组"口径 | R2/§5.1 layer3 标注创业板子群但不剔，单独算子群 lift |
| 回滚 | 纯研究脚本，删脚本 + `.scratch/s077/` 即可，零生产影响 |

## 10. 初步结果（30 天 smoke，2026-08-18）

`python tools/first_board_layer_lift.py --days 30`（19 交易日 2026-07-20~08-09，cache max=08-17，max_d 留 7 天 robust margin 防 D+2 越界）：

| 层 | n | winrate_lift | §44 四态 |
|---|---|---|---|
| layer0（raw 首板基线，策略口径）| 563 | —（基线）| — |
| layer1（封板质量：炸板≥2/封单<0.1%）| 434 | 1.0099 | 未validated |
| layer2（筹码：换手>30%）| 433 | 1.0125 | 未validated |
| layer3（全剔除含孤板）| 318 | 1.0596 | 未validated |

## 11. 全量复验（--days 120，2026-08-18）

`--days 120` 跑完（exit 0）但**数据受限**：gene_scores.db eastmoney_live 仅 26 交易日（07-09~08-09），其中 7 个最早日（70 首板）D+1/D+2 缺（kline cache/baostock 覆盖缺口，待查），**有效仅 19 日 / 563 首板**——与 30 天 smoke 同。

**§44 verdict（19 日 / 563 首板，非 120 日——数据受限，非定论）**：
- 三层剔除 lift 1.01-1.06，**全未validated**（1≤lift<2：无 ≥2x edge，但 ≥1 未劣于随机）。
- layer3（全剔除）最高 1.06x，仍远未过 2x 门。
- 配合 Phase 0（raw 首板隔夜 ≈1x），**首板流选股链 §44 端到端暂无 validated edge**——印证 grill D7d 影子先行（不真金白银建仓，先影子）。
- n≥30 过"探索性"门槛但 lift<2x=未validated，不下"有 edge"结论。

**ROOT CAUSE（2026-08-18 debug 查清）**：`astock.em_zt_topic_pool("getTopicZTPool", D)` 对老日期返**空池**（07-09/06-15/03-16 debug 全 0 首板）——东财 push2ex 涨停池端点**历史回看仅 ~1 个月**。非 B1 bug、非 cache（cache 实有 8 月 bars / 1121 codes / 全字段）、非 baostock 补——是端点限制。`--days 240 --no-fetch` 跑 152 交易日仅近 ~10-12 日有非空池 → n 仍 563。

**数据局限（要长窗 verdict 须换源）**：
- em_zt_topic_pool ~1 月回看 → B1 上限 ~1 月 / 563 首板。
- 备选涨停历史源（待探）：akshare 涨停接口 / `ths_limit_up_pool` 是否服务历史 / 自建涨停历史 DB（每日 snapshot 累积，须数月）。
- 题材简化（concept_tags=[]，孤板=sector<2）；接 ths_limit_up_pool 题材后 layer3 lift 可能略变。

**§44-honest 定位**：lift~1.0 robust（剔除 barely beat raw，达 ≥2x 极不可能）→ 1 月 verdict 已足够定性"剔除层无 §44 validated edge"。长窗数据即使补到，flip 到 ≥2x 概率极低。→ 首板流剔除（grill-decisions.md 设计）在可用数据上**无 §44 validated edge**，印证 D7d 影子先行；硬剔除是否进生产 filter 须重新审视（无 validated edge 不该上）。

## 12. 8 月 baostock verdict（决定性，2026-08-18）

`python tools/first_board_layer_lift.py --baostock-history`——baostock kline cache 8 月 / 1121 codes，`pctChg>=9.9` 算涨停历史（**绕开 em ~3 周限制**），秒级，无须等 S078 累积：

| 项 | 值 | §44 |
|---|---|---|
| raw 首板（8 月基线）| n=5632 / 153 日 / winrate 50.66% / mean +0.74% | 薄 edge ≈1x，未 validated 非劣于随机 |
| 层2 换手>30% 剔除 | n=5494 / lift 0.9952 | **劣于随机**（<1.0；0.9952 borderline，honest=中性偏微害、无 edge）|
| 层1 炸板/封单 / 层3 孤板 | 未算 | baostock 无 zbc/fund/hybk |

**§44 定论（8 月 / 153 日 / 5632 首板，robust）**：
- raw 首板 edge 薄（winrate 50.66% 近掷硬币 + 0.74% mean），≈1x，无 validated edge——印证 Phase 0。
- 层2 换手剔除 lift 0.9952 <1.0 → 劣于随机（borderline 0.5% below；honest 读=中性偏微害、无 edge，§44-consistent 不进硬剔除/移除）。
- 首板流剔除（至少换手层）8 月无 validated edge → **不该进生产 filter**；raw 首板 edge 薄 → raw-shadow + D7d 影子先行站住。
- **绕开 S078 累积**：baostock `pctChg>=9.9` 算涨停历史是 em ~3 周限制的 bypass，8 月秒级——S078 zt_history DB 降为交叉验证（非 block，仍累积作 em 口径对照）。

**caveat（§44-honest）**：涨停代理 `pctChg>=9.9` 有近涨停非涨停噪声（lift 内抵消）；1121 cache codes 选择偏（涨停-prone 股，lift 比值内抵消）；层1/3 未算（补需 zbc/fund/hybk 源）；0.9952 borderline（n=5494 下 0.5% deviation 可能显著亦可能噪声，不强判"强反作用"，判"无 edge + 中性偏微害"）。
