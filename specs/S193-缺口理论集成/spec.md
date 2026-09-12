# Spec: S193 — 缺口理论集成（regime 判断信号 + chat.TOOLS 注入）

> 状态：草案（grill-me 2026-09-12 走完 Q1-Q17 定向）
> 作者：Claude  日期：2026-09-12
> 分级：medium（纯函数 + chat.TOOLS，可独立验分类准确率，融合消融在 S194）
> 关联：[[../S194-信号融合基线/spec.md]]（融合层，F1 消融验缺口增量）、[[../S189-做T框架/spec.md]]（T+0 OFI 证否，缺口是不同信号源）、`edge-in-intraday-not-selection`、`methodology-window-before-no-edge-conclusion`

## 1. 问题 / 目标

用户贴缺口理论（四类：普通/突破/持续/衰竭），要集成进项目。经 grill-me 17 轮定向：
- **定位**：缺口作 **regime/变盘判断信号**（多空动能转换），**不直接触发买卖**（Q10-Q11）
- **形态**：日级 K 线缺口（不是盘中 T+0，Q6）+ 纯函数 `classify_gap(code, date) → {type, regime, confidence}`
- **用法**：问时注入 AI 研判 + 关注标的推送 + 候选池注入（Q12），不自动切 arm（Q11）
- **验证**：不验单信号 §44（Q13 反思——单信号独立验可能无价值，融合才是），验 S194 融合消融 F1（加缺口 vs 不加的 lift 增量）
- **方向**：上下都做（向上=多头、向下=空头），但 A 股做空受限 → 向下缺口仅作 regime 判断 + 减仓预警，不裸做空（Q3 + §1.1 弱合规）

**目标**：缺口理论作认知 + 纯函数信号 + chat.TOOLS 注入 AI 研判，**不直接进买卖执行层**。

## 2. 四类缺口量化定义（Q2 grill 定）

理论定性描述 → 可重算量化（§44v2 可复现要求）：

| 类型 | 出现位置 | 量化判定 | 实战意义 |
|---|---|---|---|
| 普通缺口 | 盘整/无趋势 | 缺口小 + 量比<2.0 + 3 日内回补 | 噪音忽略 |
| **突破缺口** | 关键压力/支撑 | **量比≥2.0 + 3 日不回补 + 在 20 日前高/前低压力位** | 趋势启动 regime |
| 持续缺口 | 趋势中途 | 突破缺口后 + 量比≥1.5 + 不回补 | 趋势中继 regime |
| 衰竭缺口 | 趋势末端 | 第三个缺口+异常放量(量比≥3)或缩量(量比<1) | 反转 regime |

**参数（§44 sweep 空间，先拍起点）**：
- 量比 = 当日成交量 / 5 日均量；放量阈值 2.0（突破）/ 1.5（持续）/ 3.0 或 <1（衰竭）
- 不回补窗口 = 3 日（A 股 T+1，3 日不回补=有效；回补=失效）
- 压力位 = 20 日前高（向上突破）/ 前低（向下突破）——最简量化定义，避免密集成交区聚类复杂度

**缺口方向**：
- 向上缺口（D 低 > D-1 高）→ 多头 regime
- 向下缺口（D 高 < D-1 低）→ 空头 regime（A 股做空受限，仅 regime 判断 + 减仓预警，不裸做空）

## 3. 需求清单

- [ ] R1：`classify_gap(code, date) → dict` 纯函数
  - 输入：股票代码 + 日期
  - 输出：`{type: 普通/突破/持续/衰竭, direction: 向上/向下, regime: 趋势启动/中继/反转/噪声, confidence: 0-1, params: {量比, 回补状态, 压力位}}`
  - 数据源：baostock 日 K（date/open/high/low/close/volume/amount）+ 5 日均量 + 20 日前高/前低
  - 复用：`bars_provider`（baostock fallback）+ 不走 em_get（无防封顾虑，日 K 非东财端点）
- [ ] R2：加入 `chat.TOOLS`（§3 约定，自动同步 MCP）
  - 新工具 `query_gap_regime(code)` → 调 classify_gap → 返 regime 给 AI
  - AI 用户问"X 股怎么看"时，system prompt 注入该股缺口 regime（问时注入，Q12 场景 1）
- [ ] R3：候选池注入（Q12 场景 3）
  - breakout 候选池标的 → 缺口 regime 注入候选池 context（AI 研判候选时带 regime）
  - 复用 `candidate_funnel` / `briefing` 上下文构造
- [ ] R4：关注标的推送（Q12 场景 2）
  - watchlist/持仓标的 出现缺口 regime 变盘（突破/衰竭）→ 飞书推送提醒
  - 推送阈值：只推突破+衰竭（普通/持续不推，避免噪声）
  - 复用 `notification_service` + 飞书 App Bot
- [ ] R5：分类准确率验（Q13-B，不是 §44 买卖 lift）
  - 验"分类准不准"：突破缺口后 N 日（3/5/10 多窗口）是否真趋势启动（收益 > 阈值）
  - 混淆矩阵：判突破实际是持续的 % + 衰竭实际是普通噪声的 %
  - 准确率 < 50% → 标"分类不可信"降级，但**不阻止集成**（Q13 反思：单信号无 edge ≠ 融合无价值）
  - 工具：复用 §44v2 verifier 的 event edge_type（缺口事件作 dates，后续收益作 returns）作 sanity，非 gate

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/engine/gap_classifier.py` | **新建**：classify_gap 纯函数（无 IO，可单测）+ 四类缺口量化逻辑 |
| `backend/chat.py` TOOLS | 加 `query_gap_regime` 工具项（§3 自动同步 MCP） |
| `backend/routers/candidates.py` | 候选池 context 注入缺口 regime（R3） |
| `backend/scheduler/executors/...` | watchlist 缺口变盘扫描 + 飞书推送（R4，新 executor 或加 daily_full_pull） |

## 5. 验收

- [ ] A1：classify_gap 纯函数 + 单测（四类缺口各一个 case + 边界）
- [ ] A2：query_gap_regime 进 chat.TOOLS，飞书 bot 问股时注入 regime
- [ ] A3：候选池 + watchlist 注入/推送通路通
- [ ] A4：分类准确率 sanity（多窗口 3/5/10 日）— 不作 gate，标"分类质量" metadata
- [ ] A5：pytest not live 全绿

## 6. 合规与工程底线自查

- [x] 缺口 regime 是研究性判断（可复现：baostock 日 K + 量化规则重算），禁臆造
- [x] 不直接触发买卖（regime 信号喂 AI + 用户决策，§1 弱合规半自动化助手）
- [x] 不做空（向下缺口仅 regime + 减仓预警，A 股做空受限 §1.1）
- [x] 私有数据未进 git（classify 用 baostock 公开日 K）
- [x] baostock 非 em_get，无防封顾虑

## 7. 关联

- [[S194-信号融合基线]]（F1 消融验缺口增量贡献）
- [[S189-做T框架]]（T+0 OFI 证否——缺口是不同信号源，日级非盘中，可能更强但未验）
- `methodology-window-before-no-edge-conclusion`（缺口后验多窗口 3/5/10 日）
- `edge-in-intraday-not-selection`（缺口 regime 是择时/状态，不是选股）
- 知识图谱：[[../_knowledge/gap-theory]]（S195 落图谱认知层）
