# Spec: S093 — 三视图内容重组与飞书通知

> 状态：设计闭合（grill 讨论 5 轮，用户确认全部决策），待实现
> 作者：Codex 会话  日期：2026-08-22
> 级别：**large**（跨层 + 碰外部数据源（tencent_quote 实时行情）+ 新增通知渠道（飞书 webhook）+ 新增 AI 工具（盘后 LLM 总结）+ 涉及操作建议/风险提示信号）
> 流程门：spec.md + plan + task；feature 分支 `feature/S093-内容重组与飞书通知`；完整 grill；playwright 验收
> 依赖：S092 已合并（三视图交易日锚 + dateTriplet + today_status + TaskStatusCard + useMarketClock 已在 develop）

## 0. 起因

S092 实现了三视图交易日锚模型（复盘/当日/前瞻 + dateTriplet + 双定时器 + 任务状态卡片），但内容分配有偏差：
1. **当日 Tab 过重**——PreMarketBriefing 全量简报内容堆在当日，但当日应该是"盯盘执行台"不是"选股决策台"
2. **前瞻 Tab 过轻**——只有 breakout 弱信号选股，缺漏斗选股 + 战法匹配 pipeline
3. **战法战绩表维度不对**——跨阶段统计被塞进前瞻 Tab，不属任何交易时段
4. **stage 枚举不准**——盘中到 15:00 不是 15:30（最新交易规则），缺 pre_open（集合竞价）
5. **无通知机制**——用户需要前瞻选股结果推送 + 盘中风险提示推送，不能只靠被动看页面

用户在 grill 讨论中逐条确认：前瞻吸收全量选股决策内容、当日改为盯盘执行台、战法战绩移出三 Tab、stage 枚举修订（含 pre_open + 盘中延长到 15:30）、新增飞书通知 + 规则引擎实时信号 + AI 盘后总结。

## 1. 问题 / 目标

1. **三 Tab 内容重组**：前瞻=选股决策全量 pipeline；当日=盯盘执行台（前瞻结论看板+盘中因子+操作建议+风险提示）；复盘=保持不变+行为对照卡移入
2. **stage 枚举修订**：pre_market=post_market（17:15→09:00 跨夜就绪合一）；新增 pre_open（09:00-09:30 集合竞价）；intraday 延长到 15:30；post_transition 从 15:30 开始
3. **飞书通知**：前瞻选股结果推送（17:15 漏斗预计算完成后）+ 盘中风险提示推送（规则引擎触发）
4. **盘中因子监控**：战法相关因子实时变化，按战法分类匹配，给操作建议和风险提示
5. **操作建议**：规则引擎实时（确定性信号 if-then）+ AI 盘后总结（LLM 综合分析）
6. **战法战绩移出**：公共区入口卡片跳 `/strategy` 独立路由
7. **交叉验证**：漏斗 final_candidates ∩ breakout top-N 双重确认徽章

## 2. 背景（现状挂载点）

- S092 已实现：`resolve_date_triplet`（vr_paths.py）、`GET /api/workflow/date-triplet`、`today_status`（scheduled_tasks router）、`useDateTriplet`/`useMarketClock`/`TaskStatusCard`、Workflow.tsx 三 Tab 容器
- 前瞻 Tab 当前：PremarketSelectionSection（breakout 弱信号）+ 战法战绩表折叠区
- 当日 Tab 当前：PreMarketBriefing（情绪天气/因子漏斗/候选池/战法匹配/行为对照/T-1语境/验证卡）
- 复盘 Tab 当前：PostMarketReview（三问/昨日漏单/结算入口/验证卡/盘后工具入口）
- 战法组件：StrategyMatchMatrix（数据源 `usePreMarketBriefing(date).scored_candidates`）、CandidateFunnelEmbed（数据源 `briefing.funnel_layers`）
- 实时数据源：`tencent_quote`（个股实时价格，sentiment_weather.py:1114 已在用）、`intraday_sentiment`（市场级 5min 采样，09:25-15:00 运行）
- 通知：scheduled_tasks 有 `notify_on_success`/`notify_on_failure` 字段但未实现实际推送；前端有 `toast`（sonner）+ `BombAlertBanner`
- 飞书 webhook：需新建通知模块，飞书机器人 webhook 发 card 消息
- 规则引擎：需新建规则定义 + 触发逻辑（if-then 确定性信号）
- AI 总结：盘后调 LLM 生成"今日操作回顾 + 明日建议"，异步生成不阻塞盘中

