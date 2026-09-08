# S171 UI 契约 — 价值因子月度 §44v2 验证看板

> 状态：草案 | 日期：2026-09-08 | 分级：medium | 关联：S165（verifier 契约复用）/ S171 spec（822db17）
>
> **Design Read**：投研终端数据看板（cockpit density），个人投研者读数场景，暗色暖中性单色板，
> 纵向叙事 + 交互 drill-down，非营销页。design-taste §13 明示本 skill 不管 dashboard，
> 仅取 anti-slop / 暗色 / shape-lock / em-dash 禁令等普适规则。

## 1. 组件结构（React 组件树 + 字段消费映射）

```
S171ValueVerdictPage (page, 路由 /value-verification)
├─ useS171ValueBundle()  TanStack Query
│  → GET /api/verifier/records?spec=S171
│  前端按 params.experiment_id==='S171' 过滤 + params.co_primary_role 分组 +
│  params.delisting_return 分 tier，组装 S171ValueBundle（见 §2）
│
├─ VerdictHeader
│  ├─ CombinedGateDots     — 3 圆点 UI-computed（非 API 字段）
│  │  pass=绿实心 / fail=红实心 / 未测=灰空心
│  ├─ StatusPill            — bundle.combined_status + edge_type 联合标签
│  └─ ReproduceButton       — onClick → 滑入 ReproducePanel
│
├─ ThreeQuestionKpiRow  [graft P4，唯一直答投研者心智模型]
│  ├─ KpiTile 稳不稳       — derived: combined_status 降级=不稳 / robust=稳
│  ├─ KpiTile 能信不       — derived: combined_status + extrapolation_warnings
│  └─ KpiTile 能交易不     — derived: ① tradeable=false + ② tradeable=true + combined
│  · 每格 icon + 一句人话 why（非单一 Verdict 字段，从 bundle 综合算）
│
├─ ExtrapolationWarningStrip  [graft P2，警示放 verdict 之前，不可折叠]
│  consumes: bundle.extrapolation_warnings[]（5 条，spec R5 全覆盖）
│  · 1m 月频 proxy 非长线 verdict
│  · period-specific（2018-2026 growth-favorable）
│  · 联合测试不能解窗口 vs 股票池归因（S168→S171 双变更）
│  · ① long-short 不可直接交易（A 股 short 受限）
│  · 月末资金面 confound（entry 月末最后交易日，资金面紧张污染买入价）[spec R5 line 53 补]
│
├─ GateDecisionFlow  [graft P4 纵向流，非三张并列卡，避 design-taste §9.C]
│  ├─ GateNode 互验          — bundle.gates.cross_check
│  ├─ GateNode sensitivity   — bundle.gates.sensitivity
│  ├─ GateNode 覆盖率        — bundle.gates.coverage
│  └─ CombinedVerdictNode    — bundle.combined_status + edge_type 联合
│  · 纵向连接线（CSS ::before）表达"三 gate 全过才 robust"因果链
│  · combined = 最低那档（任一不过即降级）
│
├─ CoPrimaryCrossCheck  [graft P1 三列布局 ① | gate | ②]
│  ├─ PrimaryCard ① (edge_type=event, 蓝色 categorical swatch)
│  │  consumes co_primary_1.verdict:
│  │    event_metrics{mean_return, net_mean, win_rate, t_stat_day_clustered, n_event, base_rate}
│  │    event_status, tradeable=false, n, days_robust, frozen_commit
│  │    params.event_materiality_floor (from RecorderRecord.params)
│  │  ├─ EventMetricsPanel（复用 DimensionValidationCard event_metrics 子件）
│  │  ├─ TradeableBadge（不可直接交易 - long-short）
│  │  └─ WinrateBiasNote（"① 管 mean 无 winrate 偏"静态标注）
│  │
│  ├─ CrossCheckGateCenter  — bundle.gates.cross_check（视觉锚点）
│  │  矛盾/一致 状态 + 下箭头 → combined 结果
│  │
│  └─ PrimaryCard ② (edge_type=selection, 橙色 categorical swatch)
│     consumes co_primary_2.verdict:
│       lift, ci_low, ci_high (null→"待 v2 verifier" 灰底), n, n_effective, days_robust
│       tradeable=true, params.purged_kfold_lift, params.walk_forward_lift
│     ├─ SelectionMetricsPanel
│     ├─ OosPanel（PurgedKFold + walk-forward，从 params 取）
│     ├─ TradeableBadge（long-only 可实现）
│     └─ SelectionFalsifiedNote（"② selection not_validated ≠ 价值无 edge，① event 有弱正 mean"防外推）
│
├─ SensitivityToggle  [graft P3，杀手交互]
│  consumes: bundle.sensitivity_rows[]（2 tier，-0.5 / -1.0）
│  ├─ ToggleButton ×2（-0.5 温和 / -1.0 保守 worst-case）
│  ├─ VerdictFlipIndicator — 切 tier 时 ① event_status + ② status 实时变
│  │  flip=红"verdict 翻转，结论依赖退市假设" / stable=绿"一致，结论不依赖假设"
│  └─ LiftDeltaFlag — 两 tier lift 差值
│  · 切一次就理解"verdict 依赖退市假设，不可信为 robust"
│
├─ CoveragePanel  [graft P1 meter bar，ratio-to-limit 用 meter 非 pie]
│  consumes: bundle.coverage_audit
│  ├─ DualMeter（宽松 lenient_pct + 严格 strict_pct，50% 门槛竖线）
│  ├─ ZeroBarsStat（zero_bars_count / total_delisted / pct）
│  └─ BiasDirectionNote（bias_direction = favors value，不可恢复）
│
├─ StLayerSeparation
│  consumes: bundle.st_separation
│  ├─ 验证层（保留 *ST，保守，不删 value trap 尾部）
│  └─ capture 层（规避 *ST，实盘不买）
│  · 标"剔 *ST 美化 value，capture 剔后仍有 edge 才是真可交易 edge"
│
├─ DeferredFactorsNote  [spec R2 gap 补]
│  consumes: bundle.deferred_factors[]
│  · F2 PE+ROE composite（Family C K=1，数据够才跑）
│  · F3 Low PB（BVPS 派生 3/4 季度失效，Q4-only deferred）
│  · PE 是 pragmatic proxy 非 canonical B/M（数据可得性驱动）
│
├─ BugFixSeverityGrid  [graft P2，9 bug 全可见带 severity 色边，不折叠]
│  consumes: bundle.bug_fixes[]（9 项）
│  · 3×3 grid，每项 severity 色左边框（critical=红 / high=琥珀 / latent=灰）
│  · icon + title + status badge（fixed=绿 / pending=黄"未验" / annotated=灰"已标注"）
│  · 数据可信是诚实标注核心，不藏 tooltip/折叠
│
├─ AuxiliarySecondaryRow
│  ├─ VerdictMiniCard auxiliary（low_pe + high_pe，selection，not_validated）
│  └─ VerdictMiniCard secondary（Q1-excess-HS300，event，size-confounded caveat）
│
├─ CaveatList  [spec R5 gap 全补]
│  · restatement risk（baostock 可能存 restated epsTTM 保留原始 pubDate）
│  · turnover sensitivity（cost drag 1.5% vs 3% 看 verdict 是否翻转，首跑后实测）
│  · Newey-West HAC SE deferred（月度自相关，day_clustered t 略偏高，caveat 标注）
│  · 月度 autocorrelation（组合慢变，跨月自相关违反 iid）
│
└─ ReproducePanel  [graft P3 滑入面板，不阻断上下文]
   consumes: co_primary_1 (RecorderRecord)
   ├─ recorder_id / data_snapshot_id / input_snapshot_hash / timestamp
   ├─ ParamsTable（round_trip_cost / event_materiality_floor=0.001 amber 高亮 /
   │  walk_train / walk_test / step / delisting_return / K_familyA / K_familyB）
   └─ StatusMatchCheck（reproduce_verdict 重算 status 一致）
   · event_materiality_floor 是唯一直接影响 status 的参数（verifier.py:370-374）
     不存 Recorder params → reproduce 用 verify 默认 0.003 非 0.001 → status 翻转 → A5 炸
```

