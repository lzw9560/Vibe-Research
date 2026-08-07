# Spec: S030 — 盘前简报多层化 + UX 收敛

> 状态：已废弃 2026-08-07（并入 `../S031-调度收口盘前多层按战法回测/spec.md` 重写实现；本 spec 留档作决策记录，未独立实现）
> 作者：Claude  日期：2026-08-06
> 关联：S028（limitup 文案/条件）、S029（GeneScreener 接通）、S023（漏斗可用性）、S024（拓扑展示）
> 级别：large（多文件 + UX 重设计 + 两套漏斗整合；不碰新外部源，但面大；feature 分支 + grill + playwright）

## 1. 问题 / 目标

盘前简报（`/workflow/pre-market`）的涨停基因因子被压成单层（`limitup_screener_factor.py:82` "单层包装"），用户**无法逐层验证策略**（打分→战法→仓位各留了什么、过滤了什么）。

同时页面逻辑"乱、跳"：
- 点候选整页跳 `/workflow/candidates/:code`，打断当前视图；
- 涨停基因选股散在三页：`/workflow/pre-market`（单层因子）、`/candidates`（R1/R2/R3 漏斗）、`/limitup/gene`（S029 配置表），切来切去；
- 页内布局（情绪/因子卡/条件 chips）排列不连贯；
- GeneScreener（S029）与盘前简报定位不清。

**目标**：盘前简报作为涨停基因选股的**统一多层视图**——同时展示因子三步漏斗（打分→战法→仓位）+ 候选池 R1/R2/R3 漏斗，每层可逐层验证（conditions/passed/filtered_out），点候选用侧边抽屉看诊断卡（不整页跳），布局重整，GeneScreener 厘清为"阈值配置 + 全市场得分表"伴随页。

## 2. 背景

- **涨停基因因子**：`backend/factors/limitup_screener_factor.py` 包装 `PreMarketWorkflow`，现输出单层 `FunnelLayer(layer_id="LS")`。S028 已补 `conditions` + 三态 `data_status`。
- **PreMarketReport 数据已足三层**（`pre_market_workflow.py:76-88`）：
  - `candidates`(qualified 打分≥阈值) + `strong_candidates`(high_gene) + `filtered_out`(未达标，含 code/name/reason) → **L1 打分层**
  - `strategy_matches`(每股战法 best_strategy/confidence/reasons) → **L2 战法层**
  - `position_suggestions`(每股仓位 suggested_pct/confidence) → **L3 仓位层**
- **候选池漏斗**：`backend/candidate_funnel/funnel.py` run_funnel → R1(宽源)→R2(收敛)→R3(定稿)+SELF，`FunnelLayer` 含 conditions/passed/filtered_out。前端 `/candidates` 页用 `FunnelLayers` 卡片组件 + `useFunnelLayers` hook（`frontend/src/lib/query/topology.ts:27`，S024 复用 `/api/workflow/funnel/layers`）。
- **候选详情**：`/workflow/candidates/:code`（`CandidateDetail.tsx`）调 `candidatesApi.diagnosis(code)` → DiagnosisCard（活跃度档位/命中规则/量价/情绪梯队/资金流/风险标注/缺失）。S028 已修 Lazy 路由 bug。
- **GeneScreener**（S029）：`/limitup/gene` 阈值配置 + 全市场得分表 + 可展开五维明细。
- **UI 基元**：无现成 Sheet/Drawer/Modal（`frontend/src/components/ui/` 只有 GlassCard/Button/TabBar 等），需新建轻量 Sheet。

## 3. 需求清单

