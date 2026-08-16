# S066 实现计划

> 一切为了提高期望收益（赚钱）。Phase 0 先验证 alpha 存在，再逐步增加复杂度。
> 依赖链：0a(回填) -> 0b(回归) -> 0c(阈值) -> 0d(权重) -> 0e(前向测试) -> Phase 1/2(并行) -> Phase 3(前端)

## §44 验证后修订（2026-08-16，按 AGENTS.md §44 数据支撑优先）

> **Phase 0b/0e 回归 + 前向测试均未验证 alpha（§44 bar）**：
> - Phase 0b：全 6 因子 within-day（横截面）r≈0、CI 含 0（pooled r=+0.07 是日间 confound，非选股力）。
> - Phase 0e（`tools/forward_test_backfill.py` retroactive 跑 31 天 eastmoney_live）：策略胜率 49.2% CI[44.8,53.6] vs 随机基准 50.2% CI[48.2,52.3]，**lift 0.98x <2x = 噪声**（且 <1 略劣于随机）。
> - 三方一致：§1.1 grill Q1（total_score 无 edge）+ Phase 0b + Phase 0e → S066 信号在 §44 bar 下**均无次日收益 edge**。
>
> **§13.0 被违反**：Phase 1-3（9 战法+kill+Kelly+板块+日历，全复杂度）建在 Phase 0 未验证的地基上——Phase 0e runner（run_daily_forward_test）此前未接线、forward_test_records 0 行，§13.0"先验证 alpha>60% 再加复杂度"门没过。框架 pass-logic 也不合规（pass_threshold=48=回测60×0.8 弱 bar ≠ §13.0 绝对 60，无随机基准）。
>
> **修订路径**（不回退 Phase 1-3，但诚实标注未验证）：
> 1. **HOLD 新复杂度**（Phase 4+ / 新层）至 alpha 验证（§13.0"不提升的不加"）。
> 2. **修框架 pass-logic 到 §44 合规**：加随机基准 + lift、门槛对齐 §13.0 绝对 60（非 48 degradation）。
> 3. **weather-adapted 重跑**：Phase 0e 回填接历史天气（sentiment_context），测完整架构非退化版（当前 weather=None 是下界）。
> 4. **60 天积累复验**：eastmoney_live 满 60 天后重跑 Phase 0b（within-day r）+ 0e（胜率 lift），lift 破 2x + r 显著 → alpha 成立；否则确认无 edge。
> 5. **前端 getAStockTimeInfo 重构**：改用后端 /api/workflow/status 源（单源 + 北京时区 + 节假日 is_trading_day），去本地重复（drift 源；非交易日 fix 见 591f536，节假日待重构补）。
>
> **原 Phase 1-3 计划状态**：已实现（Phase 0-3 全闭合），但建在 placeholder/null-验证信号上——非"validated alpha"，是"待验证的架构 shape"。下方原计划保留作参考。

## Phase 0：数据 + 统计 + 前向验证（串行，每步依赖上一步）

### 0a kline 回填（1 天）
- 安装 baostock（已装）
- 从 gene_scores.db 取全部 6537 条 (date, code) 对
- 对 1104 个独立 code 用 BaoStock 拉日K（qfq，含 turn/pctChg/amount/open/high/low）
- 匹配每条 -> next_bar 的 open/close/high/low/涨停价
- 输出 .vibe-research/backtest_samples.json（6537 条，含 5 因子 + 次日收益 + gap + fill_rate）
- 同时计算 benchmark_A（全 6537 样本次日红盘率）和 benchmark_B（CSI300 次日上涨概率）
- 备用源：新浪 API（已测试可用），kline_multi（4 源回退）
- 合并策略：独立脚本，直接 develop 提交

### 0b 全样本因子回归（1 天）
> **§44 修订（2026-08-16）**：双轨分层（kline_rebuild 3760 / eastmoney_live 2836，零重叠，spec §13 Phase 0b grill 决议）；二轮验证（日内/日间分解 + day-cluster bootstrap）证伪 rebound_rate 强信号 + 全 6 因子 within-day r≈0、CI 含 0 → **无已验证横截面选股因子**，权重改等权 placeholder（见 0d）。原"n=6537 单组"已废止。
- 对 5 因子 + zt_count 计算 Pearson r + 95% CI + p 值（**双轨分层**：kline 3760 / eastmoney 2836）
- 每个因子做五分位胜率（按 data_source 分组，非 qualify=1 子集）
- 2-way ANOVA 因子交互（仅 eastmoney_live 子集）
- 验证 alpha 来源假设（§14.1）
- 因子相关矩阵 + PCA 降维
- 输出 factor_significance.json
- 合并策略：独立脚本 + 分析报告，develop 提交

