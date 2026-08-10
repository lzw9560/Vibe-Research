# Spec: S049 — 盘前简报漏斗重构与诊断修正（合并 S049a-d，唯一权威版本）

> 状态：子项 A 已实现（89768c2）；B/C/D 实施中
> 作者：Claude（Codex 会话）  日期：2026-08-11
> 级别：**medium**（跨前后端 >50 行；不接新外部源/无新 AI 工具/无财务验算，不触发自动 large）
> 流程门：develop 直提 + 勤 commit；验收=离线全测 + tsc/vitest + dev server 冒烟（用户 2026-08-11 批准 large→medium 降级，理由见 §1.3）
> 来源合并：`specs/S049a-d` 四草案（已删）+ `.scratch/funnel-list-rebuild/` 工单（已毕业）+ 本会话 grill Q1–Q9 锁定
> 关联：S048（盘前简报页/诊断链路）、S031 R22（战法胜率对比）、S033（状态卡）、S008（data/sources）、S023/S024

## 1. 背景与目标

### 1.1 用户反馈（8 点）

1. 漏斗选股怎么 R123（澄清，无改动：R1 宽源→R2 收敛→R3 定稿，逐层过滤副作用=同标的多层出现）
2. 卡片重复，能否合并显示
3. 表格中间大量空白
4. 战法胜率对比，战法可以展开吗
5. 附带符合战法可建仓的标的（用户明确：**建仓**，非减仓；当日命中+回溯明细都要）
6. 展开个股详情确保数据准确；为什么没有情绪梯队参数
7. 无资金流
8. 工作流状态只有选中，没有取消

### 1.2 子项划分

| 子项 | 内容 | 状态 |
|---|---|---|
| A | 资金流取数修复（push2his→push2delay 降级 + 单行降级态诚实 missing） | ✅ 已实现（89768c2） |
| B | 情绪梯队语义修正（个股删市场级三率）+ `_fetch_market_emotion` 重写（STI+三率+ladder） | 实施中 |
| C | 个股诊断时点修正（as_of=数据源最早日期）+ date 透传 + 快照诊断卡优先 | 实施中 |
| D | 漏斗矩阵全参数 + 战法展开建仓 + 状态取消三件套 + 采集去重 | 实施中 |

### 1.3 流程门降级说明（large→medium）

`.scratch` 工单 issue01 原标 large（跨前后端+数据输出合规重审）。降级理由：
- scope 收缩后**不碰新外部源**（push2delay 是东财既有官方端点同 path 同参数仅 host 换；backtest 走 DB+mootdx 既有链路）、无新 AI 工具、无财务验算——不触发 AGENTS.md 自动 large 判据；
- grill 已两轮（vibe-feedback session + 本会话 Q1–Q9 逐题锁定），review 门已实质满足；
- 用户 2026-08-11 明确批准降级。

## 2. 决策记录（三方产物冲突裁决，2026-08-11）

| # | 冲突 | 裁决 |
|---|---|---|
| D1 | 旧工单"减仓标注" vs 用户纠正 | **建仓**；当日命中+回溯明细都要（懒加载） |
| D2 | Q6"三率作为个股列" vs 语义错位 | 个股**删** seal_rate/bomb_rate/advance_rate（市场级聚合）；市场级三率+ladder 移简报市场情绪区 |
| D3 | Q3v"列表层多列全参数" vs C2 矩阵 | **用户终裁（2026-08-11）：全部参数**——funnel.py 扩 passed dict + 矩阵行带统一参数列（见 R-D1/R-D2） |
| D4 | Q7"资金流作为列" vs S049a 数据修复 | 两者都做：S049a 修数据源（已完成）+ 矩阵参数列展示 |
| D5 | issue02"只做 chips" vs C3 | 三解读全做：状态机 watching→candidate + candidate→filtered"取消选中" + 矩阵状态 chips |
| D6 | issue01 large vs 直提 develop | medium 直提（§1.3，用户批准） |
| D7 | S049b 假设 `_fetch_market_emotion` 活着 | 实测**死的**（`market.get_overview(date)` 抛 TypeError→恒 `{}`）→ 重写（R-B4） |
| D8 | 采集去重/快照诊断卡无归属 | 去重+live funnel_layers 归 D；快照诊断卡+date 透传归 C |
| D9 | 回溯明细数据边界 | 只跑 DB 已有 gene_scores 日期（R21 防封），UI 如实标"样本 N 天"，不臆造（用户批准） |

