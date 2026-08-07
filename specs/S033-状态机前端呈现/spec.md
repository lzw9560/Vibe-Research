# Spec: S033 — 状态机前端呈现（状态徽标 + 流转按钮 + holding 价格采集）

> 状态：草案 2026-08-07（grill 已过，待实现）
> 作者：Codex（grill 驱动）  日期：2026-08-07
> 关联：`../S032-调度收口第二轮/spec.md`（R10 状态机接线落库，后端已实现）、`../S031-调度收口盘前多层按战法回测/spec.md`（Sheet 抽屉 + CandidateDetailPanel + 多层漏斗，已实现）
>
> 级别：medium（跨层、>50 行；不碰外部数据源；直接 develop 提交 + 单轮 issue 层 review）
> 为 S034 SettlementEngine 接线铺路：holding 流转时采集 entry_price/strategy，settled 流转时采集 exit_price。

---

## 1. 问题 / 目标

S032 已将七态状态机后端全实现（`workflow_state_repo` + 3 个 API + DB 99 行数据在积累），但**前端零集成**——用户看不到状态分布、不能手动流转、不能记录买卖价。`CandidateDetailPanel`（S031 抽屉）只展示诊断卡，无状态信息。`workflow_state` 表无 `entry_price`/`exit_price`/`strategy` 列，S034 SettlementEngine 接线时无结算输入。

**目标**：前端呈现工作流状态（列表徽标 + 抽屉状态卡 + 流转历史 timeline + 流转按钮），扩表采集 holding/settled 的买卖价和战法为 S034 铺路。

---

## 2. 背景

- **状态机**：`workflow_state_machine.py` 七态 pending→candidate→watching→monitoring→holding→settled（旁路 filtered），`_ALLOWED_TRANSITIONS` 定义合法流转，`allowed_targets()` 返回当前态可流转目标。
- **落库**：`workflow_state_repo.py`（S032）已实现 `ensure_candidate`/`ensure_filtered`/`transition`/`get_state`/`list_states`/`get_history`/`allowed_targets`，DB 表 `workflow_state`（8 列：id/code/name/trade_date/status/reason/created_at/updated_at）+ `workflow_state_history`。99 行数据（98 filtered + 1 watching）。
- **API**：`GET /api/workflow/state?date=`（全日列表+计数）、`POST /api/workflow/state/transition`（手动流转）、`GET /api/workflow/state/{code}/history`（流转历史）。
- **_TransitionRequest**：`class _TransitionRequest(BaseModel): code: str; date: str; target: str; reason: str = ""`——无价格/战法字段。
- **前端**：`api/workflow.ts` 有 5 个函数（status/pre-market/refresh/intraday/post-market）但**无 state 相关**。`CandidateDetailPanel`（`CandidateDetail.tsx:27`）纯诊断卡，无状态。`PreMarketBriefing.tsx` 的 Sheet 抽屉（S031）已接 `CandidateDetailPanel`。`FunnelLayerCard`（S031）渲染 passed 列表，每行候选可点。
- **8 大战法**：`limitup_strategy.STRATEGY_REGISTRY`（首板挖掘/连板接力/炸板回封/低吸龙头/反包战法/N字反击/平台突破/尾盘偷袭）。

---

## 3. 需求清单

### A 节：后端

- [ ] R1 扩 `workflow_state` 表加 `entry_price REAL`/`exit_price REAL`/`strategy TEXT` 三列（ALTER TABLE 幂等——PRAGMA table_info 检查列已存在则跳过）
- [ ] R2 扩 `_TransitionRequest` 加 `entry_price: float | None = None`/`exit_price: float | None = None`/`strategy: str | None = None`；`workflow_state_repo.transition()` UPDATE 时写入（None 不覆盖已有值）
- [ ] R3 加 `GET /api/workflow/state/{code}?date=` 单股端点——返 `{...state, allowed_targets: [...]}`；`workflow_state_repo` 加 `get_state_with_targets(code, date)`

### B 节：前端

- [ ] R4 API 层：`api/workflow.ts` 加 `getWorkflowStates(date)`/`getWorkflowState(code, date)`/`transitionWorkflowState(req)`/`getWorkflowStateHistory(code, date?)`；`lib/query/workflow.ts` 加对应 hooks（`useWorkflowStates`/`useWorkflowState`/`useTransitionWorkflowState`/`useWorkflowStateHistory`）
- [ ] R5 列表徽标：`FunnelLayerCard` passed 列表每行候选带状态色块（candidate=蓝/watching=黄/monitoring=橙/holding=绿/settled=灰/filtered=红淡）；调 `useWorkflowState(code, date)` 取单股状态
- [ ] R6 抽屉状态卡：`CandidateDetailPanel` 底部加 `WorkflowStateCard`——当前态徽标 + 流转历史 timeline（from→to+reason+时间）+ 流转按钮（只渲染 `allowed_targets`）
- [ ] R7 流转交互：watching/monitoring 按钮→直接 POST（无弹窗）；holding/settled 按钮→弹窗表单（entry_price/exit_price input + strategy 下拉选 8 大战法），字段可选填，不填也能 POST
- [ ] R8 filtered 徽标：L1 打分层 `filtered_out` 列表也带红色淡徽标（和 workflow_state 的 filtered 一致）

