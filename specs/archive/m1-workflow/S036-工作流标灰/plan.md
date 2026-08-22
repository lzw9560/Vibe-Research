# 技术方案 · S036 工作流标灰

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 级别：medium，直接 develop 提交。

## 1. 文件结构与职责

### 改动后端
| 文件 | 改动 |
|---|---|
| `backend/routers/workflow.py` | 5 个桩端点改 early return `not_implemented`；`/workflow/refresh` 保留不变 |
| `backend/realtime_workflow.py` | 桩方法加 `# stub: 未实现，见 S036` 注释 |
| `backend/post_market_workflow.py` | 同上 |

### 改动前端
| 文件 | 改动 |
|---|---|
| `frontend/src/pages/workflow/IntradayMonitor.tsx` | 不调 `useIntradayData()`，渲染未实现横幅 |
| `frontend/src/pages/workflow/PostMarketReview.tsx` | 不调 `usePostMarketReview()`，渲染未实现横幅 |
| `frontend/src/pages/workflow/BombAlertPanel.tsx` | 不调 `useBombAlerts()`，渲染未实现横幅 |
| `frontend/src/pages/workflow/components/WorkflowStage.tsx` | 加 `notImplemented` prop，true 时渲染灰底横幅 |

## 2. 后端端点改写

### 2.1 early return 模式
```python
@router.get("/api/workflow/realtime")
async def realtime():
    return {"not_implemented": True, "message": "盘中监控未实现", "spec": "S036"}
```

5 个端点改写：`/workflow/realtime`（含 `/intraday` 别名）、`/workflow/post-market`、`/workflow/signals`、`/workflow/alerts`、`/workflow/settle`（POST）。

`/workflow/refresh` 保留不动（纯返回时间戳，非桩）。

### 2.2 桩方法不删
`realtime_workflow.py` / `post_market_workflow.py` 的桩方法保留签名 + 加注释。端点 early return 后桩不被触达，但保留签名防外部脚本调用报 AttributeError。

## 3. 前端改写

### 3.1 WorkflowStage 加 notImplemented prop
```tsx
interface WorkflowStageProps {
  // ...existing props
  notImplemented?: boolean;
}
// notImplemented=true 时渲染灰底 badge + 说明文案，替代 children
```

### 3.2 三页不调 hook
直接在组件内渲染 `<WorkflowStage notImplemented>` 横幅，不调 `useIntradayData` / `usePostMarketReview` / `useBombAlerts`。hook 定义保留不删。

### 3.3 路由和导航保留
`router.tsx` 三个路由 + `navigation.ts` 三个 nav item 不删，用户可导航到页面看到未实现横幅。