## 3. 需求清单

### 子项 A · 资金流取数修复（✅ 已实现）

- [x] R-A1 `stock_fund_flow_120d` host 列表 `[push2his, push2delay]` 遍历降级，空 klines 视同失败
- [x] R-A2 降级走 `em_get`（限流/熔断底线不变），返回 shape 不变
- [x] R-A3 两 host 都失败返 `[]`（现状行为）
- [x] R-A4 三分支单测（7 passed）
- [x] R-A5 `len(flows) < 2`（单行降级态）→ `main_net_5d=None` + missing；≥2 行保留"flows[-5:] 按可用天数求和"契约
- [x] R-A6 联网冒烟：600519 返 1 行（date=2026-08-10, main_net=664611600）

### 子项 B · 情绪梯队语义修正 + market_emotion 重写

- [ ] R-B1 `IndicatorSet` 删 `seal_rate`/`bomb_rate`/`advance_rate`（市场级错位，`build_indicator_set` 本就从不赋值）
- [ ] R-B2 保留 `consec_boards`（个股自身连板数，赋值链路不变）
- [ ] R-B3 `board_ladder.py` fetcher 删三率返回键，保留 `lianban_stocks`
- [ ] R-B4 `_fetch_market_emotion`（routers/workflow.py:162）**重写**：STI score+phase（`limitup_sti.service.get_sti_engine().precompute_daily(date)`，phase 中文直出 高潮/启动/分歧/冰点/退潮）+ `market._emotion(date)` 三率（seal_rate/break_rate/promotion_rate）+ ladder + 涨跌停家数；失败降级返空值不崩
- [ ] R-B5 前端市场情绪区重写：STI 分数+阶段 + 三率 chips + ladder 分布 + 涨跌停家数；删死 phaseLabel 映射；缺失显"--"
- [ ] R-B6 `CandidateDetail` 情绪梯队块删三字段，只留 `consec_boards`
- [ ] R-B7 测试：board_ladder 返 dict 无三键；`_fetch_market_emotion` 返 STI+三率+ladder（mock）；前端渲染

### 子项 C · 个股诊断时点 + 快照诊断卡

- [ ] R-C1 `diagnose()` 收集各源最新行日期取**最早**为 `as_of`（数据下限）；全无日期 fallback `now()`
- [ ] R-C2 源 fetcher 暴露 `_as_of` 内部键（YYYY-MM-DD，不进 IndicatorSet）
- [ ] R-C3 前端 diagnosis 调用透传 `date`（CandidateDetail 用 selectedDate，现状不带）
- [ ] R-C4 快照存 `final_candidates` 诊断卡；抽屉查看快照日期时**快照卡优先**，无快照卡才 live diagnose
- [ ] R-C5 测试：多源有 date→最早；全无→≈now；快照优先逻辑

### 子项 D · 漏斗矩阵全参数 + 战法展开建仓 + 状态取消 + 采集去重