## 2. 数据形状（TypeScript 类型，扩展 S165 verifier-contract.ts）

S171 复用 S165 既有 `Verdict` / `RecorderRecord` / `VerifierStatus` / `EdgeType` /
`EventMetrics` / `EventStatus` 类型（verifier-contract.ts），不重复定义。
新增以下 S171 专属类型（追加到 verifier-contract.ts，S165 R4 双向锁）：

```typescript
// S171 R1: 退市覆盖率审计（spec R5，S171-NEW，非 Verdict 标准字段）
interface S171CoverageAudit {
  lenient_pct: number;        // 返 >0 bars 退市股占比（宽松口径）
  strict_pct: number;         // ipoDate..outDate 完整活跃期覆盖 ≥80% 占比（严格口径）
  zero_bars_count: number;   // 0-bars 退市股数（无 kline，不可恢复 bias）
  total_delisted: number;     // 退市股总数（type=1, outDate!=""）
  bias_direction: "favors_value"; // 不可恢复偏差方向（0-bars = value trap 缺失 = 高估 value）
}

// S171 R1: sensitivity 两档（spec R5，退市 return -0.5 vs -1.0）
interface S171SensitivityRow {
  delisting_return: number;  // -0.5 或 -1.0
  primary_1_event_status: EventStatus;  // ① event 子结论
  primary_2_status: VerifierStatus;     // ② selection status
  primary_2_lift: number;               // ② lift
  combined: VerifierStatus;             // 该 tier combined verdict
}

// S171 R1: gate 结果（UI-computed，非 API 字段，前端从 component verdicts 算）
interface GateResult {
  passed: boolean;
  label: string;             // "一致" / "矛盾" / "通过" / "不过"
  detail: string;           // 一句人话原因
  severity: "good" | "warning" | "critical";
}

// S171 R1: 9 bug fix 诚实标注（spec R1-R3 bug 清单）
interface S171BugFix {
  id: number;
  title: string;
  detail: string;           // what was wrong
  fix: string;              // fix 描述
  severity: "critical" | "high" | "latent"; // 承重=红 / 重要=琥珀 / latent=灰
  status: "fixed" | "pending" | "annotated"; // 已修 / 未验 / 已标注
}

// S171 R1: ValueVerificationBundle — 聚合多 RecorderRecord + gate metadata
interface S171ValueBundle {
  // 多 RecorderRecord（params.experiment_id==='S171' 过滤，按 co_primary_role + delisting_return 分组）
  co_primary_1_tier1: RecorderRecord;  // ① event, Q1-Q5 spread, -0.5 tier
  co_primary_2_tier1: RecorderRecord;  // ② selection, Q1-excess-universe, -0.5 tier
  co_primary_1_tier2: RecorderRecord;  // ① event, -1.0 tier
  co_primary_2_tier2: RecorderRecord;  // ② selection, -1.0 tier
  auxiliary: { low_pe: RecorderRecord; high_pe: RecorderRecord } | null;
  secondary: RecorderRecord | null;     // Q1-excess-HS300, Family B K=1

  // S171-NEW（UI-computed 或 run 后落 Recorder params）
  gates: {
    cross_check: GateResult;    // ①② 方向一致判定
    sensitivity: GateResult;   // -0.5/-1.0 两档 verdict 一致性
    coverage: GateResult;       // strict_pct >= 50
  };
  combined_status: VerifierStatus;  // 三 gate 全过才 robust_edge，任一不过降级
  coverage_audit: S171CoverageAudit;
  sensitivity_rows: S171SensitivityRow[];  // 2 行（-0.5 / -1.0）
  bug_fixes: S171BugFix[];              // 9 项
  extrapolation_warnings: string[];     // 5 条（spec R5 全覆盖）
  st_separation: { verification: string; capture: string };
  deferred_factors: string[];          // F2/F3/PE-proxy caveat
  caveats: string[];                   // restatement/turnover/Newey-West/autocorrelation
}
```

