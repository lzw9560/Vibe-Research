# Spec: S159 — §44 应用规约 v2（保留方法论，改应用方式）

> 状态：草案（方向已接受 2026-09-06，evidence 待 6 专家+8 域 workflow 回来补充）
> 作者：Claude  日期：2026-09-06
> 关联：[s44-quant-validation-loop memory]、[methodology-window-before-no-edge-conclusion memory]、S153/S155-S158（§44 v1 各 harness，结论窗口偏差待修）

## 0. 问题（窗口偏差 + 斤斤计较失真 + 每阶段激进）

§44 v1 在 D+1-开盘→D+4 path 窗口测了 ~20 因子跨数据源全 net lift<1"劣于随机"。用户质疑"跟设计思路出入太大"——独立验证三窗口**证实是窗口偏差假象，非真无 edge**：

| 窗口 | 平均 | 中位数 | 胜率 |
|---|---|---|---|
| 隔夜 gap（D 收盘→D+1 开盘） | +1.30% | +0.28% | 54.3% ← 真 edge（合 Chen2017） |
| D+1 日内（开→收，H2 o2c） | +0.03% | 0.00% | 46.2% |
| path（D+1 开→exit，§44 v1 框架） | +0.67% | -3.00% | 36.3% ← 反转负段 |

**根因**：§44 v1 `simulate_holding(signal_date=D)` 入场 D+1 开盘 = 隔夜 gap **之后**，测的是隔夜正之后的反转负段。**系统性 miss 了隔夜正 edge**。"全因子劣于随机" = "D+1-open 窗口无 edge"，≠"无 edge"。

用户判断（统计上成立）：
1. **斤斤计较失真**：Bonferroni K=6-8 假设大 n；在 13-42 天 modest n 上 over-conservative → false negative 爆炸 → 真优势被误否 → 失真。
2. **每阶段激进**：§44 散在 5 层（spec 自查+evaluation 降权+回溯+6-lens grill+每 harness），每 spec 上 grill+full 重方法论，背离 §1.2"降级非阻塞"本意。
3. **该拉长时间维度**：短窗噪声大+regime 依赖（秒板 13 天 1.31x→31 天 0.22x 翻转）；复杂因子需更长样本。

## 1. 目标

§44 v2 应用规约——**保留方法论（day_paired+零分布+Bonferroni+walk-forward sound 别废弃），改应用方式**：窗口优先 + n 门槛 + 回溯主场 + 小 n 不抬杠 + 数据积累并行。让 §44 从"每阶段激进 gate"变"回溯期合理验证 + 前置轻 sanity 定位"。

## 2. 背景

- 方法论 sound：§44 真防了假阳性（vol_surge 池化预知偏差、late_lock 5min 假象是它促使 grill 戳破的）。别废弃方法论。
- 问题在应用：错窗口 + 短数据 + 每阶段 + 小 n 过度矫正。
- 隔夜 gap 不可直接交易捕获（涨停股 D 收盘 sealed 买不到），须盘中打板 intraday entry（live-only，需采集积累）。
- §44 v1 各 harness（platform_breakout/first_plate_h2/low_absorption/lianban/zt_pool_seal_time/valuation_pe/miaoban_superset）结论"D+1-open 窗口无 edge"窗口偏差待修。

## 3. 需求清单（R1-R5，5 件改）

