# Spec: S232 — T+1 涨停预测 watchlist 生成器

> 状态：草案 | 日期：2026-09-30 | 分级：medium（观察池工具非 edge 基建，接线为主）
> 作者：claude
> 关联：12-agent workflow `t1-limitup-forecast-signals`（6 专家 + 6 对抗）、[[consecutive-relay-falsified-2026-09-23]]、[[edge-exhaustive-5batch-2026-09-28]]、[[v6-systematic-blindspot-2026-09-27]]（claim≠runtime 病）

## 1. 问题 / 目标

用户问"T+1 要涨停的标的，T 日没有交易信号吗"。12-agent workflow（6 专家视角 + 6 对抗验证）结论：
- **T 日有真信号**：换手率>20% + 量比>2.0 → lift 5.28x（CI[4.38,6.35]x 干净排除 1.0，n=2428，统计显著非噪声）
- **但交易 EV 负**：net -0.87%/笔（t=-4.48 显著负）——95.6% 不涨停的票亏 -1.16% 淹没 4.4% 涨停的 +12.48%
- **第 5 根因"稀有事件-输家拖累"**：base rate 0.822% 太低，5x 集中度=4.4% 命中 < 8.5% 盈亏平衡
- **信号是波动率代理非方向预判**：pct<-5 大跌 lift 2.06x vs pct 8-9.3 大涨 lift 2.57x（两端都预判涨停）

**目标**：建 T+1 涨停预测 watchlist 生成器——T 日筛 turn>20%+vr5>2 未涨停股作**观察池**（非买入信号）+ 二次确认字段（T+1 竞价/封单）累积 60 天验证 + 飞书通知 + cron 每日触发。

**定位声明（最高优先级）**：这是**观察池/研究工具，非交易信号**。信号 5.28x lift 真实但 EV -0.87% 负，blanket 买入亏。作 watchlist 生成器 + 二次确认累积验证，试图把"负 EV blanket"转"正 EV 择时"。措辞锁定"watchlist/观察池"非"买入/信号"。不输出买卖标的、不自动下单、不进 sizing 承重墙。

## 2. 背景

- consecutive_relay 已 definitive falsified（真 edge -1.66% p=1.0 n_test 89/65≥60）
- 5 批穷尽 300+ 候选 0 alpha（严口径）
- 12-agent workflow（2026-09-30）确认 T+1 涨停预测信号 5.28x lift 真但 EV 负
- baostock_kline_cache.db 5248 codes 日线（含 turn/volume/pctChg/isST）+ zt_history.db 315 天涨停池——数据源全已建
- agent 留探索脚本 `tools/explore_t1_zt_from_tday.py`（数据读法 + Wilson CI 参考实现）

## 3. 需求清单