---

## 4. 受影响文件

### A 节

| 文件 | 改动 |
|---|---|
| `backend/workflow_state_repo.py` | R1 `_ensure_tables` 加 ALTER TABLE 幂等扩列；R2 `transition()` 写入 entry_price/exit_price/strategy；R3 加 `get_state_with_targets(code, date)` |
| `backend/routers/workflow.py` | R2 `_TransitionRequest` 加三可选字段；R3 加 `GET /api/workflow/state/{code}?date=` 单股端点 |

### B 节

| 文件 | 改动 |
|---|---|
| `frontend/src/lib/api/workflow.ts` | R4 加 4 个 state API 函数 |
| `frontend/src/lib/api/types.ts` | R4 加 `WorkflowState`/`TransitionRequest`/`WorkflowStateHistory` 类型 |
| `frontend/src/lib/query/workflow.ts`（新或并入既有） | R4 加 4 个 hooks |
| `frontend/src/components/ui/FunnelLayerCard.tsx` | R5 passed 列表行加状态色块徽标 |
| `frontend/src/pages/workflow/CandidateDetail.tsx` | R6 `CandidateDetailPanel` 底部加 `WorkflowStateCard` |
| `frontend/src/components/workflow/WorkflowStateCard.tsx`（新） | R6 状态徽标 + 流转历史 timeline + 流转按钮 + 弹窗表单 |
| `frontend/src/components/workflow/TransitionForm.tsx`（新） | R7 holding/settled 弹窗表单（价格 + 战法下拉） |

---

## 5. 设计方案

### R1 扩表（ALTER TABLE 幂等）

```python
def _ensure_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_state)").fetchall()}
    if "entry_price" not in cols:
        conn.execute("ALTER TABLE workflow_state ADD COLUMN entry_price REAL")
    if "exit_price" not in cols:
        conn.execute("ALTER TABLE workflow_state ADD COLUMN exit_price REAL")
    if "strategy" not in cols:
        conn.execute("ALTER TABLE workflow_state ADD COLUMN strategy TEXT")
    conn.commit()
```

在 `_ensure_tables()` 末尾调 `_ensure_columns(conn)`。现有 99 行数据三新列为 NULL，不影响查询。

### R2 扩 TransitionRequest + transition()

```python
class _TransitionRequest(BaseModel):
    code: str
    date: str
    target: str
    reason: str = ""
    entry_price: float | None = None
    exit_price: float | None = None
    strategy: str | None = None
```

`transition()` 的 UPDATE 加三列——None 不覆盖已有值（COALESCE 语义）：

```sql
UPDATE workflow_state
SET status=?, reason=?, updated_at=?,
    entry_price=COALESCE(?, entry_price),
    exit_price=COALESCE(?, exit_price),
    strategy=COALESCE(?, strategy)
WHERE code=? AND trade_date=?
```

### R3 单股端点

```python
@router.get("/api/workflow/state/{code}")
async def get_single_workflow_state(code: str, date: Optional[str] = Query(None)):
    d = date or last_trading_date_str()
    state = _wf_state_repo.get_state(code, d)
    if state is None:
        raise HTTPException(404, f"该日无此股的工作流状态记录: code={code} date={d}")
    return {"data": {**state, "allowed_targets": _wf_state_repo.allowed_targets(code, d)}}
```

### R4 前端 API + hooks

```typescript
// api/workflow.ts
export async function getWorkflowStates(date?: string): Promise<WorkflowStateList | null> { ... }
export async function getWorkflowState(code: string, date?: string): Promise<WorkflowState | null> { ... }
export async function transitionWorkflowState(req: TransitionRequest): Promise<WorkflowState | null> { ... }
export async function getWorkflowStateHistory(code: string, date?: string): Promise<WorkflowStateHistory[] | null> { ... }
```

hooks 仿 `usePreMarketBriefing` 范式。`useTransitionWorkflowState` 是 mutation（成功后 invalidate `["workflow","state"]` 前缀）。

### R5 列表徽标

`FunnelLayerCard` 的 passed 列表每行：

```tsx
<span className={cn("h-2 w-2 rounded-full", STATUS_COLORS[state?.status ?? "candidate"])} />
```

色板：candidate=蓝(`bg-blue-500`)/watching=黄(`bg-yellow-500`)/monitoring=橙(`bg-orange-500`)/holding=绿(`bg-green-500`)/settled=灰(`bg-gray-400`)/filtered=红淡(`bg-red-300`)。

每行调 `useWorkflowState(code, date)`——同日多行候选共享一个 query key 前缀，TanStack Query 自动去重。

### R6 抽屉状态卡

`CandidateDetailPanel` 底部加 `<WorkflowStateCard code={code} date={date} />`：

- 当前态徽标（同色板，大号）
- 流转历史 timeline（from→to + reason + created_at，倒序）
- 流转按钮组（只渲染 `allowed_targets`）

### R7 流转交互

