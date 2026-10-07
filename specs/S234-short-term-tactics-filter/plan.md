# S234 短线战法排雷过滤器 - 技术方案 (plan.md)

> spec.md 已建（2026-10-07）。本 plan 是技术方案（怎么做：取舍/备选为何不选/模块拆分/依赖序/数据流）。

## 核心决策：复用现有不重造（DRY/YAGNI）

排雷过滤器**不新建选股引擎**，而是复用项目已有基建：

1. **复用 `pre_market_workflow.PreMarketWorkflow.run()`**（已有：涨停池→候选池→8战法→仓位→P2 仓位闸+龙虎榜黑名单 DragonTigerSeatFilter）
2. **复用 `_market_phase` 五状态机**（冰点/普通/活跃/亢奋/红期→cap 1.0/0.5/0.2）
3. **复用 `strategies/funnel/`** 漏斗选股（aggregation + non_limitup_funnel）
4. **复用 `gene_scores.zt_count_250d`**（股性活跃度）+ `code_industry`（行业映射 5896 行）
5. **复用 `dragon_tiger_history.db`**（1 年席位，资金流梯度 inst_dominant）
6. **复用 `baostock_kline_cache.db`**（5248 股 kline）+ `zt_history.db`（涨停+连板）

**commander 定位 = 调度层 + 排雷输出层**，不重造选股。

## 模块拆分

### 新建：`backend/tools/short_term_tactics_filter.py`
核心排雷脚本，输出 JSON。

**输入**：候选股票池（从 pre_market_workflow / funnel 取）+ 战法类型（战法1早盘 9:25 / 战法2尾盘 14:50）

**第一层财务硬过滤（一票否决，sound）**：
- 流通市值 30-150 亿（baostock kline ltsz / gene_scores）
- 剔除 ST+*ST+退市（astock isST + 6 位代码前缀）
- 资产负债率 >85% 或非标意见（hithink 财报，不全则降级用 baostock isST+市值+成交额）
- 5 日均成交 >1.5 亿（baostock amount）

**第二层情绪因子匹配（标 falsified verdict，不假装 alpha）**：
- 战法1（9:25 早盘弱转强）：竞价量比>3.5 / 竞价成交额占比>8% / 高开 2-5%
  - 每因子旁标：`verdict: "falsified - consecutive_relay direction-confirmed magnitude-uncertain (-0.024%~-0.70%)"`
  - chasing 维度（grilling 发现）：gap>=3% 强烈回避（-1.60%），gap<-1% 无 edge 非输家
- 战法2（14:50 尾盘锁定）：换手 12-22% / 收盘>=99.5% 日内最高+站稳 VWAP / 同板块 2+涨停 / 龙虎榜席位>8%
  - 每因子旁标：`verdict: "falsified - freeze_5min/seal_timing 假 edge（survivorship+entry涨停价+exit一字 over-credit）"`
  - 资金流梯度（grilling）：inst_dominant +0.405% gross 但 stop -0.286% 无显著性（标 exploratory）

**输出 JSON**（借鉴用户安全审查模板）：
```json
{
  "is_passed": true/false,
  "risk_level": "None/Low/High",
  "hit_rules": ["市值<30亿", "资产负债率>85%", ...],
  "reason": "逐项理由（附 falsified verdict）",
  "safe_action": "Pass(观察池)/Block(剔除)/Refuse(黑名单)",
  "verdicts": {"战法1": "direction-confirmed falsified", "战法2": "假edge falsified"},
  "tactics_meta": {"chasing_gap": ">=3%回避", "inst_dominant": "exploratory无显著性"}
}
```

**不编主力意图**（§1.2 工程底线）：只基于可观测量价/席位，"主力意图"类话术标"主观推断"或剔除。

### 接入：`commander_runner.py`
- 沸点期（score>70）调用 `short_term_tactics_filter`
- 常态/冰点期不调用（红利低波 512890 / 中线）

### 双时段 cron：`scheduled_tasks`
- 09:15 `task_type='sentiment_commander_morning'`（情绪诊断+仓位+飞书）
- 14:50 `task_type='sentiment_commander_close'`（尾盘排雷+飞书）
- 复用现有 `premarket_auction_notify`（9:25）+ `daily_ai_summary`（15:30）框架

## 数据流

```
baostock_kline_cache (5248股)      ─┐
gene_scores (zt_count_250d+行业)   ─┤
zt_history (涨停+连板+fbt首封)     ─┤
dragon_tiger_history (1年席位)     ─┼─→ short_term_tactics_filter ─→ JSON 输出
hithink (财报/股东户数/资产负债率) ─┤                              ↓
astock (isST/市值)                 ─┘                      commander_runner ─→ 飞书
                                                              ↑
                              fetch_market_sentiment_metrics (情绪诊断判断沸点)
```

## 依赖序

1. `short_term_tactics_filter.py`（核心，新建）
2. `commander_runner.py` 接入（沸点期调用排雷）
3. `scheduled_tasks` 双时段 cron（09:15 + 14:50）
4. pytest 单元测试（第一层+第二层+JSON 输出）

## 备选为何不选

- **重造选股引擎**：❌ 项目已有 pre_market_workflow + funnel + _market_phase，重造违反 DRY（commander-automation-wired 教训）
- **Tushare/券商 API**：❌ 项目用 baostock+em_get+hithink+akshare 已覆盖（5248 股+1 年 LHB+8188 股性），换平台违反 YAGNI
- **全自动下单**：❌ 项目无券商接口（PaperPortfolio），只能弹窗+飞书。反而 sound——避全自动滑点+反向收割（陷阱2+陷阱3）
- **假装战法翻正**：❌ grilling 4 agent 共识 falsification holds，排雷标 falsified 不翻 verdict（verdict 外推禁令）

## 风险 + 降级

- **资产负债率数据 hithink 不全** → 降级用 baostock isST + 市值 + 成交额（第一层够用）
- **竞价数据（9:25 量比）项目无实时** → 用 zt_history fbt（首封时间）代理或标"待实时数据"
- **dragon_tiger 仅 1 年 underpowered**（grilling 发现）→ 资金流梯度标 exploratory 无显著性
- **-1.66% magnitude 不可复现**（grilling）→ 排雷标"direction-confirmed magnitude-uncertain -0.024%~-0.70%"，不写 -1.66%

## 关联 spec/memory

- spec: `specs/S234-short-term-tactics-filter/spec.md`
- [[short-term-tactics-knowledge-2026-10-07]]（战法知识库+冲突标注）
- [[consecutive-relay-grilling-2026-10-07]]（战法1 magnitude 修正）
- [[quant-traps-four-pitfalls-2026-10-07]]（R27-R30）
- [[commander-automation-wired-2026-10-07]]（复用现有基建清单）
