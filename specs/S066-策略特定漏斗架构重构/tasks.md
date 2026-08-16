# S066 原子任务拆分

> 按 plan.md 的 Phase 分组。每个任务标注 [B]=后端 [F]=前端 [T]=测试 [D]=数据

## §44 验证后状态（2026-08-16）

> **Phase 0a-0e + Phase 1-3 已实现**（Phase 0-3 全闭合），但建在 placeholder/null-验证信号上（Phase 0b within-day r≈0 + Phase 0e 胜率 49.2% vs 随机 50.2% lift 0.98x 噪声 → §44 bar 下无 validated alpha）。详见 plan.md §44 修订段 + spec §1.1/§13。
> **HOLD 新复杂度**（Phase 4+/新层）至 alpha 验证（§13.0"不提升的不加"）。
> **下方原任务（001-113）保留作参考**（已建但建在 placeholder）；新增 §44 修订路径任务见文末。

## Phase 0a：kline 回填

- [D][B] 001: 从 gene_scores.db 取全部 6537 条 (date, code) 对，去重得到 1104 个独立 code
- [D][B] 002: 写 BaoStock 批量拉取脚本（qfq K线，含 turn/pctChg/amount/open/high/low），1.5s 间隔，进度日志
- [D][B] 003: 对每条 (date, code) 匹配 kline -> 取 next_bar 的 open/close/high/low + 涨停价
- [D][B] 004: 计算 gap_pct = (next_open - close) / close * 100
- [D][B] 005: 计算 fill_rate = count(next_open < limit_up_price) / total
- [D][B] 006: 计算 benchmark_A（全样本次日红盘率）+ benchmark_B（CSI300 次日上涨率）
- [D][B] 007: 输出 .vibe-research/backtest_samples.json（6537 条完整样本）
- [T] 008: 验证样本完整性（无除权假跌、无缺失日期、next_bar 存在率 > 95%）

## Phase 0b：全样本因子回归

- [B] 009: 对 5 因子 + zt_count 计算 Pearson r + 95% CI + p 值（§44：双轨分层 kline3760/eastmoney2836；within-day r≈0、CI 含 0 → 无显著因子）
- [B] 010: 每个因子做五分位胜率（全样本）
- [B] 011: 2-way ANOVA 因子交互（seal_rate x freq, premium x seal_rate 等）
- [B] 012: 因子相关矩阵（5x5 Pearson）+ PCA 降维（主成分解释方差比）
- [B] 013: 验证 alpha 来源假设 A/B/C/D（§14.1）
- [B] 014: 多重检验 Bonferroni 校正（15+ 检验的 adjusted p）
- [B] 015: 输出 factor_significance.json（每因子 r/CI/p/分位胜率/交互/bonferroni）
- [T] 016: 验证 benchmark_A 已计算，策略 alpha = 策略胜率 - benchmark_A

## Phase 0c：qualify 阈值优化

- [B] 017: 对总分区间 30-40/40-50/50-60/60-70/70+ 算胜率 + 样本量 + 95% CI
- [B] 018: 找到胜率最高且样本 >= 100 的区间 -> 最优阈值
- [B] 019: 选择偏差验证：qualify=0 样本上做同样分位胜率

## Phase 0d：策略分权重定稿

- [B] 020: 涨停类权重（§44：0b within-day r≈0 无显著因子 → 等权 placeholder W1-W5=0.20，rebound 收回）
- [B] 021: 暴风暴权重（§44：等权 placeholder，原 seal 60%+freq反向 已废止）
- [B] 022: 非涨停类权重（等权 placeholder 起步，Phase 2 后调）
- [B] 023: 输出 strategy_weights.json（等权 placeholder）

## Phase 0e：前向测试

- [B] 024: 搭建 paper trading 框架（每日记录推荐 vs 实际，无真金）
- [B] 025: 跑 20 交易日，每日日志
- [T] 026: 验证通过标准（§44：原"胜率>=回测×0.8"=48 弱 bar ≠ §13.0 绝对60 + 无随机基准 → 不合规；实测 49.2% vs 随机 50.2% lift 0.98x 噪声。须改：对齐 60 + 加随机基准+lift）

## Phase 1：涨停类策略实现

### P1-1 策略注册表
- [B] 027: StrategyFunnelConfig dataclass 定义
- [B] 028: STRATEGY_FUNNEL_REGISTRY 初始化（10 个策略 + storm_reversal）
- [B] 029: WEATHER_STRATEGY_MAP + FALLBACK_STRATEGIES 天气硬开关
- [B] 030: 3 套策略分计算函数（涨停类/非涨停类/暴风暴）
- [B] 031: 天气 -> 策略组 -> 策略分排序 -> 候选 的完整流程编排

