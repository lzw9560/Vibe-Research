# Spec: S044 — 候选池漏斗数据源补全（北向 + 板块联动 + 龙虎榜游资频次 + 公告类型化）

> 状态：已实现（R2 live 收尾 2026-08-10）——R1/R3/R4/R5/R6/R7 mock+部分 live 验证（2026-08-09）；R2 板块源 live 修复并通过（2026-08-10：行业源缺ut换 push2delay+ut、板块分页取全 496、级别后缀归一化、TTL 缓存防封、历史日防未来函数；600519=92372.0万/000001=18511.3万）。详见 `验收说明.md`
> 作者：Claude（grill-me 驱动）  日期：2026-08-09
> 关联：`../S002-打板工作流重构/spec.md`（P1 候选池漏斗，本 spec 打磨其 R2/R3 数据源）、`../S018-多源特征工程/spec.md`（R11 资金流特征组，fetcher TODO 待补）、`../S017-A股涨跌预测模型栈/spec.md`（short_sector 头预期消费这些特征）、`../S040-历史数据回填90天/spec.md`（回填脚本模式参考，不重叠——S040 是 gene_scores，本 spec 是 candidate_funnel）、`../S043-次日溢价率单因子分析/spec.md`（溢价口径参考，不重叠——S043 是单因子，本 spec 是漏斗整体增量贡献）、`../../CLAUDE.md` §1.1（弱合规，私人投研助理）、`../../AGENTS.md` 分级工作流
>
> 级别：**large**（碰 em_get 外部源 + 补 S018 fetcher TODO + 多文件 + 历史取数逻辑 + 未来函数防护；feature 分支 + grill 已完成 + playwright 验收）
> 分支：`feature/S044-候选池漏斗数据源补全`（off develop）
>
> grill 会话：本 spec 经 19 轮 grill-me 审讯锁定核心决策；Q4/Q17 因验证发现与 S018 R11 架构冲突而修正（原 A→B）；Q15 回测框架分支因验证发现 S040-S043 已覆盖而取消，本 spec 只做数据源补全。

---

## 1. 问题 / 目标

S002 P1 候选池漏斗（R1→R2→R3 + SELF）已实现，S023 已补可观测/真实数据/因子解耦，但 R2/R3 的 sources 实现与 spec §5.1 六类指标存在硬缺口：

| 类别 | spec §5.1 要求 | sources 实现 | 缺口 |
|---|---|---|---|
| 资金流-北向 | 北向净流入（分段） | `fund_flow.py:40` 写死 `"北向数据不可得"` | 🔴 完全缺失 |
| 资金流-龙虎榜 | 龙虎榜席位（机构 vs 游资） | `fund_flow.py:34` 只取 `institution_net` 标量 | 🟡 无游资席位接力频次 |
| 催化剂-板块联动 | 板块资金净流入 + 轮动速度 | `catalyst.py:30` 只取 concept 名字列表，`sector_flow=None` | 🔴 完全缺失 |
| 催化剂-公告 | 公告（预增/重组/回购）类型化 | `catalyst.py:20` 取了但不分类型，R3 只判 `bool(announcements)` | 🟡 无类型化过滤 |

**目标**：补全这四个数据源，让 R2/R3 筛选基于完整的资金面 + 催化剂信号；北向进 R2 过滤（非方向占位口径），让选出的标的 T+1 开盘有溢价的概率更高。最终目的（用户原话）：**最终选择的标的在次日要有溢价，否则一切筛选都是无用功**。

**不做**：
- 回测框架/90 天回填/次日溢价单因子分析——已被 S040/S041/S043 覆盖，本 spec 只做数据源补全，不重复
- 盘中信号/盘后结算——S002 P2/P3 范围
- 技术位（均线/BOLL/MACD）/补充参考信号（分时量比突变/大宗折溢价/筹码分布）——spec §5.1 标"辅助"/"补充参考"，优先级靠后

---

## 2. 背景

### 2.1 S018 R11 架构约束（grill Q4 修正后锁定）