### 0c qualify 阈值优化（0.5 天）
- 对不同总分区间（30-40/40-50/50-60/60-70/70+）算胜率 + 样本量
- 找到胜率最高且样本 >= 100 的区间
- 输出最优 qualify 阈值
- 合并策略：并入 0b 报告

### 0d 策略分权重定稿（0.5 天）
> **§44 修订（2026-08-16）**：Phase 0b 二轮验证收回 rebound_rate 强信号（日级伪信号）+ 全 6 因子 within-day r≈0 → **3 套权重均改等权 placeholder（W1-W5=0.20）**。下方原具体权重（seal 60%/premium反向/freq反向）已废止，见 spec §4.1/§4.3。60 天 eastmoney_live 积累后重判热替换。
- ~~基于 0b 显著因子 + 0c 阈值，确定 3 套权重~~ → 等权 placeholder（无已验证信号，等权是唯一诚实起点）
- ~~涨停类：seal_rate/premium(反向)/freq(反向)/zt_count_golden~~ → 等权 0.20
- 非涨停类：等权起步（Phase 2 有数据后调）
- ~~暴风暴：seal_rate 60% + freq 反向 40%~~ → 等权 placeholder
- 输出 strategy_weights.json（等权 placeholder）
- 合并策略：并入 0b 报告

### 0e 前向测试（20 交易日，不投真金）
- 用 0d 权重跑系统：涨停股 x 策略分排序 x 板块周期 x 日历因子
- 每日记录推荐 vs 实际表现
- 通过标准：系统无崩溃 + 推荐胜率 >= 回测 x 0.8
  > **§44 修订**：此"×0.8 degradation"弱 bar（=48）≠ §13.0 绝对 60，且无随机基准 → §44-non-compliant（50% 随机策略也过 48）。实测策略 49.2% vs 随机 50.2% lift 0.98x 噪声（见 spec §13 + plan §44 修订路径第 2 条：修框架 pass-logic 对齐 60 + 加随机基准）。
- 不通过 -> 修 bug 再跑 20 天
- 合并策略：develop 分支跑，通过后 squash 合并

## Phase 1：涨停类策略实现（依赖 0d，可与 Phase 2 并行）

### P1-1 策略注册表 + 策略分计算（3 天）
- StrategyFunnelConfig dataclass + STRATEGY_FUNNEL_REGISTRY
- 3 套权重计算函数（涨停类/非涨停类/暴风暴）
- 天气硬开关 WEATHER_STRATEGY_MAP + FALLBACK
- 板块周期分析（§5：3 日时序 + 强度排名 + 停留天数 + 轮动检测 + 广度）
- 合并：feature/S066-strategy-registry

### P1-2 日历因子 + PositionAdvisor 增强（2 天）
- calendar_factor（周五 x0.7/节前 x0.3/周四 x1.0）+ 节后红包确认
- 置信度缩放（仓位 = base x (score - threshold) / (cap - threshold)）
- 组合级风控（板块集中度/总仓位/回撤熔断/策略去重/双层 kill criteria）
- 账户硬约束（max 5 只/max 10% 单股/max 20% 板块/min 30% 现金）
- 合并：feature/S066-position-advisor

### P1-3 游资席位分析（2 天）
- 预设画像 hot_money_seats_preset.json（拉萨天团/深圳游资/机构）
- 60 日龙虎榜聚合 -> hot_money_seats.json（周更）
- 行为突变检测（5 日增量 vs 60 日均值）
- hot_money_seat_risk 因子接入策略分
- 龙虎榜直连 fetch（绕过 em_get 熔断）
- 合并：feature/S066-hot-money-seats

### P1-4 资讯雷达上下文层（2 天）
- akshare stock_news_em() 主源接入
- 板块映射表 sector_mapping.json
- 三层接入（板块资讯热度/催化上下文/风险雷达）
- LLM 公告分类（走 chat 层，用户配置 AI provider）
- 合并：feature/S066-news-radar-context

### P1-5 执行与成本模型（2 天）
- 动态滑点模型（slippage = max(0.1%, 0.3% x order/daily)）
- 多持有期回测输出（T+1/T+2/T+3/T+5）
- 收益分布分析（偏度/盈亏比/Sortino/VaR/CVaR/最大单笔亏损）
- 可成交率统计（next_open < limit_up_price 的比例）
- 市场级熔断（指数跌幅 kill switch，用 tencent_quote 取指数）
- 合并：feature/S066-execution-model