## 3. 需求清单

### A. stage 枚举修订（后端 + 前端）

- [ ] R1 **stage 枚举修订**（替换 S092 R3 时段表）：

  | stage | 时间 | 语义 | 自动高亮 Tab |
  |---|---|---|---|
  | `pre_market` | 17:15 → 09:00 | 跨夜就绪（今日盘后=次日盘前） | 前瞻 |
  | `pre_open` | 09:00 → 09:30 | 集合竞价/开盘准备 | 当日 |
  | `intraday` | 09:30 → 15:30 | 盘中交易（最新交易规则延迟到 15:30） | 当日 |
  | `post_transition` | 15:30 → 17:15 | 数据采集渐进 | 复盘 |
  | `post_market` | 17:15 → 09:00 | 跨夜就绪（= 次日 pre_market） | 前瞻 |

  - `pre_market` 和 `post_market` 是同一段（17:15→09:00），后端返回同一个值
  - 非交易日保持 `post_market` 就绪态（S092 已实现）
  - 盯盘 = `pre_open` + `intraday` = 09:00-15:30

- [ ] R2 **resolve_date_triplet 改 stage 边界**：
  - `pre_market`: now < 09:00（含隔夜）
  - `pre_open`: 09:00 ≤ now < 09:30（新增）
  - `intraday`: 09:30 ≤ now < 15:30（延长 30 分钟）
  - `post_transition`: 15:30 ≤ now < 17:15（推迟 30 分钟）
  - `post_market`: now ≥ 17:15
  - 定时器推进点不变：15:30 复盘独立推进 + 17:15 F 推进

- [ ] R3 **stage → Tab 自动高亮修订**：
  - `pre_market` → 前瞻
  - `pre_open` → 当日
  - `intraday` → 当日
  - `post_transition` → 复盘
  - `post_market` → 前瞻

### B. 前瞻 Tab 吸收选股决策全量内容（前端重构）

- [ ] R4 **前瞻 pipeline 结构**：

  ```
  ① 漏斗选股（CandidateFunnelEmbed，date=F）
     R1涨停池 → R2换手/北向 → R3筹码/龙虎榜 → final候选
  ② 战法匹配（StrategyMatchMatrix，date=F）
     票×战法命中矩阵（数据源 scored_candidates，156 条）
  ③ breakout 弱信号（PremarketSelectionSection，date=forward）
     全市场接近新高 → 风控参数（max_hold=3 短线）
  ④ 交叉验证徽章（漏斗∩breakout 双重确认，前端取交集 O(1)）
  ```

  - ①②数据日=F（漏斗和战法匹配基于 T 日收盘数据算出来的"选 T+1 标的"结果）
  - ③数据日=forward（breakout 用 T-1=F 的 close 算 breakout 分数）
  - 交叉验证：漏斗 final_candidates ∩ breakout top-N 的票打"双重确认"绿色徽章；仅漏斗有打"仅漏斗"；仅 breakout 有打"仅 breakout"

- [ ] R5 **前瞻辅助决策折叠区**（从 PreMarketBriefing 迁移）：
  - 情绪天气（WeatherDecisionBar）— 天气影响选股决策
  - P2 仓位闸（P2RiskPanel）+ advisory 仓位摘要 — 选完股配仓位
  - 行为对照卡（ShadowComparisonSection）→ 移到复盘（见 R12）
  - T-1 数据（T1Tab）+ 语境（ContextTab，含暴风雨预测）— 选股 pipeline 输入
  - 战法胜率对比（WinRateCompareSection）→ 移到战法独立页（见 R11）

