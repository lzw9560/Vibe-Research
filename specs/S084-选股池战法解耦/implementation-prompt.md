你是一个资深的 Python + React/TypeScript 工程师，在 Vibe-Research 项目（A股投研看板）中实现 S084 spec「选股池战法解耦」。

## 仓库
- 工作目录：当前 repo 根目录
- 分支：在 develop 上新建 feature/S084-选股池战法解耦 分支工作
- Python venv：.venv/bin/python（pytest 用 .venv/bin/python -m pytest）

## 必读文件（按顺序读，不要跳过）
1. specs/S084-选股池战法解耦/spec.md —— 需求 + AC + 因子清单
2. specs/S084-选股池战法解耦/plan.md —— 技术方案（§0 复用清单 + §1 目录结构 + §2 实现步骤 + §3 验收对齐）
3. specs/S084-选股池战法解耦/tasks.md —— 30 个原子任务（阶段 A-E）

## 关键代码事实（plan §0 已写，这里强调最重要的）
- DiagnosisCard 在 backend/candidate_funnel/models.py:126，现有字段 code/name/indicators/activity/stabilization/risk_flags/as_of
- IndicatorSet 在 models.py:26，已有 15 字段（含 S083 加的 max_high_pct/shadow_length_pct/ma_5_status/prev_turnover_pct）
- IndicatorSet 已有 limit_up/limit_down（models.py:38-39），R4.1 不要新增同名，只加 6 个新字段（last_close/open/change_amt/pe_ttm/mcap_yi/pb）
- gene.py（candidate_funnel/sources/gene.py:31）当前 genes[code] = {name, gene_score(数字), high_gene, qualify}，要扩展存 gene_obj: GeneScore 完整对象
- activity.py 盘前取 T-1 走 kline 复算路径（_is_historical_date 判定），tencent_quote vals 在历史日路径拿不到 —— pe_ttm/mcap_yi/pb 从 tencent_quote 当日取标"当前值非T-1"
- first_board_filter.fetch_zt_pool(date) 已有涨停池取数路径（走 em_get + 24h 缓存），R2.1 pool_item 复用它不新建
- compute_derived_features(get_snapshots_by_code(code, yesterday_date)) 取 T-1 昨日派生（已落库）
- match_strategies 当前签名 (code, gene, pool_item=None, indicators=None)，S084 加 card=None 参数，card=None 走既有 fallback 不删
- pre_market_workflow.py 保留不改（Q3=C 三入口并存）
- 前端 CandidateFunnelEmbed 是 PreMarketBriefing 局部函数不可复用，选股池 Tab 用 FunnelLayers + SelectionPipeline

## 6 条 grill 决议（必须忠实遵守）
1. Q1=A 砍盘中：选股池只做盘前，所有因子取 T-1 昨日值，不碰 T 日盘中实时
2. Q2=B修正：S070 R7 派生盘前取 T-1 昨日 snapshots（get_snapshots_by_code(code, yesterday_date)）
3. Q3=C：pre_market_workflow 保留不改，选股池Tab+战法Tab是新增独立入口
4. Q4=A：战法卡片指向 /workflow/pre-market?strategy=（已实现不改）
5. Q5=A：选股池Tab复用 FunnelLayers + SelectionPipeline，不新建组件，不用 CandidateFunnelEmbed
6. Q6=B：DiagnosisCard 加 3 子对象（gene_score/pool_item/derived），不全部塞 IndicatorSet

## Oracle 审查修复（必须遵守）
- B2：match_strategies card=None 时保留 fallback 路径不删（pre_market_workflow 不传 card 走 fallback 行为不变）
- B3：AC5a-d 移 backlog，不实现 market_context/seat_detail/派生因子/催化因子（C 段 22 因子不在本 spec）
- B4：R4.1 按历史日路径分字段取数（kline 复算 vs tencent_quote 当日取，不混用）
- H1：选股池 Tab 用 FunnelLayers + SelectionPipeline，不用 CandidateFunnelEmbed

## 实现顺序（按 tasks.md 阶段 A→B→C→D→E）
### 阶段 A（A1-A15）：模型与 source 扩展
- A1-A5：models.py 改（DiagnosisCard 加 3 子对象 + IndicatorSet 加 10 字段）
- A6：gene.py 扩展存完整 GeneScore
- A7：新建 zt_pool_source.py 复用 fetch_zt_pool 取涨停池原始 dict
- A8：新建 derived_source.py 调 compute_derived_features(get_snapshots_by_code(code, yesterday)) 取 T-1
- A9：activity.py 按历史日路径分字段扩展（kline 复算 open/last_close/change_amt + tencent_quote 当日取 pe_ttm/mcap_yi/pb）
- A10：fund_flow.py 扩展取板块资金 3 字段（market._sectors() 取昨日）
- A11：activity.py 算 prev_amount_yi（K线前日 bar.turnover/1e8）
- A12-A13：diagnosis.py 塞入 3 子对象 + 透传新字段
- A14：funnel.py _run_funnel_impl 采集 2 新 source + 塞入 DiagnosisCard
- A15：单测

