# Spec: S029 — 涨停基因选股条件动态可配 + 执行检索（GeneScreener 接通）

> 状态：已实现(2026-08-06)（决策 A3/B1/C1 已定）
> 作者：Claude  日期：2026-08-06
> 关联：S028（limitup 文案/触发/R3/条件）、S023（漏斗可用性与因子解耦）、S005（价值漏斗参考）
> 级别：medium（纯前端接通 + 复用既有 /api/limitup/screener，不加新外部源；>50 行）
>
> 验收：A1/A3/A4 经前端 149 测试 + build 通过 + 后端 /api/limitup/screener 数据核对（79 只/五维 factors/backtest 齐全）；A2 阈值持久化+trigger 复用 S028 端点（200）；A5 tsc 通过。改动 commit 于 develop。

## 1. 问题 / 目标

`/limitup/gene` 的 GeneScreener 页面是**空壳**：`GeneFilterForm`（minScore/maxScore/日期）+ `GeneResultTable`（code/name/total_score）UI 已存在，但 `loadData` 是假的 `setTimeout(setData([]),500)`，**没调后端**——点筛选啥也不返回。

同时盘前简报的"涨停基因选股"因子被压成单层（`limitup_screener_factor.py:82` "单层包装"），而 PreMarketWorkflow 内部其实多步（五维打分→候选池→战法匹配→仓位建议），用户期望多层可视。

**目标**：接通 GeneScreener，让用户能动态配置涨停基因选股条件 → 执行检索 → 看多层结果，看清"扫了什么、每层留了什么"。

## 2. 背景

### 前端现有 scaffold
- `frontend/src/pages/limitup/GeneScreener.tsx`：loadData 假实现（:12-18）。
- `components/GeneFilterForm.tsx`：`{minScore=60, maxScore=100, date}` → `onSearch(params)`。
- `components/GeneResultTable.tsx`：渲染 `row.{code,name,total_score}`，≥75 primary / ≥60 blue / 其余 gray，可展开（`expandedCode`/`onToggle`）。

### 后端已就绪（S028 后）
- `GET /api/limitup/screener?date=` → `ScreenerResult{gene_scores:[{code,name,total_score,factors{次日溢价率/红盘率/封板率/炸板后溢价/涨停频次},qualify,high_gene,...}], qualified, high_gene}`（`routers/limitup/screener.py:20`）。
- `GET/POST /api/limitup/screener/params` → `{gene_qualify_threshold, gene_high_threshold, lookback_days}`，持久化到 `backend/data/limitup_params.json`，POST 更新模块常量（`routers/common.py:84-98`）。
- `POST /api/limitup/screener/trigger` → 手动触发今日预计算（S028 R2 修好）。

### 基因得分口径（S028 已查清）
- 五维加权（`limitup_screener/models.py:133-143` calc_total_score）：次日溢价率 25% + 红盘率 25% + 封板率 25% + 炸板后溢价 15% + 涨停频次 10%。
- 阈值常量 `GENE_QUALIFY_THRESHOLD=60`、`GENE_HIGH_THRESHOLD=75`（可被环境变量覆盖，也可被 POST /params 改模块常量）。
- **注意**：改阈值不会重算已入库的 `qualify` 标志（`qualify` 在 `compute_gene_score` 入库时按当时阈值算定）。客户端按 `total_score` 范围筛是即时生效的；改合格阈值要重新打 qualify 标志需重跑。

## 3. 需求清单