- [ ] R1 涨停基因因子多层化（后端）：`limitup_screener_factor.fetch()` 输出 3 个 `FunnelLayer`——L1 打分(五维+阈值)、L2 战法匹配、L3 仓位建议——各层 conditions/passed/filtered_out/input/output 齐全；保留 S028 的 data_status/conditions。
- [ ] R2 盘前简报渲染因子多层（前端）：`FactorSection` 把 `factor.layers`（现 3 层）渲染成漏斗卡片（复用 `FunnelLayers` 卡片样式 / conditions+passed+filtered_out），逐层可验证。
- [ ] R3 盘前简报嵌入候选池 R1/R2/R3 漏斗：PreMarketBriefing 调 `useFunnelLayers`（既有）→ 渲染 `FunnelLayers` 组件，作为第二组漏斗。
- [ ] R4 候选点击改侧边抽屉（不整页跳）：新建 `Sheet` 组件；点任一层 passed 候选 → 抽屉内嵌 `CandidateDetail` 内容（诊断卡），保留 `/workflow/candidates/:code` 路由供直链。
- [ ] R5 页内布局重整：清晰纵向流——市场情绪 → 涨停基因漏斗(三步) → 候选池漏斗(R1-R3) → 候选详情(抽屉)；分区标题明确，减少视觉跳跃。
- [ ] R6 GeneScreener 定位厘清：盘前简报头部加"配置阈值/全市场得分表→"链接到 `/limitup/gene`；GeneScreener 页头部回链"← 回盘前简报"。两处分工写进导航/页头说明。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/factors/limitup_screener_factor.py` | R1 fetch() 拼 3 FunnelLayer（打分/战法/仓位），复用 report 既有字段 |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | R2/R3/R5：FactorSection 多层渲染 + 嵌入 FunnelLayers + 布局重整 + Sheet 触发 |
| `frontend/src/components/ui/Sheet.tsx`（新） | R4 轻量侧边抽屉（portal + 遮罩 + Esc 关） |
| `frontend/src/pages/workflow/CandidateDetail.tsx` | R4 抽出示内容为 `<CandidateDetailPanel code>` 供抽屉复用；路由页保留 |
| `frontend/src/pages/limitup/GeneScreener.tsx` | R6 页头回链盘前简报 + 定位说明 |
| `frontend/src/lib/query/topology.ts`（既有） | R3 复用 `useFunnelLayers`（无需改） |

## 5. 设计方案

### R1 因子三层（后端，数据全在 report）
```
L1 打分:  input = len(filtered_out)+candidates+strong  (全涨停)
          output = candidates+strong (qualified)
          filtered_out = report.filtered_out
          conditions = [五维+权重, 合格阈值, 高基因阈值]
L2 战法:  input = len(L1.output)
          output = [c for c in candidates if c.code in strategy_matches]   # 放宽到全部（去 [:20] 上限）
          filtered_out = [未匹配的]
          conditions = ["8大战法自动匹配", "取置信度最高"]
          passed 每项 detail 携 best_strategy/confidence（供视觉筛查，后续 S031 做交互式战法缩范围）
L3 仓位:  input = len(L2.output)
          output = [c for c in matched if c.code in position_suggestions]
          filtered_out = [未给仓位的]
          conditions = ["仓位建议（PositionAdvisor）"]
