# Spec 里程碑索引

> 160+ 个 spec 按里程碑分组归档。已完成的里程碑标 ✅，进行中标 🔄。
> 旧 spec 不删——保留作历史决策记录。被替代的 spec 在"备注"列标 → 后继 spec。
> 归档目录：`specs/archive/mN-xxx/`。活跃 spec 留 `specs/` 根目录。

---

## M0 地基（S001-S020）✅ 已完成 2026-07-28 ~ 2026-08-01

系统重写：契约层/数据层/调度收口/UI 重设计/测试网/ML 预测栈/多源特征/宏观/另类数据。

`specs/archive/m0-foundation/` · 20 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S001 | chat env llm config 修复 | ✅ | |
| S002 | 打板工作流重构（候选池漏斗+诊断卡） | ✅ | → S086 统一架构 |
| S003 | API bugfix 批次 | ✅ | |
| S004 | 漏斗 run_funnel 性能优化 | ✅ | |
| S005 | 中长线价值选股漏斗 | ✅ | |
| S006 | 系统重写纲领（长分支） | ✅ | 含 S007-S014 子 spec |
| S007 | 契约层（数据模型+回归基线） | ✅ | |
| S008 | 后端数据层迁移 | ✅ | |
| S009 | 前后端类型同步 | ✅ | → S013 |
| S010 | AI 工具注册表 + SYSTEM_PROMPT | ✅ | |
| S011 | 调度收口 | ✅ | → S031/S032 第二轮 |
| S012 | 工作流标灰 | ✅ | → S036 修订版 |
| S013 | 前端数据层（client+Query+懒加载） | ✅ | |
| S014 | 前端 UI 重设计 | ✅ | |
| S015 | 配置与基础设施 | ✅ | |
| S016 | 测试网（覆盖率+IO 录制+CI） | ✅ | |
| S017 | A 股涨跌预测模型栈 | ✅ | |
| S018 | 多源特征工程 | ✅ | |
| S019 | 宏观 Fred API | ✅ | |
| S020 | worldmonitor 决策因子接入 | ✅ | |

---

## M1 工作流（S022-S048）✅ 已完成 2026-08-02 ~ 2026-08-10

漏斗/拓扑/状态机/结算/标灰/回测/持仓/因子补全/空写防护/权重校准/工作流打磨。

`specs/archive/m1-workflow/` · 26 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S022 | 熔断器 health 读路径修复 | ✅ | |
| S023 | 漏斗可用性与因子解耦 | ✅ | 含 S026 并入 |
| S024 | 拓扑展示 | ✅ | |
| S025 | 补前端入口 | ✅ | |
| S026 | pre-market 异步化 | ✅ | 并入 S023 |
| S028 | limitup-screener 修复 | ✅ | |
| S029 | GeneScreener 接通 | ✅ | |
| S030 | 盘前简报多层化 | 🗑️废弃 | → S031 合并重写 |
| S031 | 调度收口+盘前多层+战法回测 | ✅ | |
| S032 | 调度收口第二轮 | ✅ | |
| S033 | 状态机前端呈现 | ✅ | |
| S034 | 结算接线（SettlementEngine） | ✅ | |
| S035 | ai_proxy 删除 | ✅ | |
| S036 | 工作流标灰（S012 修订版） | ✅ | |
| S037 | gene DB 路径迁移 | ✅ | |
| S038 | 持仓市价自动结算 | ✅ | |
| S039 | StockDeep 接线 | ✅ | |
| S040 | 历史数据回填 90 天 | ✅ | |
| S041 | 回测定时任务+趋势看板 | ✅ | |
| S042 | 统一持仓建议引擎 | ✅ | |
| S043 | 次日溢价率单因子分析 | ✅ | |
| S044 | 候选池漏斗数据源补全 | ✅ | |
| S045 | 漏斗层得分排序筛选 | ✅ | |
| S046 | fallback 空写防护 | ✅ | |
| S047 | 基因分权重回测校准 | ✅ | |
| S048 | 工作流打磨 | ✅ | |

---

## M2 闭环（S049-S065）✅ 已完成 2026-08-10 ~ 2026-08-13