### C. 当日 Tab 重新定义为盯盘执行台（前端重构 + 后端新增）

- [ ] R6 **当日 Tab 结构**：

  ```
  第一层：前瞻结论标的看板（核心）
    - 三组分组：双重确认(漏斗∩breakout) / 仅漏斗 / 仅breakout
    - 每只票：实时价格/涨跌幅/封板状态/持仓状态
    - 点击跳 IntradayMonitor 个股详情
    - 数据源：usePreMarketBriefing(F) + usePremarketSelection(forward)，前端取交集
  
  第二层：自选盯盘（后续补充设计，本 spec 留位不实现）
  
  第三层：盘中因子变化（待办 S094，本 spec 仅留位）
    - 战法相关因子实时变化，按战法分类匹配
    - 市场级：涨停数/炸板数/涨跌比/连板梯队/板块轮动/北向资金
    - 个股级：价格/涨跌幅/封板状态/量比/换手
  
  盯盘入口卡片（全天可见，不门控时段）
    - /workflow/intraday（实时盯盘）
    - /workflow/alerts（炸板预警）
    - /workflow/coach（盯盘教练）
    - /advisory（仓位详情）
  ```

  - 当日 Tab 不再做选股 pipeline（全移前瞻）
  - 数据来源：`usePreMarketBriefing(F)` 的 final_candidates + scored_candidates（前瞻结论复用）+ `usePremarketSelection(forward)` 的 candidates
  - 实时价格：`tencent_quote` 按需轮询（pre_open + intraday 时段）
  - 市场情绪实时指标：`intraday_sentiment` 采样数据（已有）

- [ ] R7 **持仓状态 chips**：`useWorkflowStates` 取候选/观察/监控/持仓/已结计数

- [ ] R8 **盯盘入口全天可见**：取消 `isIntraday` 门控，三个 EntryCard 常驻（S092 已补，需确认）

### D. 飞书通知（后端新增 + 配置）

- [ ] R9 **飞书 webhook 通知模块**：
  - 新建 `backend/notifications/feishu.py`：`send_feishu_card(webhook_url, title, content) -> bool`
  - webhook URL 存配置（`.vibe-research/feishu_webhook.txt` 或环境变量 `FEISHU_WEBHOOK_URL`）
  - 失败 catch 不抛（通知是增强，不阻塞主流程）
  - 卡片格式：飞书 interactive card（标题+正文+标签）

- [ ] R10 **前瞻选股结果通知**（17:15 漏斗预计算完成后触发）：
  - 触发点：`candidate_funnel_precompute` 任务 success 后
  - 内容：F 日期 + final_candidates 数 + 双重确认数 + top5 标的（code/name/基因分/命中战法）
  - 飞书卡片标题："📊 前瞻选股结果 {F日期}"
  - 异步推送（不阻塞 cron 链）

### E. 盘中风险提示（规则引擎 + 飞书通知）

- [ ] R11 **规则引擎定义**（确定性信号 if-then）：

  | 信号 | 触发条件 | 级别 | 飞书推送 |
  |---|---|---|---|
  | 封板跌破 | 持仓标的封单额 < 阈值 | HIGH | ✅ 即时 |
  | 炸板 | 持仓标的开板 | HIGH | ✅ 即时 |
  | 涨停 | 前瞻标的涨停 | INFO | ✅ 即时 |
  | 情绪恶化 | STI 评分连降 2 级 / 涨跌比 < 0.5 | MEDIUM | ✅ 即时 |
  | 连板梯队断裂 | 最高板 > 3 且无 2 板接力 | MEDIUM | ✅ 即时 |
  | 北向大幅流出 | 净流出 > 50 亿 | MEDIUM | ✅ 即时 |

  - 规则定义存 `backend/notifications/rules.py`，可配置阈值
  - 触发逻辑：intraday_sentiment 每次采样后检查规则
  - 去重：同一信号同一标的 5 分钟内不重复推送