### P1-6 统计严谨性 + 监控（2 天）
- 因子共线性矩阵 + PCA 输出
- 多重检验 Bonferroni 校正
- 选择偏差验证（qualify=0 样本回测）
- 压力测试（千股跌停/流动性枯竭/连续熔断三场景）
- 策略衰减监控（4 周滚动胜率告警）
- Regime 失效检测（反向因子失效 -> 触发重算）
- 性能归因（因子 beta 追踪）
- 合并：feature/S066-statistical-rigor

## Phase 2：非涨停类数据管道（不依赖 Phase 1，可并行）

### P2-1 板块成分股拉取（2 天）
- 东财 clist fs=b:BKxxxx 拉成分股（分页 50/页）
- BaoStock 行业分类作板块映射补充
- 缓存到 backend/data/sector_stocks.json
- 合并：feature/S066-sector-stocks

### P2-2 个股形态计算（3 天）
- 相对强度（个股 5 日涨幅 - 板块 5 日涨幅）
- 均线多头排列（MA5 > MA10 > MA20，从 kline 计算）
- 横盘形态（N 日振幅 < 阈值）
- MA5 接近度（低吸龙头）
- 成交额/量比突破检测（平台突破）
- 合并：feature/S066-pattern-scan

### P2-3 非涨停类策略分 + 漏斗（3 天）
- 低吸龙头策略分 + 漏斗（P1 优先）
- 反包战法策略分 + 漏斗
- 平台突破策略分 + 漏斗
- 龙头战法策略分 + 漏斗
- N字反击归入涨停类权重集
- 合并：feature/S066-non-limitup-strategies

### P2-4 产业资本 + 事件类因子（2 天）
- akshare stock_ggcx_em() 大股东增减持
- akshare stock_yjyg_em() 业绩预告
- akshare stock_share_unlock_em() 解禁
- 公告分类（利好/利空/风险提示，走 LLM）
- 除权除息日历 ex_dividend_calendar.json
- 合并：feature/S066-event-factors

## Phase 3：前端重构（依赖 Phase 1，可先做框架骨架）

### P3-1 盘前页面重构（3 天）
- 全时段定义（15:00 复盘 -> 22:00 深研 -> 7:00 确认 -> 9:15 竞价 -> 9:30 锁定）
- L0-L3 渐进式披露（默认 L0 极简，点击展开）
- 策略分组 tab（按天气激活的策略组）
- 候选卡片（L0 一行/ L1 摘要/ L2 详情/ L3 因子子页）
- 板块周期面板（启动/发酵/高潮/退潮 + 强度排名 + 轮动）
- 日历因子提示 + 节后红包确认
- 合并：feature/S066-premarket-frontend

### P3-2 盘中页面（2 天）
- 实时持仓 x 情绪联动（S063 继承）
- 条件场景 if-then + T+1 预判
- 日历因子标注（周五/节前降仓提示）
- 市场熔断提示（指数跌幅 > 3%）
- 黄金窗口采样展示（S063 继承）
- 合并：feature/S066-intraday-frontend

### P3-3 盘后页面（2 天）
- 当日候选 vs 实际表现（命中率）
- 策略分排名 vs 实际收益（有效性追踪）
- 性能归因面板（因子 beta 贡献）
- 策略衰减面板（4 周滚动胜率）
- 压力测试面板
- A 股定律验证面板
- 合并：feature/S066-postmarket-frontend

### P3-4 因子详情子页 + 面包屑（2 天）
- 74 条因子每个有子页（定义/公式/分布/相关性/分位胜率）
- 面包屑导航（首页 > 盘前 > 策略组 > 因子名）
- 返回按钮
- 超链接从候选卡片因子 -> 子页
- 合并：feature/S066-factor-subpages

## 合并策略

- Phase 0：develop 直接提交（独立脚本 + 数据文件）
- Phase 1-2：feature 分支 off develop，各模块独立分支，合并后删分支
- Phase 3：feature 分支，依赖 Phase 1 合并后 rebase
- 全部 squash 合并，commit message：feat(S066): ...
- live 冒烟：每个 feature 分支合并前跑关键路由冒烟测试

## 时间估算

| Phase | 工作量 | 可并行？ |
|---|---|---|
| 0a-0e | ~3 天 + 20 交易日前向测试 | 串行 |
| 1 (6 模块) | ~13 天 | 内部串行，可与 Phase 2 并行 |
| 2 (4 模块) | ~10 天 | 内部串行，可与 Phase 1 并行 |
| 3 (4 模块) | ~9 天 | 依赖 Phase 1 |
| 总计 | ~35 天 + 20 交易日 | Phase 1/2 并行可压缩到 ~25 天 |

实际节奏由 Phase 0e 前向测试结果决定——如果 Phase 0e 不通过，回到 0b 重算权重。
