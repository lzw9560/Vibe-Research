# 任务拆分 · S079 打板 P2 仓位闸 + 龙虎榜黑名单

> 对应：`spec.md`（spec，AC1-AC10）+ `plan.md`（技术方案，R1-R10）
> 粒度：原子任务（独立可验，1-2h/条）。每条含：依赖、改动文件、验收方式、映射 AC。
> 规则：每条完成即跑对应单测/验收；龙虎榜取数复用 `seat_engine`/`hot_money_seats`，不新增 akshare；`_market_phase` 扩展保留旧签名向后兼容（R6.5）；`cap_by_market_phase` 叠加代数严格 `min(weather_cap, market_phase_cap, max_total_position)`，绿档不放宽（R7.2）；输出层挂轻量风险提醒「历史统计特征，市场有风险」（CLAUDE.md §1.1）。

---

## 阶段 A · 龙虎榜三分级风控（AC3/AC4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | 新建 `backend/dragon_tiger_seat_filter.py` 骨架 + `DragonTigerSeatFilter` 类 + `__init__(seat_engine)` 复用既有 seat_engine 实例 | — | `backend/dragon_tiger_seat_filter.py` | `python -c "from dragon_tiger_seat_filter import DragonTigerSeatFilter"` 不报错 |
| A2 | R1 龙虎榜取数：封装 `fetch_consensus(stock_code, trade_date)` 调 `seat_engine.compute_consensus_signal(trade_date, stock_code)` 取 buy_seats + total_buy_amount，取数失败返回 None | A1 | `backend/dragon_tiger_seat_filter.py` | mock seat_engine 返回固定 buy_seats，`fetch_consensus` 返回结构含 buy_seats/total_buy_amount |
| A3 | 新建 `config/seat_blacklist.yaml`：黑名单席位名单 + 散户大本营名单 + 阈值（blacklist_ratio=0.15 / buy_one_ratio=0.55 / buy_one_ratio_daily=0.10 / retail_seat_count=3），头部标注"探索性（外部 PRD 拍定，零数据支撑，进 config 可配，AC8 回测调参）" | — | `config/seat_blacklist.yaml` | `yaml.safe_load` 解析成功，字段齐全 |
| A4 | R2.2 子串模糊匹配工具 `match_seat_substring(blacklist_name, seat_name)`：双向子串包含 `bl in seat or seat in bl`，应对"中国国际金融上海分公司" vs "中金公司上海分公司"写法差异 | A1 | `backend/dragon_tiger_seat_filter.py` | 双向匹配用例（含写法变体）通过 |
| A5 | R2 黑名单硬剔除：`filter_by_blacklist(suggestions, blacklist_config, trade_date)` 对每个 suggestion 调 `fetch_consensus` 取 buy_seats，子串匹配黑名单席位，算 `matched_buy_amt/total_buy_amount`，占比>15% → 从 suggestions 移除 + 标 `risk_flags[code]=["【拒绝介入】黑名单占比 X%"]` | A2,A3,A4 | `backend/dragon_tiger_seat_filter.py` | mock 黑名单占比 18% → 标的剔除 + risk_flags 非空；占比 10% → 保留 |
| A6 | R3 独食独大：扩展 `seat_engine/service.py:231 compute_consensus_signal` 输出 `details` 加 `buy_one_ratio` 字段（= buy_seats[0].buy_amt / total_buy_amount） | A2 | `backend/seat_engine/service.py` | compute_consensus_signal 返回 details 含 buy_one_ratio |
| A7 | R3 独食独大软标记：`check_monopoly(seat_details, daily_amount)` 判定 buy_one_ratio≥0.55（前五占比）或 buy_seats[0].buy_amt/daily_amount≥0.10（全天占比）→ 标 `["独食独大"]` | A6 | `backend/dragon_tiger_seat_filter.py` | mock buy_one_ratio=0.6 → 标"独食独大"；buy_one_ratio=0.3 → 空 |
| A8 | R3 仓位砍半集成：在 DragonTigerSeatFilter 输出中，含"独食独大"标记的标的 `suggested_pct *= 0.5`（复用 `hot_money_seats.SeatRiskFactor` 的 score_modifier 先例，day_trip_ratio>0.5→×0.7） | A7 | `backend/dragon_tiger_seat_filter.py` | mock 独食独大标的 suggested_pct 砍半 |
| A9 | R4 散户霸榜：`check_retail_dominance(buy_seats, retail_seats_config)` 对 buy_seats 前五做子串匹配零售席位（拉萨团结路/东环路等），命中≥3 个 → 标 `["散户霸榜"]` | A4 | `backend/dragon_tiger_seat_filter.py` | mock 4 个拉萨席位 → 标"散户霸榜"；2 个 → 空 |
| A10 | R4 战法匹配置信度降权：含"散户霸榜"标记的标的，战法匹配置信度降权（复用 `hot_money_seats.day_trip_ratio` 基础扩展，降权系数进 config 可配） | A9 | `backend/dragon_tiger_seat_filter.py` | mock 散户霸榜标的置信度降权生效 |
| A11 | R5 数据缺失处置：`fetch_consensus` 返回 None / signal="未取得" 时，标 `data_missing_flags[code]="席位风控数据未取得，硬剔除不可执行"`，**不剔除（不默认拒绝）也不硬剔除（不默认放行）**，保留标的由用户决策 | A5 | `backend/dragon_tiger_seat_filter.py` | mock 龙虎榜未取得 → 标的保留 + data_missing_flags 非空 + risk_flags 无硬剔除 |
| A12 | DragonTigerSeatFilter 入口 `filter(suggestions, blacklist_config, trade_date) -> (filtered, risk_flags, data_missing_flags)` 串 R2/R3/R4/R5 | A5,A8,A10,A11 | `backend/dragon_tiger_seat_filter.py` | 离线 mock 端到端：黑名单剔除 + 独食独大砍半 + 散户霸榜降权 + 数据缺失保留 |
| A13 | 龙虎榜三分级单测：mock 黑名单/独食独大/散户霸榜/数据缺失四场景 | A12 | `backend/tests/test_dragon_tiger_seat_filter.py` | `pytest -m "not live"` 过 |

