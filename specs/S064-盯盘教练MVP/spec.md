# Spec: S064 — W-C 盯盘教练 MVP

> 状态：已实现（2026-08-13）— R1-R6 全落地：后端 intraday_coach.py（10 槽位时刻表 + get_current_slot 细粒度判定 + attention_mode 读写跨日重置 + build_condition_checklist 复用 workflow_state/funnel缓存/seal快照 + build_coach_state）+ routers/coach.py 4 端点 + 29 后端单测 passed；前端 IntradayCoach 页（时刻表/条件清单/模式选择/教学点/C 档铁律）+ 3 query hooks（交易时段门控轮询）+ 6 vitest passed；tsc 零错误。
> 作者：Claude  日期：2026-08-13
> 级别：medium（跨层 >50 行，不碰新外部数据源/不加 AI 工具/不涉及财务验算）
> 关联：`../../docs/workflows/short-term-win-rate-optimization-workflow.md` §12（D8 决策+W-C 阶段定义）、`../decision-log.md` DEC-004、`../S050-W0-行动闭环/spec.md`（attention_mode 全链路）、`../S055-盘中封单时序采集与炸板预警/spec.md`（bomb_alert_rules 复用）、`../S063-情绪管线贯通与盘中辅助决策/spec.md`（盘中轮询范式）

## 1. 问题 / 目标

用户自报"不会盯盘"——9:25 竞价确认、盘中回封确认、14:30 止损执行这些高价值时刻无载体；某天没时间盯盘则交易完整性断裂（漏止损是最大尾部风险）。工作流文档 §12 DEC-004 D8a 已采纳立"盯盘教练"为阶段 W-C。

目标（MVP 一期，§12.2 MVP 范围）：盘中时刻表页（10 槽位 + 当前环节高亮）+ 候选条件状态清单（逐只报战法条件达成度）+ 教学点（默认开）+ 降级模式盘前选择（A/B/C）。二期推送通知不在本 spec。

## 2. 背景

- `trading_workflow.get_current_stage()` 仅按小时粗判（8-9 pre-market / 9-15 intraday / 15-22 post-market），无 9:15/9:25/11:30 细粒度——时刻表须自建。
- `STRATEGY_REGISTRY`（limitup_strategy.py:497）条目条件是纯文本（`entry_condition: "首次涨停+基因得分≥60+量比>1.5"`），无 threshold/actual 结构化字段——MVP 不造结构化 schema，做"文本展示 + 已有结构化数据（matched_triggers/seal/bomb）核对"。
- `attention_mode` 全链路已存在（S050）：workflow_state 列 + winrate_records 列 + transition 端点请求体——只需读/回写，无需新迁移。
- `bomb_alert_rules.check_all_rules` 返回 `list[RuleCheckResult]`（含 data_status ok/missing）——条件状态清单直接复用，缺数据返 missing 不臆造。
- 前端轮询门控范式：`lib/query/limitup.ts:315 isInAuctionWindow` + 函数式 `refetchInterval`。
- UI 组件：自研 GlassCard/PageHeader/SectionHeader/TabBar/MetricCard/Disclaimer；教学点用 GlassCard+Lightbulb 惯例。

## 3. 需求清单