### 字段来源映射（诚实标注，哪些来自 API 哪些 UI-computed）

| 字段 | 来源 | mock 阶段 |
|---|---|---|
| co_primary_1/2.verdict (event_metrics, lift, status...) | API: RecorderRecord.verdict | 前端 mock fixture |
| co_primary_1/2.params (event_materiality_floor, purged_kfold_lift...) | API: RecorderRecord.params | mock fixture |
| gates.cross_check / sensitivity / coverage | UI-computed（前端从 verdicts 算） | 前端 derived |
| combined_status | UI-computed（三 gate 全过才 robust） | 前端 derived |
| coverage_audit | API: RecorderRecord.params.coverage_audit（S171 run 落 params） | mock fixture |
| sensitivity_rows | UI-computed（从 tier1/tier2 verdicts 组装） | 前端 derived |
| bug_fixes | 静态 spec copy（spec R1-R3 bug 清单，非 API） | 硬编码 |
| extrapolation_warnings | 静态 spec copy（spec R0/R5，非 API） | 硬编码 |
| st_separation | 静态 spec copy（spec R5） | 硬编码 |
| deferred_factors | 静态 spec copy（spec R2/R8） | 硬编码 |
| ci_low / ci_high | API: Verdict.ci_low/ci_high（null → "待 v2 verifier" 灰底） | null（不臆造） |
| n_effective | API: Verdict.n_effective（null → "待 v2 day_paired"） | null |