`predict/features/fund_flow.py`（S018 R11）已声明 7 个资金流 FeatureSpec：`main_net_5d` / `dt_hot_money_relay`（龙虎榜游资接力频次）/ `seal_fund_strength` / `northbound_net_segmented`（北向分段）/ `margin_balance_change` / `sector_flow_rotation`（板块轮动）/ `block_trade_discount`。但 fetcher 是 TODO 未实现（注释"S008 迁移期间接线 live fetchers"，S008 已实现但 fetcher 未补）。

S017 short_sector 头预期消费这些特征（spec §79："资金面/热钱预期为 short_sector 的 top SHAP 特征组"）。

**架构决策**：candidate_funnel sources 不跨体系重复取数，而是先补 S018 fetcher TODO，candidate_funnel sources 调 fetcher。一处取数、两处消费（漏斗 + 预测栈），避免数据口径分裂。

### 2.2 弱合规边界（grill Q7 修正后锁定）

CLAUDE.md §1.1（2026-07-30）已将系统定位为**私人投研助理**，弱合规下"可主动给研判、推荐、买卖时机，无需强制中立措辞/不代客决策"。S002 spec §2 的"只出客观分档、方向结论交用户 AI"是 2026-07-28 旧口径（边界调整前），本 spec 按新口径执行——北向可进 R2 过滤。

### 2.3 避免未来函数（grill Q17 修正后锁定）

S018 `predict/features/registry.py` 已有 `list_for_stage(stage)` look-ahead 防护（s1/s2/s3/s4 + availability_offset）。candidate_funnel sources 复用这套防护，不自建——每个 source 调 fetcher 时按 stage 过滤，future-stage 数据标 missing。

**关键约束**：龙虎榜 `availability_offset=1`（T+1 盘后公布），R2 在 T-1 盘后跑——回溯 90 天时 T-1 的龙虎榜取不到，标 missing 保留，不因缺数据过滤掉。

### 2.4 历史取数（grill Q16 锁定）

补数据源时同步实现历史 date 参数支持。各 astock 接口对历史日期支持情况（已 live 探测，事实）：

| source | 接口 | 历史日期支持 | 替代方案 |
|---|---|---|---|
| activity | `tencent_quote(codes)` | ❌ 只取当日 | K 线 `kline(code, offset)` 复算换手/量比/成交额/振幅 |
| fund_flow | `stock_fund_flow_120d(code)` | ✅ 返回 120 日历史 | — |
| dragon_tiger | `dragon_tiger_board(code, trade_date, look_back)` | ✅ 支持传 trade_date | — |
| announcements | `announcements(code, limit=15)` | ❌ 只取最近 N 条 | limit 拉大 + 按日期本地截断 |
| block_trade | `block_trade(code, page_size)` | ❌ 只取最近 N 条 | limit 拉大 + 按日期截断 |
| industry_comparison（板块资金流） | `push2 clist` 端点 | ⚠️ 未探测历史参数 | 需 live 探测确认 |
| auction | `auction_screener.analyze(trade_date)` | ✅ 支持传 trade_date | — |
| kline | `kline(code, category, offset)` | ✅ 取历史 K 线 | — |

### 2.5 板块资金流向端点（grill Q11 已 live 探测，事实）

`push2.eastmoney.com/api/qt/clist/get`（fid=f62）已探测可用，返回板块级资金流：主力净流入（f62）/超大单（f66+f69）/大单（f72+f75）/中单（f78+f81）/小单（f84+f87）/成交额（f124）/领涨股（f204+f205）。

**事实**：只含明盘（主力资金流 5 档），**不含暗盘/大宗交易**。暗盘（大宗交易）是个股级（`astock.block_trade(code)`），东财不提供板块级大宗交易聚合。

---

## 3. 需求清单

### 数据源补全（4 项，串行实现，从轻到重）