**阶段 A 映射 AC**：AC3（三分级风控正确执行）、AC4（数据缺失处置）

---

## 阶段 B · 仓位闸扩展（AC1/AC2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | R6.5 向后兼容：`first_board_filter._market_phase` 改签名加默认参数 `def _market_phase(zt_count, big_loss=None, floor=None, ladder_success=None, ladder_height=None)`，旧调用 `_market_phase(40)` 走原四档判定（big_loss 等 None 跳过红期硬熔断），`score_candidate`（line 1341）现有调用不破坏 | — | `backend/strategies/first_board_filter.py` | `_market_phase(zt_count=40)` 返回"普通"不报错；score_candidate 调用不破坏 |
| B2 | R6.2 红期硬熔断覆盖：在 `_market_phase` 优先判定 `if big_loss is not None and big_loss >= 8: return "红期"` + `if floor is not None and floor >= 20: return "红期"`，覆盖四档判定 | B1 | `backend/strategies/first_board_filter.py` | mock big_loss=8 → 返回"红期"；big_loss=3 → 走四档 |
| B3 | R6.1 四档判定保留：zt_count <30→冰点 / <60→普通 / <100→活跃 / ≥100→亢奋（原逻辑，红期硬熔断未触发时走此） | B2 | `backend/strategies/first_board_filter.py` | mock zt_count=20/40/80/120 → 冰点/普通/活跃/亢奋 |
| B4 | R6.3 三状态映射常量 `PHASE_TO_CAP_TIER`：活跃/亢奋→green、普通→yellow、冰点/红期→red | B3 | `backend/strategies/first_board_filter.py` | 常量 5 个 phase 映射齐全 |
| B5 | R6 扩展单测：mock zt_count=40/big_loss=3/8/12 等场景验证四档 + 红期硬熔断 + 向后兼容 | B4 | `backend/tests/test_first_board_filter_phase.py` | `pytest -m "not live"` 过 |
| B6 | R7 `cap_by_market_phase(positions, phase, weather_state=None)` 新函数骨架（不修改既有 advise/advise_batch 签名） | — | `backend/strategies/position_advisor.py` | `python -c "from position_advisor import cap_by_market_phase"` 不报错 |
| B7 | R7.1 三状态 cap 映射 `MARKET_PHASE_CAP`：green=1.0（不放宽，只收紧）/ yellow=0.5 / red=0.2，未知 phase 降级 yellow | B6 | `backend/strategies/position_advisor.py` | 常量 3 档 + 降级逻辑 |
| B8 | R7.1 叠加代数：对每个 position.suggested_pct 做 `final_pct = min(weather_cap_result, market_phase_cap_result, max_total_position)`，其中 `market_phase_cap_result = min(suggested_pct, max_single_position * market_phase_cap)`，`max_total_position=0.8` 既有硬上限 | B7 | `backend/strategies/position_advisor.py` | mock 三档 phase，验证 final_pct = min() 取最严 |
| B9 | R7.2 绿档不放宽：green 档 `market_phase_cap=1.0`，`max_single_position * 1.0 = max_single_position`，`min(suggested_pct, max_single_position)` 不超过既有单票上限，只收紧不放宽 | B8 | `backend/strategies/position_advisor.py` | mock green 档 + suggested_pct 超上限 → final_pct 不超过上限 |
| B10 | R7.3 互斥说明：同一情绪现象（大面股爆炸≈暴风雨）同时触发 weather 熔断和 market_phase 熔断时取 `min()` 不冲突（取最严），函数 docstring 显式声明 | B9 | `backend/strategies/position_advisor.py` | mock weather_cap=0.5 + market_phase_cap=0.2 → final=0.2 |
| B11 | R7 标记仓位闸信息：position 输出加 `market_phase` + `market_phase_cap` 字段（供前端展示） | B10 | `backend/strategies/position_advisor.py` | mock 输出含 market_phase/market_phase_cap |
| B12 | cap_by_market_phase 单测：mock PositionAdvisor 输出 + 三状态映射 + weather_cap 叠加 + 绿档不放宽 + 互斥 | B11 | `backend/tests/test_position_advisor_cap.py` | `pytest -m "not live"` 过 |
| B13 | R8 STI 时序分离文档声明：`_market_phase` docstring + `cap_by_market_phase` docstring 显式声明"STI 是 T-1 盘后总结，_market_phase 是 T+1 盘前仓位闸因子，时序用途不同，不引入新概念，不替代 STI" | B5,B11 | `backend/strategies/first_board_filter.py`、`backend/strategies/position_advisor.py` | docstring 含时序分离声明 |