> mock 阶段：derived 在前端算，实 S171 run 后接 GET /api/verifier/records 读真实值替换。
> S171-NEW 字段（coverage_audit / combined_status / gates）若落 Recorder params 须同步入
> verifier-contract.ts（S165 R4 双向锁）。

## 3. 诚实标注规则

### 3.1 三 gate 呈现（纵向决策流，非三张并列卡）

- 纵向连接线 + 节点圆点 + status pill，gate 顺序 = 判定逻辑因果链：
  互验 → sensitivity → 覆盖率 → combined 终端节点
- combined = 三 gate 全过才 robust_edge，任一不过降级到最高优先级 fail status
- 互验 gate：①② 方向一致（都 edge 或都无 edge）才信，矛盾降级 exploratory 标"双 PRIMARY 不一致"
- sensitivity gate：-0.5/-1.0 两档 combined verdict 一致 → 稳；不一致 → 降级 exploratory 标"依赖退市 return 假设"
- 覆盖率 gate：strict_pct ≥ 50% 才过；<100% 标"残留 survivorship bias，方向高估 value"
- gate 节点圆点用 status 色（good 绿 / warning 琥珀 / critical 红），总配 icon + 文字（status 色不单独承义，dataviz 铁律）

### 3.2 不可外推警示（5 条，hero 位，verdict 之前，不可折叠）

1. **1m 月频 proxy 非长线 verdict**：从月频外推到年频 = §44v1 错窗口镜像。3m/6m/12m horizon 因 n<60 underpowered 不出正式 verdict
2. **period-specific**：2018-2026 偏 growth-favorable（2019-2021 A 股成长 rally），falsified 是这段周期结论非全周期证否
3. **联合测试不能解归因**：S168（涨停/3天）→ S171（全A/1月）窗口+股票池双变更不可分离
4. **① long-short 不可直接交易**：A 股 short 受限（融券难+贵），② long-only 才可实现
5. **月末资金面 confound**：entry 用月末最后交易日，A 股月底/季末/年末资金面紧张系统性污染买入价 [spec R5 line 53 补]

### 3.3 verdict status 5 色 + edge_type 主标签

- robust_edge=绿（good #0ca30c）/ underpowered=黄（warn #fab219，"待 live 60 天复验"）/ falsified=红（crit #d03b3b）/ not_validated=灰（neutral，"弱信号非欠样本"）/ exploratory=灰（neutral，"矛盾下不能定论"）
- edge_type=event/selection 主标签永远在 status 旁（蓝=event / 橙=selection categorical swatch），防 selection-falsified 被读成"无 edge"
- underpowered 明确标"待 live 60 天复验"非"劣于随机"（S159 v2：小 n 标 underpowered 不判劣于随机）
- not_validated vs exploratory 都是灰但 label 不同，靠 label 区分非色相
- status 色总配图标 + 文字（dataviz 铁律：status 色不单独承义）

### 3.4 9 bug fix 诚实标注（全可见，severity 色边，不折叠）

| # | bug | severity | status | spec 依据 |
|---|---|---|---|---|
| 1 | 前复权 PE 致命 bug（adjustflag=3） | critical | fixed | R1 Layer1 |
| 2 | query_all_stock PIT 行为未验 | critical | **pending（未验）** | R1 Layer3 line 23 明写"未验" |
| 3 | outDate='' 二义（sanity 6 月无新 bar） | high | fixed | R1 Layer3 |
| 4 | 0-bars 不可恢复 bias（计入分母） | critical | annotated | R1 Layer3 |
| 5 | BH m=1 latent（K=1 moot，扩 K 须 enforce） | latent | annotated | R3 SECONDARY |
| 6 | event_materiality_floor 月频 0.001 | high | fixed（存 Recorder params） | R3 wire_verdict |
| 7 | pubDate < D 严格小于 | critical | fixed | R2 F1 |
| 8 | sort tie-breaking（quarter_key 降序） | high | fixed | R2 F1 |
| 9 | 停牌 stale close（volume==0 双重剔除） | high | fixed | R1 Layer3 |

