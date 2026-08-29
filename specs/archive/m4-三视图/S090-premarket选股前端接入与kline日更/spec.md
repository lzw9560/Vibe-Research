# Spec: S090 — premarket_selection 前端接入 + kline 日更

> 状态：✅已实现（2026-08-22）
> 作者：lzw9560　日期：2026-08-21
> 关联：S071（premarket_selection 模型/端点/风控已就绪）、grill-reframe-final-verdict（下一步接 endpoint+live kline 日更+风控+前端）

## 1. 问题 / 目标

S071 premarket_selection 已建：模型（breakout_20d 弱正信号 + honest 标签，§44 day-cluster lift=1.67x<2x 非 validated 但 robust>1 + PnL+0.523%）+ 端点（`GET /api/strategy/premarket-selection`，返候选+风控+日历倍率）+ 风控（stop/take_profit/position/max_hold）。但两块缺：

1. **kline 日更**：`baostock_kline_cache.json`（premarket breakout 算 T-1 kline 的数据源）靠手动跑 `tools/refresh_kline_cache.py`，无 scheduled task 日更 → cache 可能 stale，breakout 信号不新鲜。
2. **前端接入**：`usePremarketSelection` hook 已写（`lib/query/premarket.ts`），但 PreMarketBriefing 页没接 → 用户看不到盘前选股结果。

grill reframe 记忆明确下一步"接 endpoint + live kline 日更 + 风控 + 前端"，endpoint+风控已就绪，剩 **live kline 日更 + 前端**。

## 2. 背景

- `refresh_kline_cache.py`：baostock `query_history_k_data_plus` 增量刷新（从最新 bar 后拉到 last_trading_date），原子写（temp→rename），re-login 每 150 股防超时。**baostock 非东财，不被 IP 限流**（§44 grill 资金流被 push2his 限流，kline 不受影响）。
- `scheduled_tasks._executors` 18 个 executor，加 task = 加 `_execute_xxx` 方法 + 注册 dict。
- `usePremarketSelection` hook：已写，queryKey `[strategy,premarket-selection,date,topN,minScore]`，staleTime 5min，`enabled=Boolean(date)`。
- PreMarketBriefing：盘前简报主页（696+ 行，接 SelectionPipeline/P2RiskPanel/HonestyBanner/VerificationCardBlock，用 `usePreMarketBriefing` date 感知）。

## 3. 需求清单

### B. kline 日更（数据基础，先做）
- [ ] B1：`scheduled_tasks` 加 `_execute_kline_refresh`（调 refresh_kline_cache 增量刷新逻辑，import 函数非 subprocess）
- [ ] B2：注册 `_executors["kline_refresh"] = self._execute_kline_refresh`
- [ ] B3：默认任务 cron 每日盘后（16:30 收盘后拉当日新 bar）
- [ ] B4：baostock login/logout 管理（复用 refresh_kline_cache re-login 逻辑）
- [ ] B5：刷新失败不阻塞（baostock 不可用标 degraded，不崩）

### A. 前端接入（可见产出，B 后做）
- [ ] A1：PreMarketBriefing 加 `PremarketSelectionSection` 组件（用 `usePremarketSelection` hook）
- [ ] A2：展示 breakout top-N 候选（code/name/breakout_score/breakout_binary/t1_close/entry_ref）
- [ ] A3：展示风控参数（stop_loss/take_profit/position_pct/max_hold + 日历倍率 calendar_multiplier）
- [ ] A4：展示 honest_label + disclaimer（弱信号标注，§44 <2x 非 validated，前向测试不投真金）
- [ ] A5：date 感知（URL date 参数传入，历史日也能看）
- [ ] A6：刷新按钮 + loading/error 态

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | 加 `_execute_kline_refresh` + 注册 `_executors` |
| `backend/tools/refresh_kline_cache.py` | 暴露可 import 的刷新入口函数（供 scheduled task 调，非 subprocess） |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | 加 PremarketSelectionSection |
| `frontend/src/components/workflow/PremarketSelectionSection.tsx`（新） | breakout 候选表 + 风控 + honest 展示 |
| `frontend/src/lib/api/types.ts` | PremarketSelectionData 类型（若未定义） |

## 5. 设计方案

### 5.1 kline 日更 task

scheduled task 调 refresh_kline_cache 的刷新逻辑（import 函数，非 subprocess——避免子进程开销 + 复用 re-login 逻辑）。盘后 16:30 跑（收盘后拉当日 bar）。baostock 不被限流，可每日跑。刷新范围 = cache 现有 code 全量增量（不新增 code，新上市股不在 premarket 选股池）。

### 5.2 前端 section

PreMarketBriefing 加 PremarketSelectionSection（独立 section，折叠，不污染既有布局）。用 `usePremarketSelection(date)` hook。展示 breakout 候选表 + 风控卡 + honest banner + 日历倍率。复用 HonestyBanner 组件展示 honest_label。

## 6. 验收标准

- [ ] B1-B5：kline_refresh scheduled task 注册成功，手动触发刷新 baostock_kline_cache（增量 append 新 bar），baostock 不可用标 degraded 不崩
- [ ] A1-A6：PreMarketBriefing 展示 premarket-selection 候选 + 风控 + honest，date 感知，刷新/loading/error 态正常

## 7. 合规与工程底线自查

- [ ] premarket_selection 弱信号（§44 <2x 非 validated）honest_label + disclaimer 标注（§1.2 不臆造）
- [ ] kline 日更 baostock 非东财不被限流（§1.2 防封不触）
- [ ] 前向测试期间不投真金（disclaimer）
- [ ] 用户私有数据未进 git

## 8. 测试计划

- 后端：kline_refresh task 单测（mock baostock，验证增量 append + re-login + degraded）
- 前端：PremarketSelectionSection vitest（mock usePremarketSelection，验证候选展示 + honest + 风控 + date 感知）

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| baostock 长会话超时返空 | 刷新缺数据 | re-login 每 150 股（refresh_kline_cache 既有逻辑） |
| premarket 用 stale kline（B 未跑前） | breakout 信号不新鲜 | B 先做，A 接入后展示新鲜 |
| 前端 section 污染 PreMarketBriefing | 页面臃肿 | 独立 section + 折叠 |

回滚：删 `_execute_kline_refresh` + 前端 section（纯新增）。