- [ ] R1 时刻表引擎：10 槽位纯静态数据（从 workflow doc §12.2 搬运）+ `get_current_slot(now)` 细粒度判定（9:15/9:20/9:25/11:30/14:30 边界）
- [ ] R2 attention_mode 读写：`coach_config.json` 持久化，跨日自动重置 A（复用 limitup_params.json 文件模式）
- [ ] R3 候选条件状态清单：`build_condition_checklist(date)` 组装 watching/monitoring/holding 状态的 code 的 strategy/matched_triggers/bomb_status/seal_amount/max_hold_warning
- [ ] R4 教练状态组装：`build_coach_state(date, now)` = current_slot + attention_mode + checklist + mode_rules + teaching_point
- [ ] R5 4 个 REST 端点：timetable / status / attention-mode GET / attention-mode POST
- [ ] R6 前端盯盘教练页：时刻表纵向时间线（当前高亮）+ 条件清单 + 模式选择（TabBar A/B/C）+ 教学点 + 降级规则展示 + Disclaimer

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/intraday_coach.py` | R1-R4：TimetableSlot + TIMETABLE + get_current_slot + attention_mode 读写 + build_condition_checklist + build_coach_state |
| ➕`backend/routers/coach.py` | R5：4 端点 |
| `backend/app.py` | 注册 coach router |
| ➕`backend/data/coach_config.json` | attention_mode 持久化（gitignored，同 limitup_params.json） |
| ➕`backend/tests/test_intraday_coach.py` | R1-R4 单测 |
| ➕`frontend/src/lib/api/coach.ts` | 4 api 函数 |
| ➕`frontend/src/lib/query/coach.ts` | 3 hooks + 交易时段门控轮询 |
| `frontend/src/lib/api/types.ts` | 类型定义 |
| ➕`frontend/src/pages/workflow/IntradayCoach.tsx` | R6：盯盘教练页 |
| `frontend/src/router.tsx` | 加 /workflow/coach 路由 |
| `frontend/src/components/layout/navigation.ts` | SUB_TABS["/workflow"] 加"盯盘教练" |

## 5. 设计方案

- **时刻表纯静态**：10 槽位内容从 workflow doc §12.2 逐行搬运，零外部调用、零数据采集——纯计算可单测。
- **条件清单不造结构化 schema**：STRATEGY_REGISTRY 条件是纯文本，MVP 只展示文本 + 已有结构化数据（matched_triggers from funnel cache / bomb_status from check_all_rules / seal_amount from snapshots）核对，不新造 threshold/actual schema。
- **不建后端采样循环**：时刻表是纯计算，状态查询即时组装——前端轮询 GET 端点即可（仿 isInAuctionWindow 函数式 refetchInterval 门控）。
- **attention_mode 复用 S050 全链路**：不新迁移，只读 workflow_state + 写 coach_config.json（盘前选择，结算时透传已有路径）。
- **降级模式**：A=完整时刻表；B=只推两次（9:20 清单+14:25 止损提醒）；C=四条铁律（禁开新仓/止损前置条件单/max_hold 持仓置顶/收盘复盘）。MVP 只展示规则文本，不实现推送（二期）。
- **方向建议口径**（§12.3）：MVP **不输出方向建议**，仅条件状态+教学点；方向建议留后续 spec（需数据+规则背书+三情景测算，超 MVP 范围）。
- **合规**：教学点讲机制不讲动作（§12.4）；教学点/时刻表是客观规则展示；无新 em_get 调用；缺数据标 missing 不臆造。

## 6. 验收标准

- [ ] A1 `GET /api/coach/timetable` 返回 10 槽位 + 当前槽位正确（边界时间 09:14/09:15/09:25/11:30/14:30/15:01/周末）
- [ ] A2 `GET /api/coach/status` 返回 checklist（有持仓/候选时逐只组装；空时返空列表）
- [ ] A3 `POST /api/coach/attention-mode` + `GET` 闭环；跨日自动重置 A
- [ ] A4 前端页渲染：时刻表纵向时间线 + 当前槽位高亮 + 条件清单 + 模式选择 + 教学点
- [ ] A5 `pytest -m "not live"` + `tsc --noEmit` + `npx vitest run` 全绿
- [ ] A6 合规自查（§7）逐条通过

## 7. 合规与工程底线自查（逐条确认）

- [ ] 教学点/时刻表是客观规则展示，非方向建议（§12.3 口径，MVP 无方向建议输出）
- [ ] 条件状态缺数据返 missing 不臆造（复用 bomb_alert_rules data_status 语义）
- [ ] 无新 em_get 调用（build_condition_checklist 只读已有缓存/DB，不触发外部采集）
- [ ] attention_mode 读写不涉及用户私有数据（模式选择是用户偏好，非持仓/key）
- [ ] 无持仓/无候选时返空列表（诚实，不编造）
- [ ] 教学点挂轻量风险提醒（Disclaimer 组件）

## 8. 测试计划

- 后端单测 `tests/test_intraday_coach.py`：时刻表槽位边界判定 + attention_mode 读写/跨日重置 + build_condition_checklist（mock repo）+ build_coach_state 端到端
- 前端 vitest：时刻表渲染 + 当前槽位高亮 + attention_mode 切换 + 空态
- 全量：`pytest -m "not live"` + `tsc --noEmit` + `npx vitest run`
- 冒烟（用户走查）：:8900/:5899 /workflow/coach 页

## 9. 风险与回滚

- 时刻表槽位边界判定错误 → 教学点错时显示（已守：边界单测覆盖）
- build_condition_checklist 依赖 funnel 缓存未预热 → 返空（已守：空列表诚实标注，不臆造）
- attention_mode JSON 文件并发写 → 损坏（低风险，单用户场景；可加 try/except 兜底）
- 回滚：删 intraday_coach.py + routers/coach.py + 前端页 + 路由/导航条目；coach_config.json 不影响其他模块