### 阶段 B（B1-B6）：战法从 DiagnosisCard 读
- B1：match_strategies 加 card=None 参数
- B2：既有 9 战法从 card.gene_score 读（card=None 走原 gene 参数 fallback）
- B3-B4：PRD 2 战法从 card 读（card=None 走既有 S070/kline_rebuild fallback 不删）
- B5：StrategyMatcher.match() 加 card 透传
- B6：单测（card 传/不传命中一致 + PRD 2 战法从 card 读命中）

### 阶段 C（C1-C4）：前端两级 Tab
- C1：candidates.ts DiagnosisCard 类型加 3 子对象
- C2：Workflow.tsx 加选股池/战法 两级 Tab
- C3：选股池 Tab 调 runFunnel + FunnelLayers + SelectionPipeline
- C4：tsc --noEmit

### 阶段 D（D1）：pre_market_workflow 不改 + 既有测试回归

### 阶段 E（E1-E4）：验收
- pytest 全过 + 验收报告

## 回归测试（必须完成，不能跳过）

每个阶段完成后必须跑回归测试，不只是新增测试：

### 阶段 A 完成后回归：
.venv/bin/python -m pytest backend/tests/test_s002*.py backend/tests/test_s004*.py backend/tests/test_s031*.py backend/tests/test_s049*.py backend/tests/test_s057*.py backend/tests/test_candidate_funnel*.py -m "not live" --no-cov -q
- 验证：candidate_funnel 既有测试不破坏（DiagnosisCard/IndicatorSet 加字段不破坏既有序列化）

### 阶段 B 完成后回归：
.venv/bin/python -m pytest backend/tests/test_s081_prd_strategies.py backend/tests/test_s081_strategy_matcher_pool_item.py backend/tests/test_s079_dragon_tiger_seat_filter.py backend/tests/test_s079_position_advisor_cap.py backend/tests/test_s079_pre_market_workflow_p2.py backend/tests/test_s079_workflow_p2_api.py -m "not live" --no-cov -q
- 验证：S081 PRD 2 战法 + S079 仓位闸/龙虎榜测试不破坏（match_strategies 加 card 参数向后兼容）

### 阶段 C 完成后回归：
cd frontend && npx tsc --noEmit
- 验证：前端类型无 error（DiagnosisCard 类型扩展不破坏既有类型）

### 阶段 D 完成后全量回归：
.venv/bin/python -m pytest backend/tests/test_s070*.py backend/tests/test_s079*.py backend/tests/test_s081*.py backend/tests/test_s084*.py backend/tests/test_candidate_funnel*.py backend/tests/test_s002*.py -m "not live" --no-cov -q
- 验证：S070 + S079 + S081 + S084 + candidate_funnel + S002 全套不破坏

### 阶段 E 最终验收：
1. 新增测试全过：.venv/bin/python -m pytest backend/tests/test_s084*.py -m "not live" --no-cov -q
2. 前端 tsc：cd frontend && npx tsc --noEmit
3. AC 逐条核对（spec §6 AC1-AC11，AC5a-d 移 backlog 不在范围）
4. 写验收报告 specs/S084-选股池战法解耦/验收报告.md

### 回归失败处置：
- 如果回归测试失败，必须修复后重跑，不能跳过
- 如果是既有测试因为新字段/新参数导致失败，优先改测试适配（不破坏既有行为）
- 如果是新增代码 bug，修代码
- 记录每个回归套件的 passed/failed 数

## 工程约束
- 不要 git checkout（在 feature/S084 分支工作），改完跑 pytest 我来 commit
- em_get 防封底线不可绕过
- 缺数据标 None 不臆造
- T-1 昨日日期用 is_trading_day 判断非交易日回溯
- 每完成一个阶段跑 pytest 验证 + 回归测试

## 完成后告诉我
1. 改动文件列表（新增+修改）
2. 新增测试文件 + 测试用例数
3. 每个阶段的回归测试结果（passed/failed）
4. 完成的 task ID（A1-A15 + B1-B6 + C1-C4 + D1 + E1-E4）
5. AC 逐条核对结果
6. 阻塞（如有）
