# Spec: S034 — SettlementEngine 接线（settled 流转即结算，写 winrate.db）

> 状态：已实现 2026-08-07（T1-T7 ✅；后端 815 passed + tsc 0 + vitest 190 全绿；冒烟实证：603221 重入一轮 entry 88.8→exit 92.1 结算 +3.72%/盈/4天，gene_score 回查真实值 61.3，winrate 记录写入后冒烟清理恢复 67 条用户记录）
> 作者：Claude  日期：2026-08-07
> 关联：`../S033-状态机前端呈现/spec.md`（铺路：holding 行 entry_price+strategy / settled 行 exit_price）、`../S032-调度收口第二轮/spec.md`（workflow_state 落库 + 手动流转）、`../S012-工作流标灰/spec.md`（`_settle_recommendations` 桩边界——本 spec 不碰）
>
> 级别：**medium**（跨层 >50 行；不碰新外部数据源——只读本地 SQLite；无新 AI 工具。盈亏结算是用户自录交易的客观记账，非公司财务验算）。
> 流程门（AGENTS.md）：直接 develop 提交 + spec 先行（SDD §0 非平凡必写）+ 单轮自查 + 后端冒烟。涉及交易数据输出 → 过合规自查（§7）。

---

## 1. 问题 / 目标

S033 已让 holding 行带 `entry_price+strategy`、settled 行带 `exit_price`（用户自填），但**结算断在最后一公里**：`SettlementEngine`（`backend/settlement/settlement_engine.py`）只在 `routers/workflow.py:97` 实例化、零调用；`winrate.db`（67 条用户手录记录）只靠 `POST /api/winrate/records` 手填。用户走完 candidate→…→settled 全流程后，胜率页看不到这笔交易——还得再手录一遍。

**目标**：settled 流转触发即结算——`SettlementEngine.settle()` 算 return_pct/won/hold_days，写 `winrate_records`（喂既有胜率页 stats/trends/strategy 拆分），`workflow_state.settled_at` 幂等防重；settled→candidate 重入清零开启新轮。

---

## 2. 背景

- `SettlementEngine.settle(SettlementInput)` → `SettlementResult`：`return_pct=(exit-entry)/entry*100`、`won=return_pct>0`、`hold_days=settle_date-signal_date`。纯计算，无 IO。
- `WinRateTracker(db_path="data/winrate.db")`：`add_record(WinRateRecord)` 写 `winrate_records`（stock_code/stock_name/strategy_used/entry_date/entry_price/exit_date/exit_price/return_pct/is_win/gene_score/sti_label/sector/created_at）。既有胜率端点（stats/trends/sector/strategy）全读这张表。
- `workflow_state` 现有列：code/name/trade_date/status/reason/created_at/updated_at/entry_price/exit_price/strategy（S033 扩）。无结算时间戳——同一股 settled→candidate→…→settled 重入（`_ALLOWED_TRANSITIONS` 允许）会重复结算，需幂等锚点。
- `gene_scores`：`limitup_screener.data.load_gene_scores(date)` 从基因 DB 按日重构 GeneScore（含 total_score）——结算记录的 gene_score 字段可回查真实值（喂 score_breakdown 拆分），查不到兜底 0.0。
- `PostMarketWorkflow._settle_recommendations` 返 `[]` 桩——S012 标灰范围，本 spec **不实现盘后批量结算**（transition 即结算后无积压可扫）。
- winrate.db 有 67 条用户真实手录记录——冒烟写入必须事后清理。

---

## 3. 需求清单

- [ ] R1 `workflow_state` 幂等扩列 `settled_at TEXT`（S033 `_ensure_columns` 模式）；`_row_to_state` 补字段。
- [ ] R2 新模块 `backend/settlement_recorder.py`：`record_settlement(state) -> dict | None`——校验 entry/exit 价齐 → `SettlementEngine().settle()` → 组 `WinRateRecord`（gene_score 回查基因 DB，失败 0.0；sti_label/sector 空）→ `_get_tracker().add_record()` → 返 `{return_pct, won, hold_days}`。`_get_tracker()` 可注入（测试隔离真实 winrate.db）。
- [ ] R3 `routers/workflow.py` transition 端点接线：target=settled 成功且 entry/exit 齐且 `settled_at` 空 → `record_settlement` + repo 落 `settled_at`；响应 data 带 `settlement`（记录成功=摘要；价缺={recorded:false, reason}）。
- [ ] R4 repo：`mark_settled(code, trade_date, settled_at)`；`transition()` 中 settled→candidate 重入时清 `settled_at=NULL`（新轮可再结算）。
- [ ] R5 单股端点 `GET /api/workflow/state/{code}`：`settled_at` 非空时响应附 `settlement`（由 entry/exit/trade_date/settled_at 确定性重算，不额外存储）。
- [ ] R6 前端 `WorkflowStateCard`：settlement 存在时显示收益摘要（return_pct 红涨绿跌 A 股口径配色 + 盈/亏标签）；vitest 补测。

### 明确不做