```
**改 PreMarketWorkflow**：`pre_market_workflow.py:130` `pool.candidates[:20]` 去掉 `[:20]` 上限 → match 全部 qualified（典型日 5-20 只，无性能问题；今天 0 qualified 无影响）。其余 PreMarketWorkflow 逻辑不动。

### R2/R3 前端两套漏斗
- 因子三步：`factor.layers`（L1/L2/L3）渲染——抽 `FunnelLayerCard` 公共组件（从 `FunnelLayers.tsx` 提取，候选池与因子共用）。
- 候选池 R1/R2/R3：`useFunnelLayers` hook 取数 → 复用 `FunnelLayers` 组件。
- 两组漏斗分区呈现，标题区分"涨停基因因子漏斗（打分→战法→仓位）" vs "候选池漏斗（宽源→收敛→定稿）"。

### R4 候选抽屉
- 新建 `Sheet`（右侧滑入，portal 到 body，遮罩 + Esc + 点遮罩关）。
- `CandidateDetail.tsx` 重构：把诊断卡渲染抽成 `CandidateDetailPanel({code})`（纯展示，不依赖路由 params），路由页 thin 包装调 Panel，抽屉也调 Panel。
- 点候选：`setDrawerCode(code)` → `<Sheet open><CandidateDetailPanel code/></Sheet>`，不 navigate。

### R5 布局
- 纵向分区：①市场情绪卡（既有）②涨停基因因子漏斗（三步）③候选池漏斗（R1-R3）④（抽屉层）。每区 `SectionHeader` 标题 + 一句说明。
- 因子卡的 S028 conditions chips 保留，移入对应层卡。

### R6 GeneScreener 定位
- 盘前简报头部："阈值配置 / 全市场得分表 →" 链 `/limitup/gene`。
- GeneScreener 页头：副标题加"（盘前简报的配置伴随页）"+ 回链。

## 6. 验收标准

- [ ] A1 盘前简报涨停基因因子呈现 L1/L2/L3 三层卡，每层 conditions+passed+filtered_out+输入→输出计数可见。
- [ ] A2 候选池 R1/R2/R3 漏斗在盘前简报同一页可见（第二组），逐层可验证。
- [ ] A3 点任一层候选 → 右侧抽屉弹诊断卡（不整页跳路由）；Esc/点遮罩可关；`/workflow/candidates/:code` 直链仍可用。
- [ ] A4 页内布局：情绪→因子漏斗→候选池漏斗 纵向清晰分区，无明显跳跃。
- [ ] A5 GeneScreener 有回链 + 定位说明；盘前简报有去 GeneScreener 的入口。
- [ ] A6 前端 tsc + 149 既有测试通过；新增 Sheet/FactorLayer 抽取组件测试；playwright 关键路由（pre-market → 抽屉 → 候选直链）冒烟。
- [ ] A7 数据：各层 passed/filtered 基于后端实际字段，禁臆造。

## 7. 合规与工程底线自查

- [x] 涨停股 code/name/得分/战法/仓位属客观事实 + 既有研究模式输出，可呈现（CLAUDE.md §1.1 私人助理口径）。
- [x] 判断可复现：层 conditions/passed/filtered 基于后端 report/ funnel 实际字段，禁臆造/心算。
- [x] 走既有 `/api/workflow/pre-market` + `/api/workflow/funnel/layers` + `/candidates/{code}/diagnosis`（em_get 限流+熔断已有），不新增裸调。
- [x] 私有数据不涉；不动 `.vibe-research/`。

## 8. 测试计划

- **前端单测**：`Sheet`（开/关/Esc）、`FactorLayerCard`（多层渲染 + conditions）、`CandidateDetailPanel`（诊断卡渲染）。
- **集成**：PreMarketBriefing 挂载 → 因子三层 + 候选池 R1-R3 均渲染（mock query）。
- **playwright（large 必）**：`/workflow/pre-market` 加载 → 点候选 → 抽屉开 → 关 → 直链 `/workflow/candidates/:code` 仍渲染。
- **后端**：`test_limitup_screener_factor_layers`——fetch 返 3 层 FunnelLayer，L1/L2/L3 passed/filtered 正确。
- **离线**：`pytest -m "not live"` 全过。

## 9. 风险与回滚

- **因子三层 passed 数据**：L2 战法依赖 `report.strategy_matches`（PreMarketWorkflow 限 `pool.candidates[:20]` 匹配，`pre_market_workflow.py:130`），超 20 的候选无战法数据 → L2 可能漏。spec 内标注此限制，或放宽匹配上限（另议）。
- **抽屉性能**：诊断卡 `candidatesApi.diagnosis(code)` 可能慢（实时算），抽屉内 loading 态必备。
- **FunnelLayers 抽取公共组件**：候选池页（`/candidates`）与盘前简报共用，改动影响候选池页，需回归测试。
- **回滚**：feature 分支，未合 develop 前 `git checkout develop` 即隔离；合并用 `--squash` 一 commit。

## 10. 决策记录（2026-08-06）

- **L2 战法上限**：放宽到全部 qualified（去 `pre_market_workflow.py:130` 的 `[:20]`）；L2 每项携 best_strategy/confidence 供视觉筛查。**后续 S031**：交互式按标的特性 + 战法因子继续筛查缩小范围（本 spec 不做，列 backlog）。
- **候选展开**：侧边抽屉（Sheet），不整页跳；路由保留供直链。
- **两套漏斗**：都默认展开，分区标题区分因子三步 vs 候选池 R1-R3。