**阶段 B 映射 AC**：AC1（_market_phase 4 因子 + 红期硬熔断 + 向后兼容）、AC2（cap_by_market_phase 叠加代数 + 绿档不放宽）

---

## 阶段 C · 信号输出（AC5/AC9）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | R9 链路集成：`pre_market_workflow.py` 在既有 `advise_batch`（line 150）后串 Layer 1 `DragonTigerSeatFilter.filter(...)` | A12 | `backend/pre_market_workflow.py` | 离线 mock 端到端：advise_batch 输出 → DragonTigerSeatFilter 输出 filtered + risk_flags + data_missing_flags |
| C2 | R9 链路集成：Layer 2 串 `cap_by_market_phase(positions, phase)`，phase 从 `_market_phase(zt_count, big_loss, floor, ladder_success, ladder_height)` 取 | B11,C1 | `backend/pre_market_workflow.py` | 离线 mock 端到端：DragonTigerSeatFilter 输出 → cap_by_market_phase 输出含仓位上限 |
| C3 | R6.4 因子来源：从 T-1 盘后市场数据计算 big_loss/floor/ladder_success/ladder_height（复用 `market._emotion` 既有端点，实现阶段核实具体字段，标注 T2 待定） | C2 | `backend/pre_market_workflow.py` | mock T-1 市场数据 → 4 因子可计算（字段名待定项 T2 实现阶段核实） |
| C4 | R9.1 仓位参数输出：单笔委托金额 = 总仓位上限 × 个股仓位分配 ÷ 标的数，黄色期砍半（market_phase_cap=0.5 已在 cap_by_market_phase 处理） | C2 | `backend/pre_market_workflow.py` | 输出含单笔委托金额 + 总仓位上限 |
| C5 | R9.2 触发价/竞价达标额**不输出**：属 S081 战法匹配 spec 范围，本 spec 只输出仓位参数 + 龙虎榜风控标记 | C4 | `backend/pre_market_workflow.py` | 代码审查：输出无触发价/竞价达标额字段 |
| C6 | AC7 合规：输出层挂轻量风险提醒「历史统计特征，市场有风险」（CLAUDE.md §1.1 弱合规） | C4 | `backend/pre_market_workflow.py` | 代码审查：输出含风险提醒字符串 |
| C7 | R9 输出结构：`output = {position_suggestions, market_phase, market_phase_cap, seat_risk_flags, data_missing_flags}` | C2,C4,C6 | `backend/pre_market_workflow.py` | output 字段齐全 |
| C8 | R9 单测：mock 全链路（match → advise_batch → DragonTigerSeatFilter → cap_by_market_phase），验证输出结构 + 仓位参数 + 风控标记 | C7 | `backend/tests/test_pre_market_workflow_p2.py` | `pytest -m "not live"` 过 |