### P1-2 板块周期分析
- [B] 032: 从 gene_scores.db 按 (date, industry) 聚合涨停股数
- [B] 033: 3 日时序计算（count_today + count_avg_3d + momentum）
- [B] 034: 阶段分类（启动/发酵/高潮/退潮/冷门/无历史）
- [B] 035: 板块强度排名（zt_count + momentum + fund_flow）
- [B] 036: 板块停留天数追踪
- [B] 037: 跨板块轮动检测（排名变化 >= 5 位）
- [B] 038: 板块广度（up_count / (up_count + down_count)）
- [B] 039: 板块阶段标注（§5.4 Q2：修饰不接策略分——验证驳了方向，改纯 LABEL 标候选卡；60 天后回归再议）

### P1-3 日历因子 + PositionAdvisor
- [B] 040: calendar_factor 函数（周五 x0.7/节前 x0.3/周四 x1.0）
- [B] 041: 节后红包确认策略（跳空高开加仓/跳空低开清退）
- [B] 042: holidays.json 节假日日历（2026 年）
- [B] 043: 置信度缩放（仓位 = base x (score - threshold) / (cap - threshold)）
- [B] 044: 组合级风控（板块集中度 max 2/总仓位 max 30%/回撤熔断 8%/策略去重）
- [B] 045: 双层 kill criteria（策略级 >= 5/组合级 >= 8 每 5 日）
- [B] 046: 账户硬约束（max 5 只/max 10% 单股/max 20% 板块/min 30% 现金）
- [B] 047: 多策略资金分配（Kelly x 容量 x 相关性，取 min，半 Kelly）

### P1-4 游资席位分析
- [D][B] 048: hot_money_seats_preset.json 预设画像（拉萨天团/深圳游资/机构）
- [D][B] 049: 60 日龙虎榜聚合脚本（周更，约 18 次 API 调用）
- [B] 050: 行为突变检测（5 日增量 vs 60 日均值，偏差 > 30% 标注）
- [B] 051: hot_money_seat_risk 因子 -> 策略分修饰
- [B] 052: 龙虎榜 direct fetch（绕过 em_get 熔断，urllib 直连 datacenter）

### P1-5 资讯雷达上下文层
- [B] 053: akshare stock_news_em() 接入个股新闻主源
- [D][B] 054: sector_mapping.json 板块映射表（雷达赛道 -> 东财行业）
- [B] 055: 三层接入（板块资讯热度/催化上下文/风险雷达关键词命中）
- [B] 056: LLM 公告分类（走 chat 层，利好/利空/风险提示）

### P1-6 执行与成本模型
- [B] 057: 动态滑点模型（slippage = max(0.1%, 0.3% x order/daily)）
- [B] 058: 多持有期回测（T+1/T+2/T+3/T+5 收益输出）
- [B] 059: 收益分布分析（偏度/盈亏比/Sortino/VaR/CVaR/最大单笔亏损/最长连亏）
- [B] 060: 市场级熔断（指数跌幅 > 3% kill switch，tencent_quote 取指数）
- [B] 061: 策略容量估算（候选股日均成交额 x 2% x 持仓数）

### P1-7 统计严谨性 + 监控
- [B] 062: 因子共线性矩阵 + PCA 输出（docs/factor-correlation-matrix.md）
- [B] 063: 选择偏差验证（qualify=0 样本分位胜率对比）
- [B] 064: 压力测试三场景（千股跌停/流动性枯竭/连续熔断）
- [B] 065: 策略衰减监控（4 周滚动胜率告警）
- [B] 066: Regime 失效检测（反向因子失效 -> 触发重算）
- [B] 067: 性能归因（因子 beta 月度回归）

## Phase 2：非涨停类数据管道（可与 Phase 1 并行）

### P2-1 板块成分股
- [D][B] 068: 东财 clist fs=b:BKxxxx 拉成分股（分页 50/页）
- [D][B] 069: BaoStock 行业分类补充板块映射
- [D][B] 070: 缓存 sector_stocks.json

### P2-2 形态计算
- [B] 071: 相对强度（个股 5 日涨幅 - 板块 5 日涨幅）
- [B] 072: 均线多头排列（kline close -> MA5/MA10/MA20）
- [B] 073: 横盘形态（N 日振幅 < 阈值）
- [B] 074: MA5 接近度（低吸龙头用）
- [B] 075: 成交额/量比突破检测（平台突破用）

### P2-3 非涨停类策略
- [B] 076: 低吸龙头策略分 + 漏斗
- [B] 077: 反包战法策略分 + 漏斗
- [B] 078: 平台突破策略分 + 漏斗
- [B] 079: 龙头战法策略分 + 漏斗
- [B] 080: N字反击归入涨停类权重集

### P2-4 事件类因子
- [D][B] 081: akshare stock_ggcx_em() 大股东增减持接入
- [D][B] 082: akshare stock_yjyg_em() 业绩预告接入
- [D][B] 083: akshare stock_share_unlock_em() 解禁接入
- [B] 084: 公告分类（利好/利空/风险提示，LLM 辅助）
- [D][B] 085: ex_dividend_calendar.json 除权除息日历

## Phase 3：前端重构