> 关键修正（judge gap #1）：#2 query_all_stock PIT spec 明写"未验"，不可标"已验/fixed"。
> 须标 pending"待验"，否则投研者误以为 PIT 已解决 → verdict 可信度虚高。

### 3.5 selection-falsified 防外推（继承 S165 R7）

- ② selection not_validated/falsified 时加蓝底 note："selection falsified; event edge may exist（see ① event verdict）"
- 防外推 cross-note 在两栏之间："② selection not_validated ≠ 价值无 edge，① event 有弱正 mean 信号。把 selection-falsified 读成'价值因子无 edge'正是外推越界（§44v1 同型）"

### 3.6 *ST 两层分离

- 验证层：保留 *ST（保守，不删 value trap 尾部，保"不剔除退市"一致性）
- capture 层：规避 *ST（实盘不买，涨跌停 ±5% + 流动性差 + 退市风险）
- 标"剔 *ST 美化 value，capture 须 *ST filter。capture 剔后仍有 edge 才是真可交易 edge"

### 3.7 退市 -100% worst-case + sensitivity

- 退市整理期实际损失 -50%~-90%（老三板 NEEQQ），-100% 归零是保守 worst-case
- sensitivity 两档对比：-0.5 温和 vs -1.0 保守 worst-case
- 一致性 gate：两档 combined verdict 一致 → 稳；不一致 → 降级 exploratory
- 退市 return 规则在 survivors 和 universe 一致（同月同值，不静默 drop 退市股）
- 不剔除退市（退市是 value premium 承重样本，剔除 = 删 value trap 尾部 = 假性抬高 value）

### 3.8 严格覆盖率双数

- 宽松（返 >0 bars 占 %）+ 严格（ipoDate..outDate 完整覆盖 ≥80% 占 %）双数并排
- 严格 <50% → gate fail → verdict 降级
- 0-bars 退市股计入分母（算 0% 覆盖，不静默排除）
- 标"0-bars 不可恢复 bias，方向 = 高估 value premium（value trap 缺失 → Q1 收益虚高）"

### 3.9 mock 诚实标注

- hero 旁 mock tag（"mock · 待 S171 run 跑出"）
- ci_low/ci_high 标"待 v2 verifier"灰底（不臆造）
- n_effective 标"待 v2 day_paired"灰底
- footer 注明"按 spec 设计的代表性场景（co-PRIMARY 矛盾 → 探索性），实 verdict 由 long_value_run.py 跑出后落 Recorder，UI 经 /api/verifier/records 读真实值替换"
- params 数字（round_trip_cost=0.0025, event_materiality_floor=0.001 等）来自 spec R3 非臆造

## 4. API 契约（基于 S165 routers/verifier.py）

### 4.1 复用 S165 既有端点（不改后端）

```
GET /api/verifier/records?limit=100
  → RecorderRecord[]（S165 已有，verifier.py:143）
  前端按 params.experiment_id==='S171' 过滤 + params.co_primary_role 分组 +
  params.delisting_return 分 tier，组装 S171ValueBundle

GET /api/verifier/records/{recorder_id}
  → RecorderRecord（S165 已有，verifier.py:158）
  ReproducePanel 用此端点 reproduce_verdict
```

### 4.2 S171-NEW 字段落 Recorder params（spec A2/A3）

S171 run（long_value_run.py）须将以下字段存入 RecorderRecord.params dict：

| params key | 类型 | 用途 | spec 依据 |
|---|---|---|---|
| experiment_id | string="S171" | 前端过滤 | A2 |
| co_primary_role | "primary_1"\|"primary_2"\|"auxiliary"\|"secondary" | 角色识别 | A2 |
| delisting_return | number (-0.5 / -1.0) | sensitivity 分 tier | A4 |
| event_materiality_floor | number=0.001 | **唯一直接影响 status** | R3, A5 |
| round_trip_cost | number=0.0025 | harness 预扣成本 | R3 |
| walk_train | number=36 | walk-forward 训练窗 | R3 |
| walk_test | number=12 | walk-forward 测试窗 | R3 |
| step | number=12 | walk-forward 步长（月） | R3 |
| purged_kfold_lift | number | ② OOS lift | R3 |
| walk_forward_lift | number | ② OOS lift | R3 |
| coverage_audit | S171CoverageAudit | 退市覆盖率审计 | R5 |
| n_comparisons | number | Bonferroni K | R3 |
| holding_horizon | string="1m" | 持有期标识 | R4 |