**阶段 C 映射 AC**：AC5（输出仓位参数 + 风控标记 + checklist，不接券商不下单）、AC9（S002 AC10 在 P2 放宽到弱合规口径）

---

## 阶段 D · checklist 推送（AC5/AC9）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | R10 后端响应扩展：`routers/workflow.py` `/api/workflow/pre-market` 响应加 `market_phase` + `market_phase_cap` + `position_cap_tier` + `seat_risk_flags` + `data_missing_flags` + `execution_checklist` 字段，**不新增 /api/workflow/p2/* 端点** | C7 | `backend/routers/workflow.py` | curl /api/workflow/pre-market 返回含新增字段 |
| D2 | R10 execution_checklist 内容：["仓位参数参考值，非执行指令", "黄色期仓位砍半...", "【拒绝介入】标的不可开仓", "数据缺失标的需人工核实龙虎榜后决策", "历史统计特征，市场有风险"] | D1 | `backend/routers/workflow.py` | checklist 含 5 项 + 标注"参考值，非执行指令" |
| D3 | R10 前端 api.ts：pre-market 响应类型加 `market_phase_cap` + `risk_flags` + `data_missing_flags` + `execution_checklist` 字段 | D1 | `frontend/src/lib/api.ts` | TypeScript 类型编译通过 |
| D4 | R10 前端 Workflow.tsx 仓位闸面板：显示 market_phase + market_phase_cap + position_cap_tier（绿/黄/红三色标识） | D3 | `frontend/src/pages/Workflow.tsx` | 页面渲染三色仓位闸标识 |
| D5 | R10 前端龙虎榜风控标记：每个标的旁显示 seat_risk_flags（【拒绝介入】/独食独大/散户霸榜） | D3 | `frontend/src/pages/Workflow.tsx` | mock 标的含"独食独大" → 渲染标记 |
| D6 | R10 前端数据缺失警示：显著警示标记"席位风控数据未取得，硬剔除不可执行" | D3 | `frontend/src/pages/Workflow.tsx` | mock data_missing_flags → 显著警示渲染 |
| D7 | R10 前端人工执行 checklist：底部展示 execution_checklist，标注"参考值，非执行指令" | D3 | `frontend/src/pages/Workflow.tsx` | checklist 渲染 + 标注非执行指令 |
| D8 | R10 飞书推送：复用既有推送通道（`notification/`），推送格式含仓位参数 + 风控标记 + checklist，标注"仓位参数参考值，非执行指令" | D1 | `backend/notification/*`（复用） | mock 推送 payload 含 checklist + 非执行指令标注 |
| D9 | D 阶段单测 + 前端冒烟 | D2,D8 | `backend/tests/test_workflow_p2_api.py` | `pytest -m "not live"` 过；`npm run dev` 打开 Workflow 页各交互 |

**阶段 D 映射 AC**：AC5（checklist 推送 + 不接券商不下单）、AC9（P2 放宽到弱合规口径）

---

## 阶段 E · AC6 处置（AC6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | AC6 核实：`hot_money_seats.py:75` 注释"绕过 em_get 熔断（datacenter API 可直接 urllib 调用）" —— 核实 `datacenter-web.eastmoney.com` 域名限流策略是否与 `push2ex.eastmoney.com`（em_get 防护对象）相同 | — | `backend/strategies/hot_money_seats.py` | 核实记录写入代码注释：datacenter [需要/不需要] em_get 防护 + 理由 |
| E2 | AC6 处置分支 A（datacenter 不需 em_get 防护）：在 line 75 注释显式声明理由（datacenter 限流策略与 push2ex 不同，直接 urllib 调用安全），保留 urllib 直接调用 | E1 | `backend/strategies/hot_money_seats.py` | 注释含理由声明 |
| E3 | AC6 处置分支 B（datacenter 需 em_get 防护）：套上 `em_get` 限流 + `circuit_breaker.get_breaker("eastmoney")` 熔断器 + 重试 | E1 | `backend/strategies/hot_money_seats.py` | datacenter 调用经 em_get + 熔断器 |
| E4 | AC6 联网测试：`pytest -m live` 跑 datacenter 通道限流验证 | E2 或 E3 | `backend/tests/test_hot_money_seats_live.py` | `pytest -m live` 过（datacenter 不被封） |

**阶段 E 映射 AC**：AC6（hot_money_seats "绕过 em_get" 处置）

> E1 是核实任务，根据结果走 E2 或 E3 分支（二选一），不两者都做。

---