- [ ] R1 `generate_t1_watchlist(date)` 纯函数：筛 T 日有 kline + NOT 在 zt_history[T] + turn>20% + vr5>2 → watchlist dict
- [ ] R2 诚实标注：edge_status="weak-signal-EV-negative" + honest_caveat（5.28x lift 真但 EV 负 + 第 5 根因 + 观察池非买入信号）
- [ ] R3 二次确认字段预留：stocks 含 t1_zt/t1_auction/t1_seal_time/confirmed，初始 None，T+1 收盘后回填 t1_zt
- [ ] R4 `render_watchlist_report(watchlist)` 人话报告：信号 + 命中率 + 诚实标注 + 观察池清单
- [ ] R5 cron executor `t1_watchlist_generate(payload)`：15:10 收盘后触发（T 日全量数据确认）
- [ ] R6 飞书通知：推当日 watchlist + 诚实标注（非交易信号）
- [ ] R7 持久化：`.vibe-research/t1_forecast/{date}_watchlist.json`
- [ ] R8 router GET /api/t1-forecast/watchlist?date=X → watchlist
- [ ] R9 前端 /t1-forecast 路由 + WatchlistCard 组件

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/t1_forecast.py` | **新增**：generate_t1_watchlist + render_watchlist_report 纯函数 |
| `backend/scheduler/executors/t1_forecast.py` | **新增**：t1_watchlist_generate cron executor |
| `backend/scheduler/executors/__init__.py` | 注册 executor（_executors dict + _execute 方法）|
| `backend/scheduler/seed.py` | 新增 cron seed（15 10 * * 0-4 收盘后）|
| `backend/routers/t1_forecast.py` | **新增**：GET /api/t1-forecast/watchlist |
| `backend/app.py` | include_router |
| `backend/tests/test_t1_forecast.py` | **新增**：TDD 6 test |
| `backend/tests/test_task_executor.py` | _EXPECTED_TASK_TYPES 加 t1_watchlist_generate |
| `backend/tests/test_regression_bugs.py` | expected set 加 t1_watchlist_generate |
| `frontend/src/lib/api.ts` | t1ForecastWatchlist method |
| `frontend/src/lib/query/t1_forecast.ts` | **新增**：useT1Watchlist hook |
| `frontend/src/lib/query/index.ts` | export |
| `frontend/src/components/t1-forecast/WatchlistCard.tsx` | **新增**：看板组件 |
| `frontend/src/pages/t1-forecast/T1ForecastPage.tsx` | **新增**：页面 |
| `frontend/src/router.tsx` | /t1-forecast 路由 |

**复用现有（0 改动，只读）**：baostock_kline_cache.db + zt_history.db（SQL 读）+ signals.py（_send_text_notification）+ cron_fire_audit（@fire_receipt）+ vr_paths（resolve_data_dir/prev_trading_date_str）

## 5. 设计方案

### 关键设计决策（深度讨论）

**决策1 信号选择**：用 turn>20% + vr5>2（5.28x lift 最强）。对抗 agent 3 戳破 vr5>2 增量仅 1.02x（turn>20% 单独 5.18x，加 vr5>2 后 5.28x），但保留 vr5>2 因：① n=2428 vs 9629 信噪比更好（日均 ~8 只可观察 vs ~40 只太宽）② 略提升命中率方向对。诚实记录：5.28x 几乎全来自 turn>20% 单条件，vr5>2 是辅助筛非主因。

**决策2 watchlist vs 买入信号**：workflow 12 agent 一致 EV -0.87% 负，**作观察池非买入信号**。不进 sizing 承重墙（违 risk_rules.py:565"⛔ 不碰 final_size"），不触发 journal.add_trade，不自动下单。前端措辞"watchlist/观察池"。

**决策3 二次确认累积**：stocks 预留 t1_auction（竞价低开/高开/平开）+ t1_seal_time（封单时间）+ confirmed 字段，初始 None。T+1 收盘后回填 t1_zt（是否涨停）。累积 60 天后跑命中率验证：不同二次确认条件的命中率 vs blanket 4.34%。这是把"负 EV blanket"转"正 EV 择时"的唯一出路——但二次确认信号未验证（auction-t0-reverse 10 天 underpowered），累积验证中。

**决策4 诚实标注**：edge_status="weak-signal-EV-negative"（非 validated 非 pure-practice），前端 + 飞书 + 持久化全标。避 V1 假 edge 覆辙（用户误当 edge 重仓）。honest_caveat 含"5.28x lift 真但 EV -0.87% 负 + 第 5 根因 + 观察池非买入信号"。

### 数据流

```
数据源层（全已建，0 新数据源）
  baostock_kline_cache.db + zt_history.db
  ↓
generate_t1_watchlist(date)
  筛 T 日有 kline + NOT zt_history[T] + turn>20% + vr5>2
  输出 watchlist{date, signal, lift, hit_rate, edge_status, honest_caveat, stocks[]}
  持久化 .vibe-research/t1_forecast/{date}_watchlist.json
  ↓
cron 15:10 收盘后触发 + 飞书通知（watchlist + 诚实标注）
  ↓