- [ ] R12 **操作建议**：
  - **规则引擎实时**（盘中）：确定性信号生成操作建议（如"炸板→建议止损"、"封板跌破→建议关注"），推飞书卡片
  - **AI 盘后总结**（15:30 后异步）：LLM 汇总当日所有信号 + 持仓表现 + 市场数据，生成"今日操作回顾 + 明日建议"自然语言总结，推飞书文章
  - AI 总结不在盘中实时调（成本高+延迟大），盘后异步生成

### F. 战法战绩移出三 Tab

- [ ] R13 **战法独立路由**：
  - 新建 `/strategy` 路由（或复用已有 `/strategy/funnel/forward-test`）
  - 内容：战法战绩表（registry+backtest）+ 前向测试入口 + 阈值配置入口
  - 公共区入口卡片：`<EntryCard to="/strategy" title="战法管理" />`（锚条下方常驻）
  - 从前瞻 Tab 删除战法战绩折叠区

### G. 复盘 Tab 微调

- [ ] R14 **行为对照卡移入复盘**：
  - ShadowComparisonSection 从当日 Tab（PreMarketBriefing）移到复盘 Tab（PostMarketReview）
  - 理由：行为对照是 28 天历史回看，属复盘语义不属当日盯盘
  - 复盘 Tab 其他内容保持不变

### H. 待办（不在本 spec 实现，记录为后续 spec）

- [ ] R15 **盘中因子实时监控**（S094）：战法相关因子在盘中实时变化，按战法分类匹配，给操作建议
- [ ] R16 **自选盯盘**（S095）：用户持仓/关注但不在前瞻结果里的标的
- [ ] R17 **其他通知渠道**：桌面通知/邮件/discord/telegram（飞书先行，其他后续）
- [ ] R18 **AI 盘后总结**：LLM 生成每日操作回顾（本 spec 留接口位，S094 完整实现）

## 4. 受影响文件

### 后端
| 文件 | 改动 |
|---|---|
| `backend/vr_paths.py` | resolve_date_triplet stage 边界修订（pre_open 新增 + intraday→15:30 + post_transition→15:30） |
| `backend/notifications/feishu.py` | 新建——飞书 webhook 通知模块 |
| `backend/notifications/rules.py` | 新建——规则引擎定义 + 触发逻辑 |
| `backend/notifications/__init__.py` | 新建——模块入口 |
| `backend/scheduled_tasks.py` | candidate_funnel_precompute success 后触发飞书通知（R10） |
| `backend/routers/intraday_sentiment.py` | 采样后检查规则引擎触发飞书通知（R11） |
| `backend/tests/test_s093_*.py` | 新建——stage 枚举 + 飞书通知 + 规则引擎测试 |

### 前端
| 文件 | 改动 |
|---|---|
| `frontend/src/pages/Workflow.tsx` | 前瞻 Tab 重构（补漏斗+战法匹配+交叉验证）+ 当日 Tab 重构（盯盘执行台）+ 战法入口移公共区 + stage→Tab 高亮修订 |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | 改为当日盯盘执行台（前瞻结论看板+持仓chips+市场情绪+盯盘入口）；选股决策内容迁出 |
| `frontend/src/pages/workflow/PostMarketReview.tsx` | 加行为对照卡（ShadowComparisonSection） |
| `frontend/src/pages/StrategyPage.tsx` | 新建——/strategy 独立路由页（战法战绩+前向测试+阈值配置入口） |
| `frontend/src/router.tsx` | 加 /strategy 路由 |
| `frontend/src/components/workflow/WatchlistBoard.tsx` | 新建——前瞻结论标的看板组件（三组分组+交集+实时价格） |
| `frontend/src/components/workflow/CrossValidationBadge.tsx` | 新建——交叉验证徽章组件 |
| `frontend/src/tests/*.test.tsx` | 适配——Workflow/PreMarketBriefing/PostMarketReview 测试更新 |