- [ ] R1 **北向 fetcher**：在 `predict/features/fund_flow.py` 实现 `fetch_northbound(code, date)` live fetcher（补 S018 TODO）；走 `em_get` 拼东财个股北向端点（astock 无现成函数，需 live 探测端点）；声明 `stage="s1"` `availability_offset=1`；candidate_funnel `sources/fund_flow.py` 调它填 `northbound` 字段，替换写死的 `"北向数据不可得"`
- [ ] R2 **板块联动 fetcher**：在 `predict/features/fund_flow.py` 实现 `fetch_sector_flow(code, date)`（补 S018 TODO）；走 `push2 clist` 端点取个股所属板块的主力净流入（f62）；声明 `stage="s1"`；candidate_funnel `sources/catalyst.py` 调它填 `sector_flow` 字段，替换 `None`
- [ ] R3 **公告类型化**：candidate_funnel `sources/catalyst.py` 加公告类型分类逻辑（预增/重组/回购/其他）；R3 过滤 `_filter_r3` 支持按公告类型筛（当前只判 `bool(announcements)`）
- [ ] R4 **龙虎榜游资席位接力频次**：在 `predict/features/fund_flow.py` 实现 `fetch_dt_hot_money_relay(code, date)`（补 S018 TODO）；走 `astock.dragon_tiger_board(code, trade_date, look_back)` 取席位明细（`BillboardDetail.operate_dept_name`）；聚合游资席位接力频次（多日频次，不依赖个体席位标签——S018 R11 明确"个体席位标签 alpha 已衰减，只用聚合频次"）；声明 `stage="s1"` `availability_offset=1`；candidate_funnel `sources/fund_flow.py` 调它填新字段 `dragon_tiger_hot_money_relay`

### R2 过滤扩展

- [ ] R5 **北向进 R2 过滤（非方向占位口径）**：`BaseThreshold` 加 `northbound_abs_min: float` 字段（默认值待 live 探测确定）；`_filter_r2` 加 `if nb is not None and abs(nb) < eff.northbound_abs_min: filter`；北向 missing 标 missing 保留，不因缺数据过滤掉；非方向口径是占位——先用绝对值筛掉无北向动作的票，方向判断留给后续数据源（主力净流/龙虎榜）组合判断
- [ ] R6 **R2 过滤的 stage 防护**：`run_funnel` 调各 source 前，按当前 stage（R2 在 s1=T-1 盘后）过滤 future-stage 数据；future-stage（如龙虎榜 availability_offset=1）标 missing 不用，避免未来函数

### 历史取数支持

- [ ] R7 **统一历史 date 参数**：candidate_funnel 各 source 的 `fetch_xxx(codes, date)` 统一支持历史 date 参数；当日走实时接口（tencent_quote/auction_screener），历史走替代逻辑（kline 复算活跃度 / 接口历史参数 / limit 拉大+日期截断）；90 天回溯用统一接口
- [ ] R8 **板块资金流端点历史参数探测**：live 探测 `push2 clist` 端点是否支持历史日期参数；不支持则标 missing 或找替代

### 诊断卡拼接

