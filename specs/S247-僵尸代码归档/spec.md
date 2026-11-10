# S247 · 僵尸代码归档（tail_dip + sector_rotation）

**状态**：已完成（2026-11-10，5 endpoint 全 410 + 353 backend 测试 + 435 前端测试 + tsc 0 error）
**日期**：2026-11-10
**分级**：medium（多文件 + 前端 + test + endpoint sunset，但非新功能）

## 问题

两个 falsified 策略的 endpoint/前端组件仍 live，误导未来会话 + 用户 UI 拿到死策略数据：
- **tail_dip**（2026-10-17 FALSIFIED）：backend router 已 410-sunset（`dependencies=[Depends(_falsified_gone)]`），但前端 `TailDipDeviationPanel.tsx` + `IntradayCockpit.tsx:222` 仍调 `/api/strategy/tail-dip/deviation`（拿 410）。
- **sector_rotation**（2026-11-08 5 方法全 FALSIFIED）：backend 4 个轮动 endpoint（`/sector-cycle` `/sector-rotation` `/concept-rotation` `/multi-rotation`）仍返数据；前端 `useSectorCycle`/`useSectorRotation` hooks + `SectorRotationNode` + `api.ts` getSectorRotation 仍在（大部分 dead path，`sharedSectorRotation=true` 默认不渲染）。

## 范围（归档）

**backend**：
- `routers/strategy.py` 4 个轮动 endpoint 加 410 falsified 通告（per-endpoint `dependencies=[Depends(_sector_falsified)]`，像 tail_dip）

**前端**：
- 删 `TailDipDeviationPanel.tsx` + `IntradayCockpit.tsx` 移除 import + line 222 调用
- 移除 dead hooks `useSectorCycle`/`useSectorRotation`（`lib/query/strategy.ts`）+ `useMultiRotation`（若只 SectorRotationNode 用）
- 移除 `SectorRotationNode`（`SelectionPipeline.tsx:225`）+ `sharedSectorRotation` prop（默认 true 已不渲染）
- 移除 `api.ts` `getSectorRotation`/`getSectorCycle`

**test**：
- `PreMarketBriefing.test.tsx` mock 更新（移除 useSectorCycle mock）
- `test_sector_cycle.py` **保留**（测 sector_cycle 模块函数 classify_phase/sector_breadth 等，模块 live）

## 不归档（live 依赖）

- `strategies/sector_cycle.py` 模块——`trend_swing_arm.py:45` import aggregate_sectors/classify_phase + `dimension_registry.py:48` 引用 zt_count_today + `/non-limitup-funnel` endpoint 直接调 sector_rotation() 函数
- `strategies/market_scan.py`——`workflow.py:302` + `strategy.py:254` live pipeline 依赖
- `/non-limitup-funnel` endpoint——候选生产管道，直接 import sector_rotation 函数不经轮动 endpoint

## 验收（2026-11-10 全通过）

- [x] backend 4 sector endpoint + tail-dip endpoint 返 410 falsified 通告（curl 验 HTTP 410 + body `{"detail":{"falsified":true,...}}`）
- [x] frontend `tsc --noUnusedLocals` 0 error
- [x] frontend vitest 435 passed / 60 files
- [x] backend pytest 353 passed（sector/strategy/tail_dip/s055）
- [x] grep 0 dangling 引用（TailDipDeviationPanel / useSectorCycle / SectorRotationNode）
- [x] 6 practitioner 任务仍在（count=6，重启未丢）

## 关键发现

**FastAPI `dependencies=[Depends(func)]` 返 JSONResponse 不短路**——dep 返回值被忽略，endpoint 函数体照常执行。tail_dip 的 `_falsified_gone` 自 2026-10-17 用 `return JSONResponse(410, ...)` 看着像 sunset 但从没真生效（curl 返 404 函数体非 410）。S247 改 `raise HTTPException(410, detail=...)` 才真短路。strategy.py 4 sector endpoint 同模式同修。详见 memory `fastapi-dependency-no-short-circuit`。

## 风险

- 前端组件移除可能影响 IntradayCockpit 布局（移除一个 panel，应可编译）
- useMultiRotation 若有其他调用方需保留（grep 确认只 SectorRotationNode 用）
- sharedSectorRotation prop 移除可能影响 SelectionPipeline 调用方