- [ ] R-D1 **后端 `funnel.py` 扩各层 passed dict 全参数**（用户终裁"全部参数"）：R1 + `consec_boards`；R2 + 量价（turnover_pct/vol_ratio/amount_yi/amplitude_pct）+ 资金流（main_net_inflow/main_net_5d/northbound）；R3 + 催化（matched_triggers/摘要）。未采集字段 None + missing dict（AC6）
- [ ] R-D2 新 `FunnelMatrix` 组件：行=三层 passed union 去重；列=R1/R2/R3 状态格（✓得分/✗/—）+ **统一参数列**（连板/量价/资金流/催化/打分）；参数值取该行最深一层 passed entry，缺显"—"；排序 R3 通过优先→R2→R1 得分降序；默认 15 行+展开全部；`overflow-x-auto`；点行→抽屉
- [ ] R-D3 因子段跳过 `factor_id === 'candidate_funnel'` 卡（消重复）
- [ ] R-D4 live done 响应带 `funnel_layers`（与快照路径对齐）；前端读 `briefing.funnel_layers`，不发额外 GET
- [ ] R-D5 `run_funnel` (date,config) 缓存：`_build_funnel_layers`/`_collect` 命中已跑因子结果，消除重复外部请求；rerun 不受影响
- [ ] R-D6 战法行展开（WinRateComparePanel）：**当日命中**=l2Passed 按 best_strategy 分组，限未持仓态（candidate/watching）=建仓语义；点标的→抽屉；**回溯明细懒加载**新端点 `GET /api/strategy/backtest/trades?strategy_code=&lookback_days=60`，`strategy_backtest.py` trades 补 `date`/`code`/`name`（GeneScore 已有）；如实标样本天数（D9）
- [ ] R-D7 状态取消三件套：①状态机 `WATCHING` transitions 加 `CANDIDATE`（"取消观察"）；②`candidate→filtered` 按钮文案"取消选中"；③FunnelMatrix 状态 chips 筛选（toggle 取消，复用 useWorkflowStates）
- [ ] R-D8 `WorkflowStateCard`：watching 态"取消观察"按钮 + candidate 态"✕ 取消选中"按钮（danger variant）
- [ ] R-D9 `FunnelLayerCard` 紧凑化：紧凑网格、max-w-2xl、filtered 原因截断+title（因子层 LS 卡仍用它）
- [ ] R-D10 测试：矩阵三格语义/排序/点行；全参数列缺显"—"；战法展开+懒加载；状态按钮 mutate；chips toggle

## 4. 受影响文件（合并）

| 文件 | 子项 | 改动 |
|---|---|---|
| `backend/data/sources/eastmoney.py` | A ✅ | host 遍历降级 + `_parse_klines` |
| `backend/candidate_funnel/sources/fund_flow.py` | A ✅ C | 单行降级 missing；+ `_as_of` 内部键 |
| `backend/tests/test_s008_sources_eastmoney.py` | A ✅ | 三分支降级测试 |
| `backend/candidate_funnel/models.py` | B | IndicatorSet 删三字段 |
| `backend/candidate_funnel/sources/board_ladder.py` | B | 删三率键 |
| `backend/routers/workflow.py` | B C D | `_fetch_market_emotion` 重写；live done 带 funnel_layers；run_funnel 缓存；快照存诊断卡 |
| `backend/candidate_funnel/funnel.py` | C D | diagnose as_of 最早日期；各层 passed dict 扩全参数 |
| `backend/workflow_state_machine.py` | D | WATCHING transitions 加 CANDIDATE |
| `backend/strategies/strategy_backtest.py` | D | trades 补 date/code/name |
| `backend/routers/strategy.py` | D | 新端点 backtest/trades 懒加载 |
| `frontend/src/lib/api/types.ts` | B C D | market_emotion 新 shape；FunnelLayer passed 参数；trades 类型 |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | B D | 市场情绪区重写；因子段跳 candidate_funnel；读 briefing.funnel_layers；FunnelMatrix 替换三层卡 |
| `frontend/src/components/candidate/FunnelMatrix.tsx`（新） | D | 三列矩阵+全参数列+状态 chips |
| `frontend/src/components/ui/WinRateComparePanel.tsx` | D | 战法行展开+懒加载 |
| `frontend/src/pages/workflow/CandidateDetail.tsx` | B C | 情绪梯队只留 consec_boards；diagnosis 透传 date；快照卡优先 |
| `frontend/src/components/workflow/WorkflowStateCard.tsx` | D | 取消观察/取消选中按钮 |
| `frontend/src/components/candidate/FunnelLayerCard.tsx` | D | 紧凑化 |

## 5. 设计要点

### 5.1 子项 B：为什么删个股三率

seal_rate/bomb_rate/advance_rate 来自 `market._emotion`，是全市场聚合（同日所有股票同值），塞个股 IndicatorSet 无信息量且误导。个股只留 `consec_boards`。市场级数据一处展示（简报市场情绪区），避免重复。`build_indicator_set` 本就从不赋值三字段（前端恒显"未取得"），删字段零行为风险。

