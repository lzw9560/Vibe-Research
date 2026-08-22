# S056 原子任务清单

> 级别：medium（跨层；无新外部数据源）
> 基线：后端 1022 passed / 前端 41 files 305 tests（S058 验收后）。
> 依赖：R2 撤单熔断依赖 S055 封单时序（未合并前置桩）；R1/R3 独立先行。

## S1 R1 仓位熔断

- [x] T1 `/api/sentiment/weather/fuse` 补全规则内容 + fuse_state 汇总：
  - R1 暴风雨 → position_fuse.is_triggered=True, current_state=triggered
  - fuse_state = any_triggered ? "triggered" : "normal"
  - 单测：暴风雨触发 / 晴天正常 / 三规则齐全 ✅ 3 passed

## S2 R2 撤单熔断置桩

- [x] T2 R2 撤单熔断置桩：data_status=待S055，is_triggered=False
  - 单测：cancel_fuse.data_status == "待S055" ✅

## S3 R3 次日强制离场信号

- [x] T3 `/api/sentiment/weather/exit-signals` 新端点：
  - 持仓股（workflow_state holding）竞价未高开/破均线 → 强制离场信号
  - 软 gate：信号 + 提醒，不自动下单
  - 缺数据诚实标注（data_status=missing）
  - 单测：无持仓返空 / 行情缺失 missing / 未高开触发 ✅ 3 passed

## S4 前端类型 + 全测

- [x] T4 前端类型：FuseRule 增 is_triggered/weather_state/data_status；FuseState + ExitSignalsResult 新增
  - tsc 过 ✅

- [x] T5 离线全测：`pytest -m "not live"` 全绿（后端 +7 新）；`tsc + vitest run` 全绿

## S5 归档

- [x] T6 spec.md 状态改已实现 + commit `docs(S056): 验收`