## 5. 验收标准

- [ ] AC1 stage 枚举正确：pre_market(17:15→09:00) / pre_open(09:00→09:30) / intraday(09:30→15:30) / post_transition(15:30→17:15) / post_market(17:15→09:00)
- [ ] AC2 前瞻 Tab pipeline 完整：①漏斗选股(F) → ②战法匹配(F) → ③breakout(forward) + 交叉验证徽章
- [ ] AC3 当日 Tab = 盯盘执行台：前瞻结论看板 + 持仓chips + 市场情绪 + 盯盘入口（无选股 pipeline）
- [ ] AC4 战法战绩移出三 Tab → /strategy 独立路由 + 公共区入口卡片
- [ ] AC5 行为对照卡在复盘 Tab（不在当日）
- [ ] AC6 盯盘入口全天可见（不门控时段）
- [ ] AC7 飞书通知：前瞻选股结果 17:15 后推送 + 盘中风险提示规则触发推送
- [ ] AC8 规则引擎：封板跌破/炸板/涨停/情绪恶化/连板断裂/北向流出 6 条规则触发正确
- [ ] AC9 交叉验证徽章：漏斗∩breakout 双重确认标的标绿
- [ ] AC10 离线全测绿（pytest + vitest + tsc）
- [ ] AC11 dev server 冒烟（三 Tab 内容重组 + stage 修订 + 飞书通知发送）

## 6. 设计取舍

1. **S092 不改不动**：S092 是已实现基线，spec 文件保留作历史决策记录。S093 在 S092 基线上做内容重组 + stage 修订 + 通知新增。S092 的 R3 时段表/R23 内容归属被 S093 替换，冲突审查表见 §9。
2. **pre_market = post_market**：今日盘后（17:15）= 次日盘前（到 09:00）。后端返回同一个 stage 值，前端高亮同一 Tab（前瞻）。语义自洽——"为次日选股做准备"的时段。
3. **盘中延长到 15:30**：最新交易规则收盘延迟到 15:30（原 15:00）。post_transition 从 15:30 开始。
4. **规则引擎 + AI 分层**：盘中确定性信号用规则引擎（毫秒级响应），盘后综合分析用 AI（异步不阻塞）。不在盘中调 AI——成本高 + 延迟大 + 盘中需要即时性。
5. **飞书先行**：通知渠道先做飞书 webhook（简单 POST），其他渠道（桌面/邮件/discord/telegram）入待办。
6. **当日不做选股 pipeline**：选股决策全在前瞻完成，当日只做"拿着前瞻结论盯盘执行"。避免重复工作。
7. **交叉验证前端做**：漏斗∩breakout 交集在前端取（两个列表 code 交集），O(1) 成本，不需要新端点。

## 7. 合规自查

- [x] 不臆造数据：前瞻选股结果来自真实漏斗+breakout 数据；操作建议基于规则引擎确定性信号，不臆造
- [x] 私有数据隔离：飞书 webhook URL 存 `.vibe-research/`（gitignored），不进 git
- [x] em_get 防封：tencent_quote 不走 em_get（走 tencent API），intraday_sentiment 已有防封
- [x] 涉及操作建议/风险提示的改动过合规自查：规则引擎只给"建议"和"提示"，不自动下单（软 gate）
- [x] 历史统计特征标注：飞书通知卡片标注"历史统计特征，市场有风险，研究参考"

## 8. 已知盲点