### 5.2 子项 B：`_fetch_market_emotion` 重写 shape

```python
{
  "sti_score": float|None, "sti_phase": "高潮|启动|分歧|冰点|退潮"|None,
  "seal_rate": float|None, "break_rate": float|None, "promotion_rate": float|None,
  "ladder": [{"boards": 2, "count": 12}, ...],
  "zt_count": int|None, "dt_count": int|None,
}
```

STI 经 `get_sti_engine().precompute_daily(date)`；三率/ladder/涨跌停经 `market._emotion(date)`（实测可用，偶发空=em_get 首调限流，内部重试一次）。注意 `market.get_overview()` **不接收 date**（旧代码 TypeError 根因）。

### 5.3 子项 C：as_of 最早日期策略

多源数据各自最新行日期不同，取最早="该卡所有数据的共同有效下限"，比最晚保守（最晚掩盖某源陈旧）。字符串比较（YYYY-MM-DD 字典序=日历序），fetcher 统一返 YYYY-MM-DD。missing 源不贡献日期。

### 5.4 子项 D：FunnelMatrix 全参数列（用户终裁）

行=三层 passed code union；每行参数值取**最深一层** passed entry（R3>R2>R1，层越深采集越全）；R1-only 行只有 gene_score+consec_boards，其余列"—"。列定义固定：连板 | 换手% | 量比 | 成交额(亿) | 振幅% | 主力净流(万) | 5日累计(万) | 北向 | 催化 | 打分。`overflow-x-auto` 处理横向溢出。

### 5.5 子项 D：状态机扩展

`workflow_state_machine.py` `_ALLOWED_TRANSITIONS[WATCHING]` 现为 `[MONITORING, FILTERED]`，加 `CANDIDATE`（取消观察=回候选池重审）。`candidate→filtered` 已合法（"取消选中"）；`filtered→candidate` 可重入，误触可恢复。settled 不加速度取消（已结算记账，防胜率污染）。

### 5.6 子项 D：采集去重

`run_funnel` 无缓存，live 流程 `_collect`（因子）与 `_build_funnel_layers`（候选池漏斗）各跑一遍 → 外部请求翻倍。加 (date,config) 键缓存因子结果，`_build_funnel_layers` 命中即复用；rerun 走清缓存路径不受影响。

### 5.7 不选的方案

- 个股级真算"该股封板率"：东财无封板尝试数端点，数据源无，不臆造
- 漏斗三层独立卡只改并排：不满足消重复
- 战法展开列持仓标的（减仓）：用户明确建仓
- 状态取消用删除记录：破坏状态机连续性
- as_of 取最晚：掩盖陈旧源
- backtest trades 补全历史：触发 em_get 拉 K 线，违 R21 防封

## 6. 验收标准（合并）

- [x] AC-A1 eastmoney 三分支降级测试过（7 passed）
- [x] AC-A2 联网冒烟 600519 返 1 行（push2delay 生效）
- [x] AC-A3 candidate_funnel+eastmoney 158 passed
- [ ] AC-B1 pytest 离线全过（board_ladder 无三键；_fetch_market_emotion 返 STI+三率+ladder）
- [ ] AC-B2 vitest+tsc 全过（市场情绪区渲染 ladder+三率+STI；CandidateDetail 只 consec_boards）
- [ ] AC-B3 冒烟：diagnose indicators 无三键；简报市场情绪区有 ladder（端点通时）；断时显"--"
- [ ] AC-C1 as_of 单测（最早日期/全无→now）；冒烟 diagnose as_of=数据源日期非当前时刻
- [ ] AC-C2 快照日期抽屉显快照诊断卡
- [ ] AC-D1 FunnelMatrix：行=union，三格 ✓/✗/—，全参数列缺显"—"，排序 R3 优先，点行弹抽屉
- [ ] AC-D2 战法行展开当日命中（未持仓）+ 回溯明细懒加载样本天数如实
- [ ] AC-D3 状态按钮：candidate"取消选中"→filtered；watching"取消观察"→candidate；chips toggle 筛矩阵
- [ ] AC-D4 live done 带 funnel_layers；同 (date,config) 二跑不重复外部请求
- [ ] AC-D5 vitest+tsc 全过；dev server(:8900) 冒烟盘前简报 done 态全区块渲染