## 阶段 F · 验收（全 AC）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| F1 | 逐条核对 AC1-AC10 | A13,B12,B13,C8,D9,E4 | — | AC checklist 全绿 |
| F2 | AC8 阈值复算：跑 `financial_rigor.py --thresholds prd_p2 --window 60d` 验证阈值判定逻辑 + 触发频率/空池率统计，标注探索性，约定命中率<5% 或空池率>30% 触发调参 | A3 | — | 复算结果记录 + 探索性标注 + 调参门限约定 |
| F3 | AC7 合规自查：所有研判/买卖时机/仓位参数输出挂轻量风险提醒「历史统计特征，市场有风险」（CLAUDE.md §1.1） | C6,D2,D8 | — | 自查表全绿（输出层均挂风险提醒） |
| F4 | AC10 不涉及确认：确认无战法匹配扩展（拆 S081）+ 无止损/止盈参考价位输出（属 S081） | 全部 | — | 代码审查：无战法匹配扩展 + 无参考价位 |
| F5 | `pytest -m "not live"` 全过 | A13,B12,C8,D9 | — | 全绿 |
| F6 | 手动验收：取近 5 个交易日真实数据跑全链路，输出仓位参数 + 风控标记 + checklist + 飞书推送格式确认 | F1-F5 | — | 5 日全链路输出 + 飞书格式确认 |
| F7 | 写验收报告，更新 spec 状态"已实现(日期)" | F1-F6 | `specs/S079-打板P2战法与仓位闸/验收报告.md` | 报告归档 |

**阶段 F 映射 AC**：全 AC（AC1-AC10）

---

## 依赖图（关键路径）

```
阶段 A（龙虎榜三分级）：
A1→A2→A5→A11→A12→A13
     ↓     ↑
A3→A4   A6→A7→A8
            ↑
           A9→A10

阶段 B（仓位闸扩展，可与 A 部分并行）：
B1→B2→B3→B4→B5
            ↓
B6→B7→B8→B9→B10→B11→B12
                        ↓
                       B13（依赖 B5+B11）

阶段 C（信号输出，依赖 A+B）：
A12 + B11 → C1→C2→C3→C4→C5→C6→C7→C8

阶段 D（checklist 推送，依赖 C）：
C7 → D1→D2→D3→D4→D5→D6→D7→D8→D9

阶段 E（AC6 处置，独立可并行）：
E1 → E2 或 E3 → E4

阶段 F（验收，依赖全部）：
A13+B12+B13+C8+D9+E4 → F1→F2→F3→F4→F5→F6→F7
```

- A/B 可并行起步（A 依赖 seat_engine，B 独立改 first_board_filter/position_advisor）
- C 依赖 A12（DragonTigerSeatFilter 入口）+ B11（cap_by_market_phase 函数）
- D 依赖 C7（输出结构）
- E 独立，可与 A/B/C/D 并行
- F 依赖全部
- **关键路径**：A1→A2→A5→A12→C1→C2→C7→D1→D9→F1

---

## 执行规则

1. **一次一任务**：按 ID 顺序，完成一条跑其验收方式再开下一条。
2. **合规前置**：每条任务实现前对照 spec §2.3（S002 AC10 显式豁免）+ §7 合规自查栏，确认符合 CLAUDE.md §1.1 弱合规口径（2026-07-30）——P2 输出层允许输出仓位参数/红期强制熔断/【拒绝介入】等量化方向参数，挂轻量风险提醒「历史统计特征，市场有风险」。
3. **_market_phase 向后兼容**：B1-B3 扩展签名用默认参数，旧调用 `_market_phase(zt_count)` 不破坏 score_candidate（line 1341）。
4. **cap_by_market_phase 叠加代数**：B8 严格 `final_cap = min(weather_cap, market_phase_cap, max_total_position)`，B9 绿档 cap=1.0 只收紧不放宽，B10 互斥取 min 不冲突。
5. **龙虎榜取数复用**：A2 调 `seat_engine.compute_consensus_signal`，不新增 akshare 通道；A6 扩展 seat_engine 输出 buy_one_ratio 字段。
6. **数据缺失不默认放行/拒绝**：A11 龙虎榜"未取得"时硬剔除不可执行 + 警示 + 用户决策。
7. **PRD 阈值探索性**：A3 config 标注"探索性"（外部 PRD 拍定，零数据支撑），F2 跑 `financial_rigor.py --thresholds prd_p2 --window 60d` 复算 + 调参门限。
8. **不接券商不下单**：C5/D8 确认无券商 API 调用，参数标注"参考值，非执行指令"。
9. **commit 引用**：commit message 带 S079 + 任务 ID（如 `S079-A2 龙虎榜取数`）。