- 盘后批量自动结算（`_settle_recommendations` 桩，S012 范围）；transition 即结算后无积压。
- 持仓按市价自动结算（需行情数据源决策，另立 spec）。
- settled 后补填价格（缺价时结算跳过；用户可经 settled→candidate 重入补全流程）。

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/workflow_state_repo.py` | R1 settled_at 扩列 + R4 mark_settled + 重入清零 |
| `backend/settlement_recorder.py`（新） | R2 结算记录器 |
| `backend/routers/workflow.py` | R3 transition 接线 + R5 单股端点 settlement 摘要 |
| `frontend/src/components/workflow/WorkflowStateCard.tsx` | R6 收益摘要展示 |
| `backend/tests/test_s034_settlement.py`（新） | R2-R5 单测 |

---

## 5. 设计方案

### D1 触发模型：transition 即结算（非批量）

`POST transition target=settled` 成功 → 立即结算写 winrate.db。备选「盘后批量扫 settled 行」否决：S033 手动流转模型下 settled 必经端点，transition 时结算零积压、反馈即时；批量扫需要「已结算未记账」中间态，徒增复杂度（YAGNI）。

### D2 幂等锚点 settled_at

- 结算成功 → `settled_at = now_iso`。
- 重复请求天然防重：settled→settled 非法（状态机拒绝）；唯一重复路径是 settled→candidate→…→settled 重入——重入 transition 清 `settled_at=NULL`，新轮重新结算（语义正确：新一轮交易）。
- 缺价（entry/exit 任一为 NULL）：流转成功但不结算、不落 settled_at；响应 `settlement={recorded:false, reason:"缺少买入价/卖出价"}`。用户可重入补全。

### D3 entry_date 口径（诚实近似）

系统不记录实际买入日——`WinRateRecord.entry_date = trade_date`（候选日≈信号日），`exit_date = 结算日`（流转 settled 当天，北京时间）。hold_days = exit_date - trade_date。近似口径写入 spec + 代码注释，不伪装精确。

### D4 gene_score 回查

`load_gene_scores(trade_date)` 找 code 对应 `total_score`；任何异常/缺失 → 0.0（score_breakdown 落 low 桶，可接受）。sti_label/sector 无数据源 → 空串（winrate_records 列可空）。

### D5 结算摘要重算（R5）

单股端点不新存结算结果——`settled_at` 非空时由 `entry_price/exit_price/trade_date/settled_at` 确定性重算 return_pct/won/hold_days（纯算术，与 recorder 同一公式，抽 `settlement_summary()` 共享函数防漂移）。

### D6 winrate.db 路径与隔离

`_get_tracker()` 返 `WinRateTracker()`（默认 `data/winrate.db`，与 `routers/win_rate.py` 模块级 `_tracker` 同路径约定）。测试 monkeypatch `settlement_recorder._get_tracker` 注入 tmp db——绝不写用户真实 67 条记录。

---

## 6. 验收标准

- [ ] A1 `workflow_state` 有 `settled_at` 列；旧行 NULL。
- [ ] A2 settled 流转（entry/exit 齐）→ winrate_records 增一行（return_pct/is_win/strategy 正确）+ `settled_at` 落戳；transition 响应带 settlement 摘要。
- [ ] A3 缺价 settled → 流转成功、无 winrate 记录、无 settled_at、响应 reason 明确。
- [ ] A4 settled→candidate 重入清 settled_at；再走链到 settled 可再结算（新记录）。
- [ ] A5 gene_score 回查命中真实分值；基因 DB 无数据时 0.0 兜底不报错。
- [ ] A6 单股端点：settled 行附 settlement 摘要（与 recorder 同值）；未 settled 无该字段。
- [ ] A7 前端状态卡显示收益摘要；`pytest -m "not live"` + tsc + vitest 全过。
- [ ] A8 冒烟不污染用户 winrate.db（测试全走注入 tmp db；真实库冒烟后清理）。

---

## 7. 合规与工程底线自查（弱合规）

- [ ] 结算数据全部来自用户自填价格 + 系统实际流转时间——客观记账，无臆造；return_pct 由确定性公式计算（代码内算术，非分析性心算结论）。
- [ ] 胜率/收益属用户私有交易记录：winrate.db（`backend/data/*.db` gitignored）+ workflow_state 同库，不进 git、不上传。
- [ ] 无新增外部数据调用（gene_score 回查是本地 SQLite）。
- [ ] 输出无方向性研判（收益摘要是历史事实；胜率页既有轻量风险提醒不动）。

---

## 8. 测试计划

- **后端单测**（`test_s034_settlement.py`）：recorder 结算计算 + WinRateRecord 字段 + gene_score 回查/兜底；端点结算链路（注入 tmp winrate db）；缺价跳过；重入清零再结算；单股端点摘要。
- **前端**：WorkflowStateCard settlement 展示 vitest。
- **离线全量**：`pytest -m "not live"`（--deselect newsradar flaky）+ `npx tsc && npx vitest`。
- **冒烟**：:8901 起服 → 用 S033 冒烟遗留的 603221 settled 行（entry 88.8/exit 92.1）触发结算验证 → **验证后 DELETE 该冒烟 winrate 记录**（用户库 67 条真实记录不得污染）。

---

## 9. 风险与回滚

- **重复记账**：settled_at 锚点 + 状态机规则双保险；单测 A4 覆盖重入路径。
- **winrate 路径 cwd 依赖**（既有 wart：`data/winrate.db` 相对路径）：recorder 沿用同约定，不引入新不一致；修路径属 #5 DB 迁移 spec。
- **回滚**：develop 直提交按 commit revert；settled_at 列留存无害（NULL 无副作用）。

---

## 10. 决策记录（2026-08-07）

- **transition 即结算**：非批量（D1）——手动流转模型下无积压。
- **`_settle_recommendations` 不碰**：S012 标灰范围；本 spec 后该桩的「结算」职责事实上被 transition 结算取代，标灰 spec 落地时按桩处理即可。
- **entry_date=trade_date 近似**（D3）：系统无真实买入日，诚实标注。
- **持仓市价自动结算不做**：需行情源决策（em_get/mootdx 取舍 + 触发规则），另立 spec。