1. **飞书 webhook 频率限制**：飞书机器人有消息频率限制（每分钟约 5 条），盘中高频信号需去重（5 分钟内同标的同信号不重复）。规则引擎已设计去重。
2. **tencent_quote 轮询频率**：盘中按需轮询持仓标的实时价格，频率不宜过高（防 IP 限流）。建议 30s-60s 轮询，仅在 pre_open+intraday 时段。
3. **AI 盘后总结成本**：LLM 调用成本 + 延迟。盘后异步生成不阻塞，但需控制 token 用量。S094 完整设计。
4. **`last_run_at` 时区**（GR5 遗留）：naive datetime 假设服务器=北京时区。云部署另立 spec。

## 9. 冲突审查（S092 → S093）

| S092 R-item | S092 决策 | S093 决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| R3 时段表 | 盘中 09:30-14:59，收盘 15:00 | 盘中 09:30-15:30，收盘 15:30 | 替换 | resolve_date_triplet 改 stage 边界 |
| R3 时段表 | pre_market=00:00-09:29 | pre_market=17:15→09:00 + 新增 pre_open=09:00-09:30 | 替换 | resolve_date_triplet 新增 stage |
| R3 时段表 | post_transition=15:00-17:15 | post_transition=15:30-17:15 | 替换 | 同上 |
| R3 时段表 | pre_market 和 post_market 分开 | 合一为 17:15→09:00 | 替换 | 后端返同一值，前端高亮同一 Tab |
| R23 | 战法匹配归"当日" | 战法匹配归"前瞻"（date=F） | 替换 | StrategyMatchMatrix 移前瞻 Tab |
| R23 | 战法胜率归"复盘" | 移出三 Tab → /strategy 独立路由 | 替换 | 新建 /strategy 路由 + 公共区入口 |
| (新) | 当日=PreMarketBriefing 全量简报 | 当日=盯盘执行台（前瞻结论+盘中因子+操作建议+风险提示） | 替换 | PreMarketBriefing 选股内容迁前瞻，当日新建盯盘看板 |
| (新) | 无通知机制 | 飞书通知（选股结果+盘中风险提示） | 新增 | 新建 notification 模块 |
| (新) | 无规则引擎 | 规则引擎实时信号 + AI 盘后总结 | 新增 | 新建 rules.py + LLM 接口位 |
| R12 | stage→Tab：post_market→前瞻 | 保持不变（post_market→前瞻） | 共存 | 无迁移 |
| R15 | toISOString 修复 | 保持不变 | 共存 | 无迁移 |
| R18 | today_status 后端推算 | 保持不变 | 共存 | 无迁移 |

**处置原则**：替换项在 S093 实现时直接改代码，S092 代码作为基线被覆盖；共存项不改。冲突审查表是实现时的权威参考——不需要翻 S092 spec。

## 10. 阶段划分

### S1 后端 stage 修订（地基）
- resolve_date_triplet stage 边界修订 + pre_open 新增
- 测试覆盖

### S2 后端飞书通知 + 规则引擎
- notifications/feishu.py + rules.py + __init__.py
- candidate_funnel_precompute success 后触发通知
- intraday_sentiment 采样后检查规则触发通知
- 测试覆盖

### S3 前端前瞻 Tab 重构
- 补入漏斗选股 + 战法匹配 + 交叉验证徽章
- 辅助决策折叠区（情绪天气/P2/advisory/T-1/语境）
- 删战法战绩折叠区（移 /strategy）

### S4 前端当日 Tab 重构
- PreMarketBriefing 改为盯盘执行台
- 前瞻结论看板组件（WatchlistBoard）
- 持仓 chips + 市场情绪 + 盯盘入口全天可见
- 选股决策内容迁出

### S5 前端战法独立页 + 复盘微调
- /strategy 路由 + StrategyPage
- 公共区战法入口卡片
- 复盘 Tab 加行为对照卡

### S6 全量回归 + 冒烟
- pytest + vitest + tsc 全绿
- dev server 冒烟（三 Tab 内容 + stage 修订 + 飞书通知发送）