## 7. 合规与工程底线自查（全子项一次）

- [ ] 研判/买卖时机：战法展开列"未持仓·命中战法"是客观状态呈现，UI 措辞不用"建议买入/可建仓"方向词；状态取消是用户操作非系统建议
- [ ] 不臆造数据：矩阵 ✓/✗/— 与参数列来自 layers.passed 原文；三率/ladder 来自 market._emotion 原文；回溯明细只含 DB 已有日，样本天数如实；缺数据统一"—"+missing（AC6）
- [ ] 判断可复现：as_of 来自数据源原文日期；push2delay 降级路径可追溯
- [ ] 涨停四池/连板股榜：lianban_stocks 保留，公开榜单客观事实
- [ ] 用户私有数据：不涉及
- [ ] em_get 防封：push2delay 复用 em_get；backtest 只跑 DB 已有日不触发 em_get；run_funnel 缓存减请求

## 8. 测试计划

**后端**（每子项 TDD 红→绿）：
1. B：board_ladder 无三键；_fetch_market_emotion mock STI+_emotion 返全 shape；IndicatorSet 无三字段
2. C：diagnose as_of 最早/fallback；快照诊断卡存取
3. D：状态机 WATCHING→CANDIDATE 合法；trades 含 date/code/name；/api/strategy/backtest/trades 端点；funnel.py passed dict 含新参数；run_funnel 缓存命中
4. 回归：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`

**前端**：
5. FunnelMatrix.test：三格语义/union/排序/参数列缺"—"/点行/ chips toggle
6. WinRateComparePanel.test：展开 toggle/未持仓 filter/懒加载 mock
7. WorkflowStateCard.test：两取消按钮显隐+mutate
8. PreMarketBriefing.test：市场情绪区/跳 candidate_funnel 卡
9. 回归：`cd frontend && npx tsc --noEmit && npx vitest run`

**冒烟**：dev server(:8900) 盘前简报 done 态走查 + diagnose 600519 端到端（并验 AC-B3/AC-C1）

## 9. 风险与回滚

- **删三字段破坏下游**：实测三字段从不赋值，下游拿到的都是 None，删字段零行为变化；grep 全仓确认无遗漏消费方
- **push2delay 只回 1 行**：main_net_5d 降级态 missing，push2his 恢复后自动回归完整窗口
- **market._emotion 偶发空**（em_get 首调限流）：内部重试一次，仍空显"--"
- **矩阵行数多**：union 可能 40+ 行，默认 15+展开全部
- **全参数列横向宽**：overflow-x-auto；列定义固定防布局漂移
- **状态取消误触**：filtered→candidate/watching→candidate 均可重入恢复
- **run_funnel 缓存脏读**：键含 config 哈希；rerun 显式清缓存
- **回滚**：按子项独立 commit，单子项 `git revert` 不影响其余

## 10. 实施记录

### 子项 A（2026-08-11，commit 89768c2）

- `stock_fund_flow_120d` 改 host 列表遍历 `[push2his, push2delay]`，抽 `_parse_klines(d)`，空 klines 视同失败继续下一 host
- 新发现：push2delay 为延迟镜像，**无论 lmt 多少只回最新 1 行**——故 `fund_flow.py` `len(flows) < 2` 置 `main_net_5d=None` + missing"资金流仅 1 天（降级源），5 日累计暂不可得"；阈值 `<2` 非 `<5`（既有契约允许短窗口求和，仅单行冒充"5 日"才误导）
- 测试：eastmoney 7 passed；candidate_funnel+eastmoney 158 passed
- 冒烟：600519 → 1 行 `{'date': '2026-08-10', 'main_net': 664611600.0, ...}`

### 子项 B/C/D

（实施中，按 §3 需求清单推进，逐项勾选）