行动闭环/行为对照/因子IC/验证卡/预测跟踪/情绪管线/盯盘教练/天气持久化。

`specs/archive/m2-closure/` · 17 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S049 | 盘前简报漏斗重构与诊断修正 | ✅ | |
| S050 | W0 行动闭环（票根+影子对照+独立性） | ✅ | |
| S051 | 基因筛选体验批 | ✅ | |
| S052 | 回测快照回填与缺口补跑 | ✅ | |
| S053 | 炸板后溢价因子修复 | ✅ | |
| S054 | W0 工作流闭环呈现（盘后三问+行为卡） | ✅ | |
| S055 | 盘中封单时序采集与炸板预警 | ✅ | |
| S056 | 天气熔断三铁律补全 | ✅ | |
| S057 | 漏斗八项标准硬约束封顶 | ✅ | |
| S058 | 战法双层卡片层与天气适配 | ✅ | |
| S059 | 因子 IC 评估 | ✅ | |
| S060 | 明日验证条件对账卡 | ✅ | |
| S061 | 预测跟踪与自动验证 | ✅ | |
| S062 | 战法卡内容填充（反包/龙头） | ✅ | |
| S063 | 情绪管线贯通与盘中辅助决策 | ✅ | |
| S064 | 盯盘教练 MVP | ✅ | |
| S065 | weather_history 持久化 | ✅ | |

---

## M3 战法统一（S066-S086）✅ 已完成 2026-08-13 ~ 2026-08-21

策略漏斗/性能/首板流/战法 pipeline/选股池分层/暴风雨/SQLite 并发/echarts。

`specs/archive/m3-strategy/` · 19 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S066 | 策略特定漏斗架构重构 | ✅ | |
| S067 | advisory 端点性能优化 | ✅ | |
| S068 | 工作流触发与结算正确性 | ✅ | |
| S069 | 每日 forward_test 管道 | ✅ | |
| S070 | intraday 采集管管 | ✅ | |
| S071 | 盘前选股谨慎部署 | ✅ | |
| S072 | 涨停叉 pipeline 诚实可观测 | ✅ | |
| S074 | market_phase 统一判定 | ❌废弃 | backend 未实现（workflow.py:800 _not_implemented），被 S092 绕过，2026-09-18 frozen → _abandoned/ |
| S075 | 首板流 | ✅ | |
| S076 | 首板流盘中多源行情实测 | ✅ | |
| S077 | 首板流剔除层 lift 验证 | ✅ | |
| S078 | 涨停历史 snapshot 数据地基 | ✅ | |
| S079 | 打板 P2 战法与仓位闸 | ✅ | |
| S081 | 打板 P2 战法匹配 | ✅ | |
| S082 | echarts 按需引入 | ✅ | |
| S083 | 工作流重构选股池分层 | ✅ | → S092 三视图 |
| S084 | 选股池战法解耦 | ✅ | → S092 三视图 |
| S085 | 因子全量补全与游资画像 | ✅ | |
| S086 | 涨停战法 pipeline 统一架构 | ✅ | → S092 三视图 |

---

## M4 三视图（S087-S093）✅ 2026-08-21 ~ 2026-08-22

工作流 tab 重构/暴风雨预测/SQLite 并发/premarket 接入/限流容错/交易日锚/内容重组。

`specs/` 根目录 · 7 specs

| 编号 | 一句话 | 状态 | 级别 | 备注 |
|---|---|---|---|---|
| S087 | 工作流 tab 按 pipeline 重设计 | ✅已实现 | medium | → S092 三视图替代 |
| S088 | 盘前暴风雨预测 | ✅已实现 | medium | |
| S089 | SQLite 并发性能加固与分表分库 | ✅已实现 | medium | |
| S090 | premarket 选股前端接入与 kline 日更 | ✅已实现 | medium | |
| S091 | gstock 限流容错优化 | ✅已实现 | small | |
| S092 | 三视图交易日锚与时段推进 | ✅已实现 | medium | Oracle P1-P10 已修复 |
| S093 | 三视图内容重组与飞书通知 | ✅已实现 | large | Oracle 4 轮审查闭合 |

---