前端 /t1-forecast 看板展示 watchlist（观察池非买入信号）
  ↓
T+1 收盘后（后续迭代）：回填 t1_zt + t1_auction + t1_seal_time
  累积 60 天后跑命中率验证二次确认信号
```

## 6. 验收标准

- [ ] A1 generate_t1_watchlist 返 watchlist{date, signal, lift, edge_status, honest_caveat, stocks[]}
- [ ] A2 筛选正确：T 日有 kline + NOT zt_history[T] + turn>20% + vr5>2
- [ ] A3 排除 ST 股
- [ ] A4 edge_status="weak-signal-EV-negative" + honest_caveat 含"EV 负/观察池"
- [ ] A5 二次确认字段预留（t1_zt/t1_auction/t1_seal_time/confirmed 初始 None）
- [ ] A6 render_watchlist_report 人话报告含诚实标注 + 观察池清单
- [ ] A7 cron t1_watchlist_generate 15:10 收盘后触发
- [ ] A8 飞书通知发送（watchlist + 诚实标注非交易信号）
- [ ] A9 持久化 {date}_watchlist.json
- [ ] A10 router GET /api/t1-forecast/watchlist 返 watchlist
- [ ] A11 前端 /t1-forecast 路由 + WatchlistCard 展示
- [ ] A12 pytest + full suite green（_EXPECTED_TASK_TYPES 加 t1_watchlist_generate）

## 7. 合规与工程底线自查

- [ ] 研判/推荐属系统能力（§1.1），用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」
- [ ] 判断可复现：复用现有数据源（baostock_kline + zt_history），禁臆造/心算
- [ ] 用户私有数据未进 git（.vibe-research/t1_forecast/ gitignored）
- [ ] 无新增东财端点（不涉 em_get）
- [ ] **定位诚实**：观察池/研究工具非交易信号——5.28x lift 真但 EV 负，不进 sizing 承重墙，不触发 journal.add_trade，措辞"watchlist/观察池"非"买入/信号"

## 7.1 §44 v3 anti-fake-edge sanity

- [ ] R1 entry close 涨停价审：本 spec **排除 T 日涨停股**（zt_history[T]），entry=T 日 close 市场价非涨停价——天生避 V1 entry 溢价
- [ ] R3 exit 一字涨停审：不涉及 exit（观察池非交易）
- [ ] R4 涨停 vs 未涨停对比：本 spec 是 T 日未涨停全样本 vs T+1 涨停——已做对比（5.28x lift vs 0.822% base）
- [ ] R2 窗口语义标注：措辞"watchlist/观察池"非"买入信号"，edge_status="weak-signal-EV-negative"（非 validated）
- [ ] A5 回归测试：edge_status="weak-signal-EV-negative" + honest_caveat 含 EV 负

## 8. 测试计划

- `pytest tests/test_t1_forecast.py`（新增）：
  - _vol_ratio_5 基础逻辑 + 前置不足 + 零量
  - generate_t1_watchlist 结构 + 筛选（turn>20+vr5>2）+ 排除涨停股 + 排除 ST
  - edge_status = weak-signal-EV-negative
  - honest_caveat 含"EV"/"观察池"
  - 二次确认字段初始 None
  - render_watchlist_report 含诚实标注
- `pytest -m "not live"` full suite green

## 9. 风险与回滚

- **爆炸半径小**：新增 2 文件（纯函数 + cron executor）+ 接线（executors dict + seed + router + 前端），复用现有，不改现有代码
- **回滚**：删 t1_forecast.py + executors 注册 + seed + 目录 + 前端
- **观察池非交易**：EV -0.87% 负已标注，不进 sizing 承重墙，不触发 journal.add_trade——用户误当 edge 重仓风险靠诚实标注 + 措辞锁定
- **二次确认未验证**：t1_auction/t1_seal_time 字段预留，累积 60 天验证前不指导交易