- `watching`/`monitoring` 按钮：直接 `transitionWorkflowState({code, date, target})`，无弹窗
- `holding`/`settled` 按钮：弹 `<TransitionForm>`（`entry_price` input + `exit_price` input + `strategy` 下拉选 8 大战法 + `reason` input），字段可选填，不填也能 POST
- 成功后 invalidate query 刷新徽标 + 状态卡

### R8 filtered 徽标

L1 打分层 `filtered_out` 列表（`FunnelLayerCard` 的 filtered_out 区）每行带红色淡徽标（`bg-red-300`），和 workflow_state 的 filtered 一致。

---

## 6. 验收标准

- [ ] A1 `workflow_state` 表有 `entry_price`/`exit_price`/`strategy` 三列；现有 99 行数据三列为 NULL 不报错。
- [ ] A2 `POST /api/workflow/state/transition` 带 `entry_price`/`exit_price`/`strategy` 时写入；不传时保持已有值（COALESCE）。
- [ ] A3 `GET /api/workflow/state/{code}?date=` 返单股状态 + `allowed_targets`；无记录返 404。
- [ ] A4 前端列表徽标：`FunnelLayerCard` passed 列表每行候选带状态色块，颜色对应 workflow_state 的 status。
- [ ] A5 抽屉状态卡：`CandidateDetailPanel` 底部有当前态徽标 + 流转历史 timeline + 流转按钮（只渲染 allowed_targets）。
- [ ] A6 watching/monitoring 流转直接 POST 无弹窗，成功后徽标刷新。
- [ ] A7 holding/settled 流转弹窗表单，可填 entry_price/exit_price/strategy（可选），不填也能 POST。
- [ ] A8 L1 打分层 filtered_out 列表带红色淡徽标。
- [ ] A9 前端 tsc + vitest 全过（含 WorkflowStateCard/TransitionForm 新测）。
- [ ] A10 `pytest -m "not live"` 全过（含扩表/单股端点新测）。
- [ ] A11 数据：状态徽标基于 `workflow_state` DB 实际数据，禁臆造。流转写入基于 `_ALLOWED_TRANSITIONS` 规则校验，非法流转 400。

---

## 7. 合规与工程底线自查

- [ ] 状态机流转是客观状态记录，不含买卖指令。holding/settled 的 entry_price/exit_price/strategy 是用户自填的操作记录，非系统推荐。
- [ ] 状态徽标基于 DB 实际数据，禁臆造。
- [ ] 用户私有数据（entry_price/exit_price/持仓价）走 `market_data.db`（项目内），不进 git。
- [ ] 不新增 em_get 调用。
- [ ] 战法名称属公开知识，可呈现。

---

## 8. 测试计划

- **后端单测**：`test_workflow_state_columns`（扩表后三列存在+旧数据 NULL）、`test_transition_with_price`（带 entry_price 的流转写入）、`test_single_state_endpoint`（单股端点返 allowed_targets+404）。
- **前端单测**：`WorkflowStateCard`（徽标颜色+timeline 渲染+按钮只渲染 allowed_targets）、`TransitionForm`（弹窗表单提交+可选字段）、`FunnelLayerCard` 徽标（状态色块渲染）。
- **集成**：PreMarketBriefing 挂载 → 列表徽标可见 → 点候选抽屉 → 状态卡可见 → 流转 → 徽标刷新（mock query）。
- **离线**：`cd backend && .venv/bin/python -m pytest -m "not live"` + `cd frontend && npx tsc && npx vitest` 全过。

---

## 9. 风险与回滚

- **ALTER TABLE 幂等**：PRAGMA table_info 检查列已存在跳过，不会重复加列。旧数据 NULL 不影响查询。回滚：列加上了就加上了（SQLite 无 DROP COLUMN < 3.35），但 NULL 列无副作用。
- **前端徽标查询量**：同日多行候选共享 query key 前缀，TanStack Query 自动去重。但 99 行全量列徽标 = 99 个 `useWorkflowState`——需确认 hook 按 code 去重不重复请求。备选：用 `useWorkflowStates(date)` 一次取全量再前端 map。
- **回滚**：medium 直接 develop，`git revert` 即可。

---

## 10. 决策记录（2026-08-07，grill）

- **① 扩表为 ③ 铺路**：holding 流转时采集 entry_price+strategy，settled 流转时采集 exit_price，存进 workflow_state 新列。S034 SettlementEngine 接线时读 holding 行直接有结算输入。
- **列表+抽屉都做徽标**：列表扫一眼看全局状态分布，抽屉看单股详情+操作流转。
- **加单股端点**：`GET /api/workflow/state/{code}?date=` 返单股状态+allowed_targets，不靠全量 filter。
- **流转交互**：watching/monitoring 直接 POST；holding/settled 弹窗表单填价格+战法（可选）。
- **filtered 两处都标**：列表 filtered_out 带红淡徽标，和 workflow_state 的 filtered 一致。
- **为 S034 SettlementEngine 接线铺路**：本 spec 采集的 entry_price/exit_price/strategy 是 ③ 接线的输入。
