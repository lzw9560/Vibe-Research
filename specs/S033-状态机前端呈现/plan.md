# Plan: S033 — 状态机前端呈现

> 对应 `spec.md`。细化扩表/单股端点/前端 API/hooks/徽标/状态卡/流转交互的技术方案。

---

## A 节：后端

### A1. 扩表（R1）

`workflow_state_repo._ensure_tables()` 末尾加 `_ensure_columns(conn)`：

```python
def _ensure_columns(conn: sqlite3.Connection) -> None:
    """幂等加列：entry_price/exit_price/strategy（SQLite 3.35+ 支持 DROP，但加了就留着）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_state)").fetchall()}
    for col, typ in [("entry_price", "REAL"), ("exit_price", "REAL"), ("strategy", "TEXT")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE workflow_state ADD COLUMN {col} {typ}")
    conn.commit()
```

现有 99 行数据三新列为 NULL。`_row_to_state()` 补三字段：

```python
def _row_to_state(row):
    return {
        **原字段,
        "entry_price": row["entry_price"],
        "exit_price": row["exit_price"],
        "strategy": row["strategy"],
    }
```

### A2. 扩 TransitionRequest + transition()（R2）

`routers/workflow.py`：

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

`workflow_state_repo.transition()` 的 UPDATE 改为 COALESCE：

```python
conn.execute(
    """UPDATE workflow_state
       SET status=?, reason=?, updated_at=?,
           entry_price=COALESCE(?, entry_price),
           exit_price=COALESCE(?, exit_price),
           strategy=COALESCE(?, strategy)
       WHERE code=? AND trade_date=?""",
    (target_status.value, reason, now,
     req.entry_price, req.exit_price, req.strategy,
     code, trade_date),
)
```

注意：`transition()` 签名需扩参收 `entry_price`/`exit_price`/`strategy`，或改收 dict。选扩参（显式可测）：

```python
def transition(code, trade_date, target, reason="",
               entry_price=None, exit_price=None, strategy=None) -> tuple[bool, str]:
```

`routers/workflow.py` 调用方传：

```python
ok, detail = _wf_state_repo.transition(
    code, req.date, req.target, req.reason,
    entry_price=req.entry_price, exit_price=req.exit_price, strategy=req.strategy,
)
```

### A3. 单股端点（R3）

`workflow_state_repo` 加：

```python
def get_state_with_targets(code: str, trade_date: str) -> Optional[Dict[str, Any]]:
    state = get_state(code, trade_date)
    if state is None:
        return None
    machine = WorkflowStateMachine(WorkflowStatus(state["status"]))
    return {**state, "allowed_targets": [s.value for s in machine.allowed_targets()]}
```

`routers/workflow.py` 加：

```python
@router.get("/api/workflow/state/{code}")
async def get_single_workflow_state(code: str, date: Optional[str] = Query(None)):
    d = date or last_trading_date_str()
    result = _wf_state_repo.get_state_with_targets(code, d)
    if result is None:
        raise HTTPException(404, f"该日无此股的工作流状态记录: code={code} date={d}")
    return {"data": result}
```

**路由冲突注意**：`GET /api/workflow/state/{code}/history` 已存在，`GET /api/workflow/state/{code}` 必须在它之前注册（FastAPI 路由匹配按注册顺序）。确认 `routers/workflow.py` 中 `/state/{code}` 在 `/state/{code}/history` 之前声明。

---

## B 节：前端

### B1. API 层 + hooks（R4）

`api/types.ts` 加类型：

```typescript
export interface WorkflowState {
  code: string; name: string; trade_date: string; status: string;
  reason: string; created_at: string; updated_at: string;
  entry_price?: number | null; exit_price?: number | null; strategy?: string | null;
  allowed_targets?: string[];
}
export interface TransitionRequest {
  code: string; date: string; target: string; reason?: string;
  entry_price?: number; exit_price?: number; strategy?: string;
}
export interface WorkflowStateHistoryItem {
  code: string; trade_date: string; from_status: string; to_status: string;
  reason: string; created_at: string;
}
```

`api/workflow.ts` 加 4 函数：

```typescript
export async function getWorkflowStates(date?: string) {
  const path = date ? `/workflow/state?date=${date}` : "/workflow/state";
  return await get<{date:string; states:WorkflowState[]; counts:Record<string,number>}>(path);
}
export async function getWorkflowState(code: string, date?: string) {
  const path = date ? `/workflow/state/${code}?date=${date}` : `/workflow/state/${code}`;
  return await get<WorkflowState>(path);
}
export async function transitionWorkflowState(req: TransitionRequest) {
  return await request<WorkflowState>("/workflow/state/transition", "POST", req);
}
export async function getWorkflowStateHistory(code: string, date?: string) {
  const path = date ? `/workflow/state/${code}/history?date=${date}` : `/workflow/state/${code}/history`;
  return await get<{code:string; date:string|null; history:WorkflowStateHistoryItem[]}>(path);
}
```

hooks（`lib/query/workflow.ts` 新建或并入既有）：

```typescript
export function useWorkflowStates(date?: string, options?: Opts<...>) {
  return useQuery({ queryKey: ["workflow","state",date] as const, queryFn: () => api.getWorkflowStates(date), ...options });
}
export function useWorkflowState(code: string, date?: string, options?: Opts<...>) {
  return useQuery({ queryKey: ["workflow","state",code,date] as const, queryFn: () => api.getWorkflowState(code, date), ...options, enabled: !!code });
}
export function useTransitionWorkflowState() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: TransitionRequest) => api.transitionWorkflowState(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflow","state"] }),
  });
}
export function useWorkflowStateHistory(code: string, date?: string, options?: Opts<...>) {
  return useQuery({ queryKey: ["workflow","state",code,"history",date] as const, queryFn: () => api.getWorkflowStateHistory(code, date), ...options, enabled: !!code });
}
```