- [ ] R1 接通 loadData：`onSearch(params)` → 调 `GET /api/limitup/screener?date=` → 按 `minScore/maxScore` 客户端过滤 → `setData(gene_scores)`；GeneResultTable 渲染真实 `code/name/total_score`。
- [ ] R2 阈值动态可配（B1）：GeneFilterForm 加 `gene_qualify_threshold`(60)/`gene_high_threshold`(75)/`lookback_days` 字段 → 改后 `POST /api/limitup/screener/params` 持久化 + `POST /api/limitup/screener/trigger` 重跑 → 重新检索。form 的 `minScore/maxScore` 仍作客户端得分区间过滤（即时）。
- [ ] R3 可展开多层明细（A3）：GeneResultTable 每行 expand → 显示五维 factors（次日溢价率/红盘率/封板率/炸板后溢价/涨停频次）+ qualify/high_gene 标记；qualified 行提供"看战法/仓位"链接跳 `/workflow/candidates/:code`（S028 已修好）。
- [ ] R4 执行检索反馈：loading/空/错误态；顶部摘要"扫描 N 只 / 合格 M 只 / 高基因 K 只"。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/pages/limitup/GeneScreener.tsx` | loadData 接真实 API；onSearch 接 params+阈值；摘要 |
| `frontend/src/pages/limitup/components/GeneFilterForm.tsx` | 加 qualify/high/lookback 阈值字段（B1） |
| `frontend/src/pages/limitup/components/GeneResultTable.tsx` | expand 渲染五维 factors + qualify/high 标记 + 战法/仓位跳链 |
| `frontend/src/lib/limitup.ts`（新或并入既有） | `getGeneScreener(date)` / `saveGeneParams(params)` / `triggerGenePrecompute()` API 封装 |

后端不改（端点 S028 后已齐：`GET /api/limitup/screener`、`GET/POST /api/limitup/screener/params`、`POST /api/limitup/screener/trigger`）。

## 5. 设计方案（A3 / B1 / C1 已定）

- **页面**：`/limitup/gene` GeneScreener（C1）。盘前简报保持只读。
- **多层**：A3 可展开明细——每行 expand 看五维 factors（得分组成）+ qualify/high 标记。不改 PreMarketWorkflow，不引入三层 FunnelLayer 重构。战法/仓位不在本页内嵌（需 per-stock 算，且对非合格股无意义）→ qualified 行跳候选详情页看。
- **配置**：B1 阈值——qualify/high/lookback 走既有 `POST /api/limitup/screener/params`（持久化 + 改模块常量）+ `POST /trigger` 重跑。**不做权重可配**（B2 需重算历史，列未来）。
- **检索流**：改阈值→存 params→trigger 重跑（后台异步，~90s 内懒算落库）→ 重新 `GET /api/limitup/screener` 取新数据。minScore/maxScore 是即时客户端过滤，不等重跑。
- **数据源**：`GET /api/limitup/screener?date=` → `ScreenerResult.gene_scores[]`，每项含 `code/name/total_score/factors{五维}/qualify/high_gene`。前端按 minScore/maxScore 过滤 + 摘要统计。

## 6. 验收标准

- [ ] A1 点筛选 → GeneResultTable 显示真实涨停股 + total_score（非空，今日 79 只）。
- [ ] A2 改 qualify 阈值 → 持久化（`GET /api/limitup/screener/params` 反映新值）+ trigger 重跑后重检索，qualify 标志按新阈值。
- [ ] A3 行 expand → 显示五维 factors + qualify/high 标记；qualified 行有跳候选详情链接（不报 Lazy 错）。
- [ ] A4 loading/空/错误态 + 摘要"扫描 N / 合格 M / 高基因 K"显示。
- [ ] A5 前端 tsc 通过；数据摘要基于后端实际字段，禁臆造。

## 7. 合规与工程底线自查

- [x] 涨停股 code/name/得分属公开榜单客观事实，可呈现。
- [x] 条件可配不涉研判方向；阈值是筛选参数。
- [x] 走既有 `/api/limitup/screener`（em_get 限流+熔断已有），不新增裸调。
- [x] 私有数据不涉。

## 8. 测试计划

- 前端：组件单测（GeneFilterForm params、GeneResultTable 渲染）。
- 后端：若加权重配置端点，补 `test_limitup_screener_params`（阈值/权重持久化 + 重算 qualify）。
- 手动：`/limitup/gene` 筛选 → 看真实数据；改阈值 → 重检索。

## 9. 风险与回滚

- **trigger 重跑是后台异步**（~90s 懒算落库），改阈值后检索需等重跑完成才反映新 qualify 标志——前端应提示"重算中"，或先按 minScore/maxScore 即时过滤、qualify 标志待重跑后刷新。
- **qualified 行跳候选详情**依赖 `/workflow/candidates/:code`（S028 已修 Lazy bug）；未合格股无战法/仓位，不跳。
- 回滚：纯前端，revert 即可。

## 10. 决策记录（2026-08-06）

- A3 可展开多层明细（每行 expand 看五维 + qualify/high；战法/仓位跳候选详情）。
- B1 只配阈值（qualify/high/lookback；不做权重可配）。
- C1 GeneScreener 页（`/limitup/gene`），盘前简报保持只读。