> event_materiality_floor 须存 Recorder params（spec R3/A5 强制）：
> verifier.py:370-374 `if days_robust>=60 and t_res.day_mean > effective_floor: event_robust else event_thin_positive`
> effective_floor = max(event_materiality_floor, round_trip_cost*0.5)
> 不存 → reproduce_verdict 用 verify 默认 0.003 非 harness 0.001 → status 翻转 → A5 炸

### 4.3 前端 query hook

```typescript
// S171 前端组装 hook（mock 阶段读 fixture，实 run 后接 API）
function useS171ValueBundle(): UseQueryResult<S171ValueBundle> {
  return useQuery({
    queryKey: ["s171-value-bundle"],
    queryFn: async () => {
      const records = await fetch("/api/verifier/records?limit=200").then(r => r.json());
      const s171 = records.filter(r => r.params?.experiment_id === "S171");
      return assembleBundle(s171); // 按 co_primary_role + delisting_return 分组组装
    },
  });
}
```

### 4.4 S165 兼容性

- 复用 DimensionValidationCard 的 event_metrics 子件 + overfit pills + commit 追溯子件
- 复用 GlassCard 容器 + STATUS_STYLE 色码 + statusFromChinese 映射
- 复用 HonestyBanner 的 amber-500/10 视觉语言
- 不复用 S165 三窗口对比表（隔夜 gap/D+1 日内/path）—— S171 是月频 value，窗口 sanity 是月度 vs 日度对比非隔夜/D+1/path，对月频 value 无意义（P1 trade_off #2 明确弃了）
- S171-NEW 字段若落 Recorder params 须同步入 verifier-contract.ts（S165 R4 双向锁）

## 5. 交互规约

### 5.1 sensitivity toggle（graft P3，杀手交互）

- 两按钮 toggle（-0.5 温和 / -1.0 保守 worst-case），非滑块（spec 恰好两档离散值）
- 切 tier 时 ① event_status pill 颜色实时变（warn→crit），② status pill 同步变（neutral→crit），combined pill 同步变
- flip indicator 红底显示翻转描述
- 投研者亲手切一次就理解"verdict 依赖退市假设，不可信为 robust"

### 5.2 reproduce slide-in（graft P3，不阻断上下文）

- 右侧滑入 420px 面板，非 modal（不遮挡主内容）
- event_materiality_floor=0.001 标 amber 高亮，提示"唯一直接影响 status 的参数"
- StatusMatchCheck 显示 reproduce_verdict 重算结果

### 5.3 无动画（MOTION_INTENSITY = 2）

- 数据看板不需要 scroll-reveal 或 hover physics
- 仅 CSS :hover 状态 + toggle 切换的即时反馈
- prefers-reduced-motion 不需特殊处理（无动画可降）

## 6. canonical mock 场景（统一，非多提案不一致）

| 维度 | -0.5 温和 tier | -1.0 保守 worst-case tier |
|---|---|---|
| ① event_status | event_thin_positive | event_falsified |
| ① mean/mo | +0.31% | +0.085% |
| ① net/mo | +0.18% | -0.066% |
| ① t-stat | 1.82 | 0.41 |
| ① p_bonf | 0.136 | 0.681 |
| ② status | not_validated | falsified |
| ② lift | 1.18 | 0.94 |
| ② CI | [0.97, 1.42] | [0.76, 1.18] |
| combined | exploratory | falsified |

- 互验 gate：PASS（①② 都"not robust"方向一致）
- sensitivity gate：**FAIL**（-0.5 exploratory → -1.0 falsified，翻转）
- 覆盖率 gate：PASS（strict 58% ≥ 50%，但残留 bias）
- combined_status：**exploratory**（互验 pass，sensitivity fail，coverage pass → 非全过 → 降级）
- days_robust：87（≥60 R6 过门槛）