- [ ] R9 **IndicatorSet 加游资频次字段**：`candidate_funnel/models.py` 的 `IndicatorSet` 加 `dragon_tiger_hot_money_relay: float | None` 字段（向后兼容，Optional 默认 None）；`diagnosis.py build_indicator_set` 拼接新字段

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/predict/features/fund_flow.py` | R1/R2/R4：实现 `fetch_northbound` / `fetch_sector_flow` / `fetch_dt_hot_money_relay` 三个 live fetcher（补 S018 TODO） |
| `backend/candidate_funnel/sources/fund_flow.py` | R1/R4：调 fetcher 填 `northbound` + `dragon_tiger_hot_money_relay`，替换写死值 |
| `backend/candidate_funnel/sources/catalyst.py` | R2/R3：调 fetcher 填 `sector_flow`；加公告类型分类逻辑 |
| `backend/candidate_funnel/funnel.py` | R3/R5/R6：`_filter_r3` 支持按公告类型筛；`_filter_r2` 加北向过滤；`run_funnel` 加 stage 防护 |
| `backend/candidate_funnel/thresholds.py` | R5：`BaseThreshold` 加 `northbound_abs_min` 字段；`PHASE_ADJUSTMENTS` 视情况加北向档位 |
| `backend/candidate_funnel/models.py` | R9：`IndicatorSet` 加 `dragon_tiger_hot_money_relay` 字段 |
| `backend/candidate_funnel/diagnosis.py` | R9：`build_indicator_set` 拼接新字段 |
| `backend/predict/features/registry.py` | R6：确认 `list_for_stage` 可被 candidate_funnel sources 复用（如需扩展接口） |

---

## 5. 设计方案

### D1 实现顺序（grill Q5 锁定）

串行实现，从轻到重：北向 → 板块联动 → 公告类型化 → 龙虎榜游资频次。每步独立 commit + 单测验证。理由：① 依赖深度递增——北向/板块联动只需改 sources + diagnosis（模型字段已存在），公告类型化要加 R3 过滤逻辑，游资频次要改 models.py 加字段 + 新取数 + 聚合；② fund_flow.py 内部北向和游资频次写同一文件，不能真并行。

### D2 北向进 R2 过滤口径（grill Q7-Q10 锁定）

非方向占位口径：北向净额绝对值 > X 万才保留，不分正负。理由：① A 股短线北向正负对次日走势有统计指向性（公开经验，**具体胜率未在本项目回测验证，标注为推测**——回测验证由 S041/S043 承担）；② 非方向口径是占位——先用绝对值筛掉无北向动作的票，方向判断留给后续数据源（主力净流、龙虎榜）组合判断；③ 阈值 X 默认值待 live 探测确定（常见值几百到几千万，**这是实现期需 live 探测确定的，不是 spec 期能定的**）。

### D3 避免未来函数（grill Q17 修正后锁定）

复用 S018 `predict/features/registry.py` 的 `list_for_stage(stage)` 防护。每个 source fetcher声明 `stage` + `availability_offset`，candidate_funnel `run_funnel` 调 fetcher 前按当前 stage 过滤。关键：龙虎榜 `availability_offset=1`（T+1 盘后公布），R2 在 T-1 盘后跑——回溯 90 天时 T-1 的龙虎榜取不到，标 missing 保留。

### D4 历史取数（grill Q16 锁定）

补数据源时同步实现历史 date 参数支持。接口设计：`fetch_xxx(codes, date)` 统一支持 date 参数；当日走实时接口，历史走替代逻辑（kline 复算活跃度 / 接口历史参数 / limit 拉大+日期截断）。90 天回溯用统一接口——回溯重建脚本可参考 S040 的 `backfill_history.py` 模式，但数据源是 candidate_funnel R3 定稿池，不是 gene_scores。

### D5 板块联动数据层（grill Q11 锁定）

取个股所属板块的资金净流入（明盘主力），不取暗盘。理由：① 事实核实——东财板块资金流向端点只含明盘（主力 5 档：超大/大/中/小单净流入），不含暗盘/大宗交易；② 暗盘（大宗交易）是个股级数据（`astock.block_trade`），东财不提供板块级大宗交易聚合；③ 暗盘个股级大宗交易折价率归入 spec §5.1 "补充参考信号"，不在本 spec 范围。

**未决（实现期定）**：个股属于多个板块（申万行业 + 东财概念），取哪个口径——申万一级行业（稳定但粗）还是东财概念板块（细但变化快）。

### D6 不建回测框架（grill Q18 验证后取消）

原 grill Q14-Q15 锁定的"先建回测框架验证每个数据源增量贡献"+"90 天回溯重建"已被 S040/S041/S043 覆盖：
- S040：90 天历史数据回填（gene_scores 体系，不碰 candidate_funnel）
- S041：回测定时任务 + 趋势看板
- S043：次日溢价率单因子分析

本 spec 只做数据源补全，不重复建回测框架。数据源补完后，S041/S043 的回测引擎可消费补全后的 R3 定稿池验证增量贡献。

---

## 6. 验收标准

- [ ] A1 北向：`fund_flow.py` 不再写死 `"北向数据不可得"`；live 取到个股盘后北向净流入；missing 时标原因保留
- [ ] A2 板块联动：`catalyst.py` 的 `sector_flow` 不再恒为 `None`；live 取到个股所属板块主力净流入
- [ ] A3 公告类型化：R3 过滤支持按公告类型筛（预增/重组/回购）；诊断卡展示公告类型
- [ ] A4 龙虎榜游资频次：`IndicatorSet.dragon_tiger_hot_money_relay` 字段有值；聚合频次不依赖个体席位标签
- [ ] A5 北向进 R2 过滤：`BaseThreshold` 有 `northbound_abs_min` 字段；`_filter_r2` 用绝对值过滤；missing 保留不过滤
- [ ] A6 避免未来函数：sources 按 stage 过滤；龙虎榜在 R2（s1）回溯时标 missing 不用；`list_for_stage` 防护生效
- [ ] A7 历史取数：各 source `fetch_xxx(codes, date)` 支持历史 date；90 天回溯用统一接口（activity 走 kline 复算）
- [ ] A8 S018 fetcher 补债：`predict/features/fund_flow.py` 三个 TODO fetcher 实现；S017 short_sector 头可消费
- [ ] A9 合规：弱合规下北向进过滤无障碍；输出挂轻量风险提醒「历史统计特征，市场有风险」；过滤口径标注"基于交易经验，未经历史回测验证，胜率提升是预期而非事实"（回测验证由 S041/S043 承担）
- [ ] A10 `pytest -m "not live"` 全过；新增 source 单测覆盖
- [ ] A11 新增东财端点（个股北向 / 板块资金流）走 `em_get()` 限流，不裸调 requests

---

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机属系统能力（2026-07-30 新口径，CLAUDE.md §1.1）；北向进 R2 过滤无合规障碍；输出挂轻量风险提醒
- [ ] 判断可复现：北向/板块/龙虎榜取数走 `em_get` + `astock` 既有接口，规则可查；过滤口径标注未经回测验证
- [x] 涨停四池/连板股榜个股属公开榜单客观事实（设计选择，可呈现 code/name）
- [x] 用户私有数据（持仓/研报/key）未进 git
- [ ] 新增东财端点（个股北向 / 板块资金流）走 `em_get()` 限流——实现期确认

---

## 8. 测试计划

- pytest -m "not live"：`candidate_funnel/tests/` + `predict/features/tests/` 全过
- 新增 source 单测：北向 fetcher / 板块联动 fetcher / 公告类型化 / 龙虎榜游资频次聚合
- live 冒烟：起 uvicorn:8900 → `GET /api/workflow/funnel/layers` 各层数据非 missing → 北向/板块/龙虎榜字段有值
- 历史取数冒烟：`run_funnel("pre_market", "2026-07-01")` 用历史 date 跑，activity 走 kline 复算，北向/板块/龙虎榜按 stage 过滤
- 避免未来函数验证：回溯 T-1 跑 R2，龙虎榜（availability_offset=1）标 missing 保留，不引入未来信息

---

## 9. 风险与回滚

- **个股北向端点未探测**：astock 无现成北向函数，需用 `em_get` 拼东财个股北向端点。**未 live 探测确认端点可用**——如果东财已彻底下线个股北向端点，R1 不可行，需回退到标 missing 或改取全市场北向汇总。**实现期第一步 live 探测端点**。
- **板块资金流历史参数未探测**：`push2 clist` 端点是否支持历史日期参数未探测。不支持则 90 天回溯时板块联动标 missing。
- **阈值 X 默认值未验证**：`northbound_abs_min` 默认值待 live 探测确定，无回测数据支撑。标注为经验假设。
- **scope 蔓延**：本 spec 已从"数据源补全"扩展到"补 S018 fetcher TODO + 历史取数 + 未来函数防护"——这是给 S018 还欠债，属于补既有 spec 的欠债，不是新工作量。
- **回滚**：candidate_funnel sources 改动向后兼容（Optional 字段默认 None）；S018 fetcher 是补 TODO，删除即回滚；北向过滤阈值默认 0 等于不过滤。