### P3-1 盘前页面
- [F] 086: 全时段状态切换（15:00 复盘/18:00 深研/7:00 确认/9:15 竞价/9:30 锁定）
- [F] 087: L0 默认极简视图（一行一只候选）
- [F] 088: L1 摘要展开（板块阶段/日历/游资标签）
- [F] 089: L2 详情展开（完整因子/质量标准/资讯雷达）
- [F] 090: 策略分组 tab（按天气激活的策略组）
- [F] 091: 板块周期面板（阶段 + 强度排名 + 轮动 + 广度）
- [F] 092: 日历因子提示 + 节后红包确认展示

### P3-2 盘中页面
- [F] 093: 实时持仓 x 情绪联动（S063 继承）
- [F] 094: 条件场景 if-then + T+1 预判
- [F] 095: 日历因子标注（周五/节前降仓提示）
- [F] 096: 市场熔断提示（指数跌幅 > 3%）

### P3-3 盘后页面
- [F] 097: 当日候选 vs 实际表现命中率
- [F] 098: 策略分排名 vs 实际收益追踪
- [F] 099: 性能归因面板（因子 beta 贡献）
- [F] 100: 策略衰减面板（4 周滚动胜率）
- [F] 101: 压力测试面板
- [F] 102: A 股定律验证面板

### P3-4 因子详情子页
- [F] 103: 74 条因子子页框架（定义/公式/分布/相关性/分位胜率）
- [F] 104: 面包屑导航（首页 > 盘前 > 策略组 > 因子名）
- [F] 105: 返回按钮
- [F] 106: 候选卡片因子超链接 -> 子页跳转


### P3-5 问 AI（每页内置）
+- [F] 107: 问 AI 浮动按钮（每页面右下角，点击展开输入框）
+- [F] 108: 上下文自动组装（盘前/盘中/盘后/因子详情各自不同的上下文 JSON）
+- [B] 109: /api/chat 上下文注入（前端发送页面上下文 + 用户问题到已有 chat 层）
+- [F] 110: AI 回答展示面板（流式输出 + 免责声明"AI辅助分析，不构成投资建议"）
+- [F] 111: 上下文随页面切换自动更新（切页面时上下文跟着变）

## 测试

- [T] 107: 策略注册表单元测试（10 策略 + storm_reversal 注册/查询/天气匹配）
- [T] 108: 板块周期分析单元测试（3 日时序/阶段分类/修饰系数）
- [T] 109: 日历因子单元测试（周五/节前/节后红包/周四）
- [T] 110: 游资席位画像单元测试（预设/数据覆盖/行为突变检测）
- [T] 111: 双层 kill criteria 单元测试（策略级/组合级/恢复协议）
- [T] 112: 动态滑点模型单元测试（小/中/大资金场景）
- [T] 113: 优雅降级矩阵集成测试（各数据源不可用时的降级行为）

## §44 修订路径任务（新增，2026-08-16）

> §13.0 违反 + 无 validated alpha 后的修订路径（不回退 Phase 1-3，但验证优先 + 诚实标注）。

- [B] 114: ✅ 修 Phase 0e 框架 pass-logic 到 §44 合规（加随机基准 + lift、门槛对齐 §13.0 绝对 60，非 48 degradation）——落地：新表 `universe_returns`（§44 随机基准源，UNIQUE signal_date,code）+ `record_universe_returns` + `run_daily_forward_test` 主动记 universe codes + gate `winrate>=60 AND lift>=2.0 AND random_settled>0` + Wilson CI + is_exploratory；forward_test_records 不动（避免 dup）；18 测试过（含 §44 三关键测试：no_edge/no_universe/pass）。**真实数据 verdict 待 Windows 重跑 backfill 填 universe_returns**（spec §13 ① 设计口径已落）
- [B] 115: Phase 0e weather-adapted 重跑（接历史 sentiment_context 天气，测完整架构非退化版；当前 weather=None 是下界）
- [B] 116: 60 天 eastmoney_live 积累后复验 Phase 0b（within-day r）+ 0e（胜率 lift）——lift 破 2x + r 显著 → alpha 成立；否则确认无 edge
- [F] 117: 前端 getAStockTimeInfo 重构——改用后端 /api/workflow/status 源（单源 + 北京时区 + 节假日 is_trading_day），去本地重复（drift 源；非交易日 fix 见 591f536，节假日待重构补）
- [B] 118: 036 板块停留天数（sector_cycle 缺，需先定义"在榜"口径）
- [B] 119: classify_phase 边缘 case（today=0 + avg∈(0,3) 落"无历史"默认，应退潮-ish）
- [B] 120: save_alert 日期分歧（calendar-today vs last_trading-day，非交易日错位）——prod 改让 save_alert 按交易日历落 date
- [T] 121: spec→plan/tasks stale lint（`tools/spec_plan_stale_lint.py`）纳入回归/CI，防跨会话 drift

## 统计

| 类型 | 任务数 |
|---|---|
| [D] 数据 | 16 |
| [B] 后端 | 56 |
| [F] 前端 | 26 |
| [T] 测试 | 20 |
| **总计** | **118** |