- [ ] R1 前置窗口 sanity（最重要）：任何 §44 验证前先多窗口对比（隔夜/D+1 日内/path，算 mean+胜率+base rate）定位优势在哪窗口。无窗口优势不上重方法论（不抬杠）。防南辕北辙。
- [ ] R2 重方法论只在"对窗口+n 够"上：day_paired+零分布+Bonferroni+walk-forward 只在 (a) 窗口已定位有优势 (b) n≥阈值（≥200 picks 或 ≥60 天）才上。小 n 短窗标"探索性/underpowered"不判"劣于随机"。
- [ ] R3 §44 不每阶段参与：spec 自查降为设计期轻 sanity（1 段确认窗口+口径），不每 spec 上 6-lens grill+full 重方法论；6-lens grill 只留给重大方法论/验证范式变更；evaluation 层降权基于长期 lift（≥60 天）非短窗，短窗标"待验"不降权。
- [ ] R4 回溯模块是 §44 主场：重方法论集中 scheduled_tasks R3（30/60 天复验节奏），spec/实现阶段不重度用。
- [ ] R5 激进度调低：Bonferroni 按 n 调（小 n 轻矫正/underpowered，大 n 才 K=6-8）；"劣于随机"只在 n 大+对窗口下；不在负 base 窗口测（先定位窗口）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `CLAUDE.md` §1.2 | §44 从"参考性建议"强化为"前置窗口 sanity + 回溯主场 + 不每阶段"；加"小 n 短窗标 underpowered 不判劣于随机" |
| `backend/candidate_funnel/evaluation.py` | R3：降权基于长期 lift（≥60 天）非短窗；短窗结果标"待验"不降权；registry 加窗口偏差告警（已加 2026-09-06） |
| `specs/_template.md` | R1：spec 模板加"前置窗口 sanity"步骤（多窗口对比定位优势在哪，无则不上重方法论） |
| `backend/scheduled_tasks.py` R3 | R4：保持 30/60 天复验节奏（§44 主场），文档强调"重方法论在此跑非每阶段" |
| `backend/tools/` 各 harness | R2：加 n 门槛（小 n 标 underpowered 不判劣于随机）；Bonferroni 按 n 调 |

## 5. 设计方案

**A. 前置窗口 sanity（R1）**：新 harness 第一步不算 lift，先算目标多窗口（隔夜/D+1 日内/path/其他）的 mean+median+胜率+base rate。无窗口显优势（如全 base 负且无窗口正）→ 标"无窗口优势，不上重方法论"，不跑 day_paired+null+Bonferroni（防抬杠）。

**B. n 门槛 + Bonferroni 按 n 调（R2/R5）**：n<阈值（如 200 picks 或 60 天）→ 标"探索性/underpowered"，不判"劣于随机"。Bonferroni：n 大用 K=6-8，n 小用更轻矫正（如 FDR Benjamini-Hochberg）或只标 underpowered。

**C. 不每阶段参与（R3）**：spec 模板的"§44 合规自查"栏从"必过 grill+full §44"改"设计期轻 sanity（确认窗口+口径+n 够否）"。6-lens grill 只在 spec 涉重大方法论/验证范式时跑。

**D. 回溯主场（R4）**：scheduled_tasks R3（30/60 天复验）是 §44 重方法论的唯一重度使用点。spec/实现阶段用轻 sanity。

**E. 数据积累并行**：封单轨迹/竞价量比/秒级 timing 是 live-only，设每日 cached 采集 pipeline，积累 ≥60-90 天再上 §44 重方法论回溯。

## 6. 验收标准

- [ ] A1 spec 模板含"前置窗口 sanity"步骤
- [ ] A2 evaluation.py 降权基于长期 lift（≥60 天），短窗标"待验"
- [ ] A3 各 harness n<阈值标"underpowered"不判"劣于随机"
- [ ] A4 CLAUDE.md §1.2 更新（§44 v2 应用规约）
- [ ] A5 scheduled_tasks R3 文档强调"§44 重方法论主场"
- [ ] A6 pytest -m "not live" --deselect (newsradar+s032+s040) 全绿（降权逻辑改不破现有测试）

## 7. 合规与工程底线自查

- [x] 不臆造：窗口 sanity 实算多窗口 mean/胜率，禁心算
- [x] 私有数据隔离：采集 cache 写 .vibe-research 不进 git
- [x] em_get 防封：live 采集走 em_get/breaker（zt_pool push2ex / ths_limit_up_pool _ths_get）
- [x] §44 降级参考性建议：v2 强化"前置 sanity+回溯主场"，不强制不阻塞
- [x] verdict 外推禁令：§44 v1 各 harness 结论标"窗口偏差待修"，不外推"绝对无 edge"