## M5 战法细化（S094-S097）✅ 已完成 2026-08-22 ~ 2026-08-26

战法分类双 pipeline / gene_scores 写路径 / P2 现象判据 / 逐条件因子过滤。

`specs/` 根目录 · 4 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S094 | 战法分类与双 pipeline 重构（涨停/非涨停） | ✅已实现 | S0-S5 done（2269 passed）+ T25 5/5 + T28 e2e 4 测全绿 |
| S095 | gene_scores 写路径修复与日期守卫 | ✅已实现 | 6 tests 全绿，全量 2226 passed，七日 7/7 code 集合全等 |
| S096 | P2 现象判据暴露（fired_rule override + 数据降级） | ✅已实现 | grill Q1 完整链 + Q2 红期 override |
| S097 | 逐条件因子过滤（三态 + 批次聚合 + 前端漏斗） | ✅已实现 | 12 战法三态 + 聚合 + 前端漏斗；对抗验证 2 bug 修；2275 passed |

---

## M6 首板流 §44 合规（S098）✅ 已完成 2026-08-26

首板流 select 不 auto-rank + 确认时间序（§44 合规，raw-shadow 路径）。

`specs/archive/m6-首板流合规/` · 1 spec

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S098 | 首板流选股 §44 合规修复（select 不 auto-rank + 确认时间序） | ✅已实现 | 29 测试绿，全量 2279 passed，1 pre-existing 非 S098 |

---

## M7 战法卡片对齐（S097 收尾）（S100-S101）✅ 已完成 2026-08-27

