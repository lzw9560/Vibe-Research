# S243 · 运维 Yield 看板（GC001 逆回购 / CB 信用申购 / 打新筛选）

> 状态：**已实现**（2026-11-08，Phase 1-3 + AC6 全闭环）
> 编号：S243 | 类型：feat | 分级：medium

## 1. 问题 / 目标

选股因子 alpha 穷尽 definitive（[[zuojianfa-finalized-2026-11-08]]：300+ 候选 0 edge，combo 9 专家 panel FALSIFIED）后，practitioner reframe 落地——散户真 edge 在**结构性 underpricing / 行为纪律**，不在选股。

本 spec 把三类散户结构性 yield 机会做成看板 + 提醒：
- **GC001 逆回购**：证券账户底仓闲置资金 sweep，零风险 2-3%/年（季末 5-15%）
- **CB 信用申购**：零成本无市值要求，纯信用额度申购
- **打新筛选**：发行 PE / 行业 PE 红线避雷（高溢价破发风险），非选股 alpha

非自动交易（PaperPortfolio 无 broker / xtquant / qmt）——提醒 + 规则辅助用户手动执行（反而 sound，用户最终决策）。

## 2. 需求清单

| # | 需求 | Phase |
|---|---|---|
| R1 | GC001 实时年化利率 + 季末/月末标记 | 1 |
| R2 | 14:30 cron 提醒（>3% 或季末/月末触发，否则 skip 不打扰） | 1 |
| R3 | 今日 CB 信用申购列表 | 2 |
| R4 | 09:15 cron 提醒（当日有 CB 才触发） | 2 |
| R5 | 今日打新 + 发行 PE / 行业 PE 筛选红线 | 3 |
| R6 | 09:17 cron 提醒（当日有新股才触发） | 3 |
| R7 | 前端 YieldPanel（GC001 + CB + 打新，1min 刷新） | 前端 |
| R8 | 提醒不轰炸（条件触发，飞书已优化 10-12 条/天） | 全局 |
| R9 | chat.TOOLS 加 query_yield（API + MCP + cli 自动获得） | AC6 |

## 3. 受影响文件

**新增**
- `backend/data/sources/akshare_yield.py`——GC001（bond_zh_hs_cov_min sh204001）+ CB（bond_zh_cov）+ IPO（stock_xgsglb_em）数据获取，走东财 datacenter + 熔断器 `circuit_breaker.get_breaker("eastmoney")` 防封
- `backend/routers/yield_ops.py`——`/api/yield/repo` `/cb` `/cb/today` `/ipo` `/snapshot`
- `backend/scheduler/executors/yield_ops.py`——`yield_repo_remind` / `yield_cb_remind` / `yield_ipo_remind`
- `backend/ai/tools/yield_tools.py`——`@register_tool("query_yield")` 聚合三类 yield（AC6）
- `frontend/src/components/yield/YieldPanel.tsx`——GC001 + 季末 badge + CB 列表 + 打新红线 panel
- `backend/tests/test_yield_ops.py`——14 测试（router + remind skip/trigger + AC6 注册/dispatch）

**修改**
- `backend/scheduler/executors/__init__.py`——`_executors` 注册 3 个 + wrapper
- `backend/scheduler/seed.py`——3 cron tasks（14:30 + 09:15 + 09:17，weekday 0-4）
- `backend/app.py`——挂载 yield_ops router
- `backend/ai/tools/__init__.py`——`from . import yield_tools` 触发注册
- `backend/tests/test_task_executor.py` + `test_regression_bugs.py`——`_EXPECTED_TASK_TYPES` 两处同步
- `backend/tests/test_registry.py`——expected tool set 加 `query_yield`
- `frontend/src/pages/sentiment/SentimentWeather.tsx`——加 "Yield" tab（Coins icon）

## 4. 验收标准

- **AC1** `/api/yield/repo` 返回 GC001 利率 + `quarter_end` / `month_end` 标记 ✅
- **AC2** `yield_repo_remind`：GC001<3% 且非季末/月末 → skip；≥3% 或季末 → 发飞书 ✅
- **AC3** `/api/yield/cb` + `/api/yield/cb/today` 返回 CB 列表 ✅
- **AC4** `yield_cb_remind`：当日无 CB → skip；有 → 发飞书 ✅
- **AC5** `/api/yield/snapshot` 聚合 repo + cb_today + ipo_today ✅
- **AC6** `query_yield` 注册进 `chat.TOOLS`（`registry.get_openai_tools()` 含 `query_yield`），`registry.execute("query_yield", {})` 聚合三类 yield + summary；MCP + cli 自动获得（§3 架构：registry 注册 = 三出口同获）✅
- **AC7** 前端 YieldPanel 1min 刷新 + 季末 badge + 打新红线 ✅
- **AC8** 提醒条件触发不轰炸（yield 最多 3 条/日：09:15 CB + 09:17 打新 + 14:30 逆回购，仅触发时）✅

## 5. 打新筛选红线（避雷，非选 alpha）

- 🔴 **高溢价**：发行 PE / 行业 PE > 1.5（破发风险高，建议跳过）
- 🟢 **折价**：PE / 行业 PE < 1.0（较安全）
- ⚠ **北交所**：流动性差标注

## 6. 合规自查（§1 弱合规）

- ✅ 工程底线——不臆造：数据全走 akshare 公开端点（bond_zh_hs_cov_min / bond_zh_cov / stock_xgsglb_em），可复算
- ✅ 工程底线——私有数据隔离：无持仓/研报/API key 涉入
- ✅ 工程底线——防封：东财 datacenter 走 `circuit_breaker.get_breaker("eastmoney")`，不裸调 requests
- ✅ 弱合规：yield 是公开市场操作（逆回购/CB/打新），无个股推荐，无方向性研判

## 7. 测试

14 passed（`test_yield_ops` 12 + `test_registry` AC6 set 1 + dispatch 1）。`test_task_executor` + `test_regression_bugs` `_EXPECTED_TASK_TYPES` 两处同步。tsc 干净。

## 8. commits

- `26748a9` feat(S243): 前端 YieldPanel
- `ca2fe99` feat(S243): 运维 yield 看板——GC001 逆回购 sweep 提醒 + CB 信用申购提醒
- `8094bae` feat(S243): Phase3 打新筛选——IPO 日历 + 发行 PE / 行业 PE 避雷红线
- AC6（本 commit）：`yield_tools.py` + `__init__` 注册 + `test_registry` expected set + `test_yield_ops` AC6 两测试

## 9. 非自动交易说明

PaperPortfolio 无 broker / xtquant / qmt——提醒 + 规则辅助用户手动执行。飞书推送（已优化 10-12 条/天，yield 提醒最多 3 条/日，仅触发条件时）。