## 8. evidence（6 专家审计 + decisive gap 测试已补，2026-09-06）

**6 专家对抗审计 verdict（置信度 0.9，code-verified）**：
- **(A) 所测窗口（D+1 开盘 post-gap 续涨选股）无 edge = 真非 bug**——D+1 开盘入场对"次日买续涨"是正确可实现口径（涨停 D 收盘封死买不到，gene_scores 信号 D 收盘后才就绪）；path_lift=0.978 五参 0.87-0.97 robust，所有选股维度≤1.363，base WR 24-35% 结构性负。
- **(B) 但"打板无 edge" blanket verdict = artifact（外推禁令违反）**——框架系统性 miss 了项目自己已验证的隔夜 gap（`first_board_premium_baseline.py`: N=899, mean +1.33%, t=10.65, p≈0, 56.8% 正, net +0.93%）。所有 verdict 口径（o2c/path/layer_lift）从 D+1 开盘起算=gap 之后。代码自己写 `first_board_layer_lift.py:13 "≠ Phase 0 隔夜口径"` 但从未把 gap 折进 lift；gap-inclusive c2c 躺 DB 里从没进 winrate/lift。
- **根因**：① 窗口错位（code-verified 最强）② verdict 外推越界（c2c 在 DB 未 aggregate）③ gap edge 真实但薄+部分不可捕获（14 天/66% 活跃 regime/未排除一字板/net_pos 50.6%）④ unbuyable 过滤器相关选择偏倚（高因子股更易 D+1 一字板被滤→lift 压低，次级）⑤ 成本口径不一致（0.4 vs 0.7，但反向切不支 bug 论）⑥ survivorship（LOW，方向有利 edge）。

**decisive gap-window lift 测试**（`backend/tools/gap_window_lift.py`，6 专家 recommended_next_test，数据已在 DB 秒级）：
- gap（D 收→D+1 开）all: mean +1.15%, net +0.45%（扣 0.70% cost）, net_WR 46.5%（薄，<50%）。
- top-quintile（高 gene_score）vs all: **lift 0.942x 劣于随机**；pearson(score, gap)=-0.075 弱负。
- **gene_score 无 gap 选股力**（不预测哪个涨停股 gap 大）→ §44"无 selection edge"在**对窗口（gap）也成立**，真非 bug。
- gap 本身是真**事件 edge**（薄+不可选+部分不可交易，sealed D 收买不到，需盘中打板 intraday）。

**refined 结论**（替代前"窗口偏差"粗框）：
- §44"无 selection edge"**是真的 + robust**（post-gap continuation + gap 两窗口均验证 gene_score 无选股力）——不是窗口偏差（对 selection 而言）。
- §44 overreach = 把"无 selection edge"外推成"无 edge"——但**事件 edge（涨停→隔夜 gap +1.15%）真实**，只是薄+不可选+部分不可交易+需 intraday 捕获。
- **答用户"全因子劣于随机"**：无因子有**选股力**（预测哪个涨停股 gap 大/续涨好）——对窗口也验证，真；gap 是**薄事件 edge** 非选股 edge，需盘中打板 intraday 入场（live-only）。

**待 8 域因子 discovery workflow（w0gt0y1xt）补**：其他因子（vol_surge/volatility/连板/封单/竞价量比/筹码分布等）是否预测 gap——本 decisive 只测了 gene_score。workflow 回来后补"对窗口+有优势因子"清单，指导 §44 v2 在 gap 窗口验哪些因子。

## 9. 分级

**medium**（应用规约调整 + CLAUDE.md/evaluation/spec 模板改 + 不破现有测试）。免 feature 分支，issue 层单轮 review。grill 留给"§44 v2 重方法论变更"（本 spec 是应用规约非方法论本身，可免重 grill，但实现后跑 sanity 验）。