S097 match 重构后 cards/*.md 卡片跟上 + fa4514e 阈值残局收拾。

`specs/archive/m7-战法卡片对齐/` · 2 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S100 | 战法卡片对齐 match 条件（S097 收尾 + fa4514e 阈值同步） | ✅已实现 | 12 卡片 + docstring + S097§5.2 + registry entry_condition + 一致性测试；fa4514e 测试残局顺手修；2281 passed |
| S101 | 飞书多点通知（9:25 竞价 / 9:35 开盘 / T+1 复盘） | ✅已实现 | 第1步修 T-1 通知 cron 17:15 + final=0 guard；第2步 3 新 executor + 内容函数 + seed；2295 passed |
| S102 | 战法卡片历史战绩 | ✅已实现 | commit fa29994；S100 延伸 |

---

## M8 诚实化底座（S102-S117）✅ 已完成 2026-08-29 ~ 2026-08-30

hithink 直连+缓存治理+撒谎清扫+裂缝登记+chip-cyq+completeness+storm daemon。

`specs/` 根目录 · 16 specs（S107 已废弃→归档 `specs/archive/`）

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S102 | 战法卡片历史战绩 | ✅已实现 | fa29994 |
| S103 | 涨停池缓存承重切片 | ✅已实现 | ea01000 |
| S104 | hithink 结构性缺口唯一源 | ✅已实现 | |
| S105 | hithink 直连 HTTP 复刻 | ✅已实现 | |
| S106 | cross_validate 接线 | ✅已实现 | |
| S107 | 龙虎榜 hithink 集成 | 🗑️废弃 | 调研结论不做→归档 |
| S108 | 新浪三表孤儿管道接线 | ✅已实现 | |
| S109 | 缓存治理 Tier1 | ✅已实现 | |
| S110 | fund_flow 测试断言对齐 | ✅已实现 | |
| S111 | 真实裂缝登记册 | ✅已实现 | |
| S112 | Tier2 撒谎诚实化 | ✅已实现 | |
| S113 | 诚实缺陷 availability 修复 | ✅已实现 | |
| S114 | chip-cyq 自建走 emget | ✅已实现 | |
| S115 | completeness-gaps 三修 | ✅已实现 | |
| S116 | storm-daemon availability | ✅已实现 | |
| S117 | premarket offbyone | ✅已实现 | |

---

## M9 源诚实化+撒谎清扫+并行化（S119-S139）✅ 已完成 2026-08-31 ~ 2026-09-01

source-em-raise/hithink-rank/tencent-zero/weekend-gate/lying-ledger/or-zero/risk-trio/批量修/scan/ai-tool/emotion-cache/熔断器/延时/premarket-kill/catalyst并行/activity并行/sector_phase。

`specs/` 根目录 · 21 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S119 | source-em-raise honesty | ✅已实现 | |
| S120 | hithink-rank raise | ✅已实现 | |
| S121 | tencent-num-zero honesty | ✅已实现 | |
| S122 | market-emotion weekend gate | ✅已实现 | |
| S123 | s118 lying-ledger cleanup | ✅已实现 | |
| S125 | s124 high-lying fix | ✅已实现 | |
| S126 | frontend-render honesty | ✅已实现 | |
| S128 | orzero-contract and high fix | ✅已实现 | |
| S129 | risk-trio provenance | ✅已实现 | 3acc295 |
| S130 | 非承重 lying 批量修 | ✅已实现 | 94ab574 |
| S131 | scan confirmed-lying | ✅已实现 | 94ab574 |
| S132 | ai-tool-source-unreachable | ✅已实现 | 3c475af |
| S133 | emotion-date-keyed-cache | ✅已实现 | 353e53b |
| S134 | 新浪源熔断器 | ✅已实现 | |
| S135 | 延时数据前端诚实消费 | ✅已实现 | |
| S136 | premarket-kill-switch 开盘后实时核 | ✅已实现 | |
| S137 | catalyst 并行化 | 草案 | |
| S138 | activity 并行化 | 草案 | |
| S139 | sector_phase 纯 LABEL 接线 | ✅已实现 | 089b8f3 |

---

## M10 工作流重脊柱+§44测量+pipeline重设计（S140-S148）✅ 已完成 2026-09-02 ~ 2026-09-03

盘前垂直切片/pipeline节点化/step-state契约/rail复制/§44测量地基/路径胜率门/选股重设计/winrate-rename/第二层过滤。

`specs/` 根目录 · 9 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S140 | 工作流层重脊柱 盘前垂直切片试点 | ✅已实现 | |
| S141 | FirstBoardPipeline 节点化拆分 | 草案 | 待 S140 落地后实施 |
| S142 | pipeline step-state 契约 | 草案 | S141 硬前置 |
| S143 | 盘中盘后 rail 复制 | ✅已实现 | |
| S144 | §44 测量地基修复 | ✅已实现 | Tier 1 |
| S145 | §44 路径胜率门 | ✅已实现 | Tier 2 |
| S146 | 选股 pipeline 重设计 | ✅已实现 | |
| S147 | strategy-winrate honest rename | ✅已实现 | |
| S148 | 选股第二层过滤 | ✅已实现 | |

---

## M11 语义吸收+采集修复+评价层+harness（S149-S156）🔄 进行中 2026-09-04 ~ 2026-09-06

vibe-astock语义吸收/采集堵塞修复/漏斗评价层/盘中H2harness/量化模型验证/debate辅助层/vol-surge（废弃）/zt-pool retest。

`specs/` 根目录 · 8 specs（S155 已废弃→归档 `specs/archive/`）

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S149 | vibe-astock 语义吸收 | 审核通过待实施 | Phase 0 审计 ✅ |
| S150 | 盘中采集堵塞修复 | ✅已实现 | 095bd2a subprocess 改造 |
| S151 | 漏斗评价层 | ✅已实现 | R1-R5 后端+前端+21 测 |
| S152 | 盘中 H2 harness | ✅已实现 | verdict: H2 早封板 lift=0.7843 劣于随机 |
| S153 | 量化模型验证 | 草案 v2 | 4 CRITICAL+2 HIGH 修，待实现 |
| S154 | debate 辅助层 | 草案→实现中 | |
| S155 | vol-surge-volatility-profit-verify | 🗑️废弃 | premise 证伪→归档 |
| S156 | zt-pool seal-time retest | ✅已实现 | 0204262 |

---

## M12 底座重建 v2（S159-S166）🔄 进行中 2026-09-06 ~ 2026-09-07

§44v2应用规约/底座重建/验证框架/反前视引擎/数据质量门/防封backbone/UI契约/Journal+RiskLedger。

`specs/` 根目录 · 8 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S159 | §44 应用规约 v2 | 草案（方向已接受） | evidence 待补 |
| S160 | 底座重建 | 草案 v2 | 世纪大辩论 10 视角收敛 |
| S161 | §44v2 验证框架 | 草案 v2 | S160 component 1 |
| S162 | 反前视引擎三层 | ✅已实现 | da7ba54 |
| S163 | 数据质量门+轻量血缘 | ✅已实现 | da7ba54 lineage 接线 |
| S164 | 防封 backbone+secrets-gate | ✅已实现 | da7ba54 CI lint gate |
| S165 | UI 契约先行 | 草案 v2 | S160 component 5 |
| S166 | TradeJournal+RiskLedger | 草案 | S160 component 6 |

---

## M13 盘中微结构+批量接线+event edges+长线（S167-S172）🔄 进行中 2026-09-06 ~ 2026-09-08

盘中微结构累积/12harness批量接线/PEAD中线event/摘帽event/长线价值/红利低波指数复制。

`specs/` 根目录 · 6 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S167 | 盘中微结构数据累积 | 🔄进行中 | medium，issue 层单轮 review |
| S168 | 批量接线 12 harness | ✅已实现 | ebecbec 12 harness §44v2 verifier 全 selection |
| S169 | 中线 event-PEAD | ✅已实现 | 8ae588a 15 verdict 短 falsified |
| S170 | 摘帽 event | 草案 | medium，复用 midline_event_harness |
| S171 | 长线价值 | ✅已实现 | f67ebf5 spec+R3 done（R2 方向转实用不做） |
| S172 | 红利低波指数复制臂 | ✅已实现 | 2026-09-09 floor ETF 512890 |

---

## M14 模拟盘自洽闭环+多臂+胜率曲线（S173-S183）🔄 进行中 2026-09-09 ~ 2026-09-11

TradeJournal 闭环/模拟盘自洽/OFI 收集器+看板/kline degraded/cockpit 清理/r3 sizing/趋势臂/PEAD cost/胜率曲线。

`specs/` 根目录 · 11 specs

| 编号 | 一句话 | 状态 | 备注 |
|---|---|---|---|
| S173 | TradeJournal 闭环 | ✅已实现 | fa25be8+84a5c2d 4 模块 55 测 |
| S174 | godmodule 拆分 | ✅已实现 | P2/P3 拆分 5 commit |
| S175 | 模拟盘自洽闭环 | ✅已实现 | P0+P1+P2 128 tests+tsc0 |
| S176 | 盘中 OFI 数据收集器 | ✅已实现 | 35 tests+188 全量 |
| S177 | kline-refresh degraded | ✅已实现 | 32 tests+全量 3200 passed |
| S178 | OFI 盘中数据看板 | ✅已实现 | 7 tests+tsc0 |
| S179 | trade-desk cockpit | ✅已实现 | Phase 0-3 清理净删-3000 行 |
| S180 | r3 sizing 接线 | ✅已实现 | 79827ef + 58 tests |
| S181 | 趋势波段臂 | ✅已实现 | b234446+653d83e+98555b6 6 测 |
| S182 | PEAD per-trade real cost | ✅已实现 | 7e49468 |
| S183 | 模拟盘胜率变化曲线 | ✅已实现 | 实时聚合+Wilson CI+50%基准；后端 7+前端 4+tsc0 |
| S184 | kline_refresh 性能 | ✅已实现 | grill rethink 方案 0：数据就绪预检+cron 17:15（非限制 universe）；91fd5fd |
| S185 | Turso 多源数据湖 | ✅已实现 | 路径 A KISS 零 libsql + v2/pipeline + sync_all 3354 synced + ofi 47039 行 + 降级三态 |
| S186 | 前端 UX 重构 | 🔄 Phase 2 done | 6 域 19 路由 + ~20 redirect（Phase 1 无死代码 S179 已清，Phase 2 router.tsx done，Phase 3 待）|

---

## 归档规则

- spec 完成验收后自动归档到对应里程碑目录
- 里程碑内所有 spec 完成后该里程碑标 ✅
- 新里程碑的第一个 spec 接续编号（不重置）
- 旧 spec 不删不改，保留作历史决策记录
- 被替代的 spec 在"备注"列标 → 后继 spec