### B2. 列表徽标（R5）

`FunnelLayerCard.tsx` 的 passed 列表每行加状态色块。用 `useWorkflowState(code, date)` 取单股状态（同日多行共享 query key，TanStack Query 自动去重）。

色板常量：

```typescript
const STATUS_COLORS: Record<string, string> = {
  candidate: "bg-blue-500", watching: "bg-yellow-500",
  monitoring: "bg-orange-500", holding: "bg-green-500",
  settled: "bg-gray-400", filtered: "bg-red-300",
  pending: "bg-gray-200",
};
```

passed 行渲染：

```tsx
{passed.map((c) => {
  const { data: state } = useWorkflowState(c.code, date);
  return (
    <button key={c.code} onClick={() => onPick(c.code)} className="flex items-center gap-2">
      <span className={cn("h-2 w-2 rounded-full", STATUS_COLORS[state?.status ?? "pending"])} />
      <span>{c.name}</span>
    </button>
  );
})}
```

**注意**：React hooks 不能在 map callback 里调 `useWorkflowState`——需提到组件层。方案：`FunnelLayerCard` 内部用 `useWorkflowStates(date)` 一次取全量，前端 `Map<code, status>` filter，不逐行调 hook。

### B3. 抽屉状态卡（R6）

新建 `components/workflow/WorkflowStateCard.tsx`：

```tsx
export function WorkflowStateCard({ code, date }: { code: string; date?: string }) {
  const { data: state } = useWorkflowState(code, date);
  const { data: history } = useWorkflowStateHistory(code, date);
  const transition = useTransitionWorkflowState();
  if (!state) return null;
  return (
    <GlassCard className="p-4">
      {/* 当前态徽标 */}
      <div className="flex items-center gap-2">
        <span className={cn("h-3 w-3 rounded-full", STATUS_COLORS[state.status])} />
        <span className="font-medium">{STATUS_LABELS[state.status]}</span>
      </div>
      {/* 流转历史 timeline */}
      {history?.length ? (
        <div className="mt-3 space-y-1">
          {history.map((h, i) => (
            <div key={i} className="text-xs text-muted-foreground">
              {h.from_status} → {h.to_status} {h.reason && `(${h.reason})`} · {h.created_at}
            </div>
          ))}
        </div>
      ) : null}
      {/* 流转按钮 */}
      <div className="mt-3 flex gap-2">
        {state.allowed_targets?.map((target) => (
          <TransitionButton key={target} code={code} date={date} target={target} onTransition={transition} />
        ))}
      </div>
    </GlassCard>
  );
}
```

`CandidateDetailPanel` 底部加 `<WorkflowStateCard code={code} date={date} />`。

### B4. 流转交互（R7）

`TransitionButton` 逻辑：

```tsx
function TransitionButton({ code, date, target, onTransition }) {
  const [showForm, setShowForm] = useState(false);
  const needsForm = target === "holding" || target === "settled";
  if (needsForm && !showForm) {
    return <button onClick={() => setShowForm(true)}>{STATUS_LABELS[target]}</button>;
  }
  if (showForm) {
    return <TransitionForm code={code} date={date} target={target} onSubmit={onTransition.mutateAsync} onCancel={() => setShowForm(false)} />;
  }
  // watching/monitoring 直接 POST
  return <button onClick={() => onTransition.mutate({ code, date, target })}>{STATUS_LABELS[target]}</button>;
}
```

`TransitionForm.tsx`（弹窗表单）：

```tsx
function TransitionForm({ code, date, target, onSubmit, onCancel }) {
  const [entryPrice, setEntryPrice] = useState("");
  const [exitPrice, setExitPrice] = useState("");
  const [strategy, setStrategy] = useState("");
  const handleSubmit = () => {
    onSubmit({
      code, date, target,
      entry_price: entryPrice ? Number(entryPrice) : undefined,
      exit_price: exitPrice ? Number(exitPrice) : undefined,
      strategy: strategy || undefined,
    });
    onCancel();
  };
  return (
    <div className="space-y-2">
      {target === "holding" && <input placeholder="买入价（可选）" value={entryPrice} onChange={e => setEntryPrice(e.target.value)} />}
      {target === "settled" && <input placeholder="卖出价（可选）" value={exitPrice} onChange={e => setExitPrice(e.target.value)} />}
      <select value={strategy} onChange={e => setStrategy(e.target.value)}>
        <option value="">选择战法（可选）</option>
        {STRATEGIES.map(s => <option key={s.code} value={s.name}>{s.name}</option>)}
      </select>
      <div className="flex gap-2">
        <button onClick={handleSubmit}>确认</button>
        <button onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}
```

8 大战法从 `GET /api/workflow/strategies`（已有端点）或常量硬编码。

### B5. filtered 徽标（R8）

`FunnelLayerCard` 的 `filtered_out` 列表每行带 `<span className="h-2 w-2 rounded-full bg-red-300" />`。

---

## 实现步骤

1. **A1** 扩表 `_ensure_columns` + `_row_to_state` 补字段 + 单测
2. **A2** 扩 `_TransitionRequest` + `transition()` COALESCE + 单测
3. **A3** `get_state_with_targets` + 单股端点 + 路由顺序确认 + 单测
4. **B1** 前端 API 4 函数 + types + 4 hooks
5. **B2** `FunnelLayerCard` 列表徽标（用 `useWorkflowStates` 全量取再 map）
6. **B3** `WorkflowStateCard` 新建 + `CandidateDetailPanel` 嵌入
7. **B4** `TransitionButton` + `TransitionForm` 流转交互
8. **B5** `filtered_out` 徽标
9. tsc + vitest + `pytest -m "not live"` 全过
