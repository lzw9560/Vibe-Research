// S171 价值因子月度验证看板——低 PE 价值股 vs 高 PE 成长股，月度调仓，看价值溢价在 A 股成不成立。
// UI 先行（memory ui-first-implementation-order）：页面先用 mock 落地，真实 verdict 由
// backend/tools/long_value_run.py 跑出落 Recorder 后，经 /api/verifier/records 读真实值替换。
// 措辞原则（memory feedback-style-plain-chinese）：用人话直答投研者三问——稳不稳/能信不/能交易不，
// 技术值保留给愿深挖的人（术语括号注一次，不堆砌）。
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { useVerifierRecords } from "@/lib/query";
import { s171ValueMock } from "@/lib/__fixtures__/s171-value.mock";
import type {
  S171ValueBundle,
  S171SensitivityRow,
  S171GateResult,
  VerifierStatus,
  EventStatus,
  RecorderRecord,
} from "@/lib/verifier-contract";

// 综合结论 5 态→人话 + 色（色不单独承义，总配文字）
const STATUS_HUMAN: Record<VerifierStatus, { label: string; tone: string; why: string }> = {
  robust_edge: { label: "稳", tone: "text-emerald-400", why: "统计上站得住，三关全过" },
  underpowered: { label: "数据不够", tone: "text-amber-400", why: "样本少，待积累（不是没效果，是测不了）" },
  falsified: { label: "证否", tone: "text-red-400", why: "方向反了或不如随机" },
  not_validated: { label: "弱信号", tone: "text-gray-400", why: "有方向但没到门槛（不是没效果，是没够强）" },
  exploratory: { label: "不能定论", tone: "text-gray-400", why: "角度间矛盾或依赖假设，下不了结论" },
};

// 角度① 对冲版子结论→人话
const EVENT_STATUS_HUMAN: Record<EventStatus, { label: string; tone: string }> = {
  event_robust: { label: "稳（价差够强够显著）", tone: "text-emerald-400" },
  event_thin_positive: { label: "弱正（方向对但不够显著）", tone: "text-amber-400" },
  event_falsified: { label: "证否（价差反了或扣成本后为负）", tone: "text-red-400" },
  event_not_tested: { label: "没测", tone: "text-gray-400" },
};

// 选股准不准倍数→人话（>2 稳，1-2 弱，<1 不如随机）
function liftHuman(lift: number | null): { label: string; tone: string } {
  if (lift == null) return { label: "—", tone: "text-gray-400" };
  if (lift >= 2) return { label: `${lift.toFixed(2)}× 稳`, tone: "text-emerald-400" };
  if (lift >= 1) return { label: `${lift.toFixed(2)}× 弱`, tone: "text-amber-400" };
  return { label: `${lift.toFixed(2)}× 不如随机`, tone: "text-red-400" };
}

// 从 API records 组装 bundle（实验 ID 过滤 + 角色分组 + 退市档位分组）
// 当前后端 long_value_run.py 未实现→空→降级 mock
function assembleBundle(records: readonly RecorderRecord[]): S171ValueBundle | null {
  const s171 = records.filter((r) => r.params?.experiment_id === "S171");
  if (s171.length < 4) return null; // 至少 4 条（2 角度 × 2 档）才算真
  // TODO: 按 co_primary_role + delisting_return 分组组装（真 run 落地后补）
  return null;
}

export function S171ValueVerdict() {
  const [tier, setTier] = useState<-0.5 | -1.0>(-0.5);
  const { data, isLoading, error } = useVerifierRecords();

  // honest fallback：后端未就绪/不够 → mock + 徽标（不 break UI）
  const realBundle = data ? assembleBundle(data) : null;
  const bundle: S171ValueBundle = realBundle ?? s171ValueMock;
  const isMock = !realBundle;

  const combined = STATUS_HUMAN[bundle.combined_status];
  const t1 = bundle.sensitivity_rows[0];  // -0.5
  const t2 = bundle.sensitivity_rows[1];  // -1.0
  const activeRow: S171SensitivityRow = tier === -0.5 ? t1 : t2;
  const flip = t1.combined !== t2.combined;  // 两档结论是否翻转

  // 当前档的 4 条 record
  const p1 = tier === -0.5 ? bundle.co_primary_1_tier1 : bundle.co_primary_1_tier2;
  const p2 = tier === -0.5 ? bundle.co_primary_2_tier1 : bundle.co_primary_2_tier2;

  return (
    <div className="space-y-5 p-4 max-w-6xl mx-auto">
      {/* ── 头部：标题 + 综合结论 + mock 徽标 ── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold">价值因子月度验证</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            低 PE 价值股 vs 高 PE 成长股，月底调仓持 1 月——A 股的价值溢价（value premium）成不成立
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isLoading && <span className="text-xs text-muted-foreground">加载中…</span>}
          {error && !isLoading && (
            <span className="text-xs text-red-400">后端未就绪，显示 mock</span>
          )}
          {isMock && !isLoading && (
            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400">
              MOCK · 待 long_value_run.py 跑出
            </span>
          )}
          {!isMock && (
            <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-400">LIVE</span>
          )}
        </div>
      </div>

      {/* ── 综合结论条 ── */}
      <GlassCard className="p-4">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm text-muted-foreground">综合结论</span>
          <span className={cn("text-2xl font-bold", combined.tone)}>{combined.label}</span>
          <span className="text-sm text-muted-foreground">— {combined.why}</span>
        </div>
        <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
          综合结论 = 三关全过才"稳"。当前：第一关（两角度方向一致）{bundle.gates.cross_check.passed ? "✓过" : "✗不过"} ·
          第二关（退市档不翻结论）{bundle.gates.sensitivity.passed ? "✓过" : "✗不过"} ·
          第三关（退市数据够）{bundle.gates.coverage.passed ? "✓过" : "✗不过"}
        </p>
      </GlassCard>

      {/* ── 三问 KPI：稳不稳 / 能信不 / 能交易不 ── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <KpiTile
          title="稳不稳"
          value={combined.label}
          tone={combined.tone}
          why={combined.why}
          sub={`有效月数 ${p1.verdict.days_robust}（≥60 才够）`}
        />
        <KpiTile
          title="能信不"
          value={isMock ? "待实跑复算" : "复算一致"}
          tone={isMock ? "text-amber-400" : "text-emerald-400"}
          why={isMock ? "long_value_run.py 还没跑，当前是按 spec 设计的代表性场景" : "每条 verdict 重算结果一致"}
          sub={`不可外推警告 ${bundle.extrapolation_warnings.length} 条`}
        />
        <KpiTile
          title="能交易不"
          value="只做多能做"
          tone="text-emerald-400"
          why="角度②只做多低 PE 可实际交易；角度①对冲版要做空 A 股难"
          sub={`实盘须避开 *ST（验证含，实盘剔）`}
        />
      </div>

      {/* ── 不可外推警告（hero，verdict 之前，不折叠）── */}
      <GlassCard className="p-4 border-l-2 border-amber-500/40">
        <div className="text-sm font-semibold text-amber-400 mb-2">⚠ 这些结论不能往外推</div>
        <ul className="space-y-1.5">
          {bundle.extrapolation_warnings.map((w, i) => (
            <li key={i} className="text-xs text-muted-foreground leading-relaxed">
              <span className="text-amber-400/70 mr-1">{i + 1}.</span>{w}
            </li>
          ))}
        </ul>
      </GlassCard>

      {/* ── 退市档切换（杀手交互：切一次就懂"结论依赖退市假设"）── */}
      <GlassCard className="p-4">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
          <div>
            <div className="text-sm font-semibold">退市股按亏多少算？</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              退市股实际亏 50%~90%（老三板），假设不同结论可能翻——切一下看看
            </div>
          </div>
          <div className="flex gap-1.5">
            <TierBtn active={tier === -0.5} onClick={() => setTier(-0.5)} label="亏一半（温和）" />
            <TierBtn active={tier === -1.0} onClick={() => setTier(-1.0)} label="归零（保守）" />
          </div>
        </div>
        {flip && (
          <div className={cn(
            "rounded px-3 py-1.5 text-xs",
            tier === -1.0 ? "bg-red-500/10 text-red-400" : "bg-amber-500/10 text-amber-400",
          )}>
            ⚠ 两档结论翻车：{STATUS_HUMAN[t1.combined].label}（亏一半）→ {STATUS_HUMAN[t2.combined].label}（归零）。
            结论依赖"退市亏多少"这个假设，不能当稳的用。
          </div>
        )}
        {!flip && (
          <div className="rounded bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-400">
            ✓ 两档结论一致——结论不依赖退市损失假设
          </div>
        )}
      </GlassCard>

      {/* ── 两个角度对照（3 栏 ① | 关 | ②）── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto_1fr] gap-3 items-stretch">
        {/* 角度① 对冲版 */}
        <GlassCard className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold">角度① 对冲版</span>
            <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-400">做多低 PE + 做空高 PE</span>
          </div>
          <p className="text-xs text-muted-foreground mb-3 leading-relaxed">
            看价差收益（价值-成长，市场涨跌抵消）。正宗 Fama-French HML 测法，但 A 股做空难。
          </p>
          <EventMetricsPanel row={activeRow} record={p1} />
          <div className="mt-3 rounded bg-amber-500/10 px-2 py-1 text-[11px] text-amber-400">
            ⚠ 不能直接交易：A 股做空（融券）难又贵，这是测"价值溢价是否存在"不是"能赚多少"
          </div>
        </GlassCard>

        {/* 中间：第一关判定 */}
        <GlassCard className="p-3 flex flex-col items-center justify-center min-w-[140px]">
          <GateDot gate={bundle.gates.cross_check} />
          <div className="text-[10px] text-muted-foreground text-center mt-1.5 leading-tight">
            第一关<br />两角度<br />方向一致?
          </div>
        </GlassCard>

        {/* 角度② 只做多版 */}
        <GlassCard className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold">角度② 只做多版</span>
            <span className="rounded bg-orange-500/10 px-1.5 py-0.5 text-[10px] text-orange-400">低 PE 跑赢全市场</span>
          </div>
          <p className="text-xs text-muted-foreground mb-3 leading-relaxed">
            只买低 PE，看能不能跑赢全市场平均。能实际交易，但"选股准不准"倍数对价值结构性偏低。
          </p>
          <SelectionMetricsPanel row={activeRow} record={p2} />
          <div className="mt-3 rounded bg-amber-500/10 px-2 py-1 text-[11px] text-amber-400">
            ⚠ 弱信号≠无 edge：选股倍数对价值永远到不了 2×（价值股赢的频率不高但平均赢更多）。
            把角度②"弱信号"读成"价值无 edge"是外推越界。
          </div>
        </GlassCard>
      </div>

      {/* ── 第二关 + 第三关（纵向决策流续）── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <GlassCard className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <GateDot gate={bundle.gates.sensitivity} small />
            <span className="text-sm font-semibold">第二关：退市档不翻结论</span>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">{bundle.gates.sensitivity.detail}</p>
          <div className="mt-2 text-[11px] text-muted-foreground space-y-0.5">
            <div>亏一半 → {STATUS_HUMAN[t1.combined].label}（角度①{EVENT_STATUS_HUMAN[t1.primary_1_event_status].label}，角度②{liftHuman(t1.primary_2_lift).label}）</div>
            <div>归零 → {STATUS_HUMAN[t2.combined].label}（角度①{EVENT_STATUS_HUMAN[t2.primary_1_event_status].label}，角度②{liftHuman(t2.primary_2_lift).label}）</div>
          </div>
        </GlassCard>

        <GlassCard className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <GateDot gate={bundle.gates.coverage} small />
            <span className="text-sm font-semibold">第三关：退市数据够不够</span>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">{bundle.gates.coverage.detail}</p>
          <CoverageMeter audit={bundle.coverage_audit} />
        </GlassCard>
      </div>

      {/* ── 9 个 bug 诚实标注（全可见，不藏 tooltip）── */}
      <GlassCard className="p-4">
        <div className="text-sm font-semibold mb-1">数据可信：9 个坑修了没</div>
        <p className="text-xs text-muted-foreground mb-3">
          诚实标注，不藏折叠——每个 bug 是否修/验/标注，severity 色边（红=承重 / 琥珀=重要 / 灰=潜在）
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
          {bundle.bug_fixes.map((b) => <BugFixCard key={b.id} bug={b} />)}
        </div>
      </GlassCard>

      {/* ── caveat + 留待因子 ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <GlassCard className="p-4">
          <div className="text-sm font-semibold mb-2">其他注意</div>
          <ul className="space-y-1">
            {bundle.caveats.map((c, i) => (
              <li key={i} className="text-xs text-muted-foreground leading-relaxed">· {c}</li>
            ))}
          </ul>
        </GlassCard>
        <GlassCard className="p-4">
          <div className="text-sm font-semibold mb-2">留待以后</div>
          <ul className="space-y-1">
            {bundle.deferred_factors.map((f, i) => (
              <li key={i} className="text-xs text-muted-foreground leading-relaxed">· {f}</li>
            ))}
          </ul>
          <div className="mt-2 text-[11px] text-muted-foreground border-t border-border pt-2">
            {bundle.st_separation.verification}<br />{bundle.st_separation.capture}
          </div>
        </GlassCard>
      </div>

      {/* ── footer 注明 mock ── */}
      {isMock && (
        <div className="text-[11px] text-muted-foreground text-center pb-2">
          mock 数据按 S171 spec §6 设计的代表性场景（双角度矛盾 → 不能定论）。真实 verdict 由
          backend/tools/long_value_run.py 跑出后落 Recorder，UI 经 /api/verifier/records 读真实值替换。
        </div>
      )}
    </div>
  );
}

// ── 子件 ──

function KpiTile({ title, value, tone, why, sub }: {
  title: string; value: string; tone: string; why: string; sub: string;
}) {
  return (
    <GlassCard className="p-4">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className={cn("text-2xl font-bold mt-1", tone)}>{value}</div>
      <div className="text-xs text-muted-foreground mt-1 leading-relaxed">{why}</div>
      <div className="text-[11px] text-muted-foreground mt-1.5">{sub}</div>
    </GlassCard>
  );
}

function TierBtn({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded px-2.5 py-1 text-xs transition-colors",
        active ? "bg-blue-500/20 text-blue-300" : "bg-muted/40 text-muted-foreground hover:bg-muted/60",
      )}
    >
      {label}
    </button>
  );
}

function GateDot({ gate, small }: { gate: S171GateResult; small?: boolean }) {
  const color = gate.severity === "good" ? "bg-emerald-400" : gate.severity === "warning" ? "bg-amber-400" : "bg-red-400";
  const size = small ? "h-3 w-3" : "h-4 w-4";
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn("rounded-full inline-block", size, color, gate.passed ? "" : "opacity-40")} />
      {!small && <span className={cn("text-sm font-medium", gate.severity === "good" ? "text-emerald-400" : gate.severity === "warning" ? "text-amber-400" : "text-red-400")}>{gate.label}</span>}
    </div>
  );
}

function EventMetricsPanel({ row, record }: { row: S171SensitivityRow; record: RecorderRecord }) {
  const es = EVENT_STATUS_HUMAN[row.primary_1_event_status];
  const em = record.verdict.event_metrics;
  return (
    <div className="space-y-1.5 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">子结论</span>
        <span className={cn("font-medium", es.tone)}>{es.label}</span>
      </div>
      <MetricRow label="价差月均（扣成本后）" value={em?.net_mean != null ? `${(em.net_mean * 100).toFixed(3)}%` : "—"} />
      <MetricRow label="月均（毛）" value={em?.mean_return != null ? `${(em.mean_return * 100).toFixed(3)}%` : "—"} />
      <MetricRow label="显著性 t 值" value={em?.t_stat_day_clustered != null ? em.t_stat_day_clustered.toFixed(2) : "—"} hint="<1.96 不显著" />
      <MetricRow label="胜率" value={em?.win_rate != null ? `${(em.win_rate * 100).toFixed(1)}%` : "—"} />
      <MetricRow label="校正后 p 值" value={record.verdict.p_bonferroni != null ? record.verdict.p_bonferroni.toFixed(3) : "—"} hint="<0.05 才显著" />
    </div>
  );
}

function SelectionMetricsPanel({ row, record }: { row: S171SensitivityRow; record: RecorderRecord }) {
  const lift = liftHuman(row.primary_2_lift);
  const params = record.params as Record<string, unknown>;
  return (
    <div className="space-y-1.5 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">子结论</span>
        <span className={cn("font-medium", lift.tone)}>{lift.label}</span>
      </div>
      <MetricRow label="选股倍数 lift" value={row.primary_2_lift != null ? `${row.primary_2_lift.toFixed(2)}×` : "—"} hint=">2 稳，1-2 弱" />
      <MetricRow label="95% 置信区间" value={record.verdict.ci_low != null ? `[${record.verdict.ci_low.toFixed(2)}, ${record.verdict.ci_high!.toFixed(2)}]` : "待 v2"} />
      <MetricRow label="样本外 PurgedKFold" value={params.purged_kfold_lift != null ? `${Number(params.purged_kfold_lift).toFixed(2)}×` : "—"} hint="防过拟合" />
      <MetricRow label="样本外 walk-forward" value={params.walk_forward_lift != null ? `${Number(params.walk_forward_lift).toFixed(2)}×` : "—"} hint="历史训未来测" />
    </div>
  );
}

function MetricRow({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">
        {label}
        {hint && <span className="text-[10px] text-muted-foreground/60 ml-1">({hint})</span>}
      </span>
      <span className="font-mono text-foreground">{value}</span>
    </div>
  );
}

function CoverageMeter({ audit }: { audit: S171ValueBundle["coverage_audit"] }) {
  const lenientPct = Math.round(audit.lenient_pct * 100);
  const strictPct = Math.round(audit.strict_pct * 100);
  const zeroPct = audit.total_delisted > 0 ? Math.round((audit.zero_bars_count / audit.total_delisted) * 100) : 0;
  return (
    <div className="space-y-2 mt-2">
      <MeterBar label="宽松（至少有 K 线）" pct={lenientPct} threshold={50} />
      <MeterBar label="严格（完整覆盖）" pct={strictPct} threshold={50} />
      <div className="text-[11px] text-muted-foreground leading-relaxed pt-1">
        退市股 {audit.total_delisted} 只，其中 {audit.zero_bars_count} 只（{zeroPct}%）一根 K 线都没有——
        这批是极端 value trap，缺失导致 <span className="text-amber-400">价值溢价被高估</span>。
      </div>
    </div>
  );
}

function MeterBar({ label, pct, threshold }: { label: string; pct: number; threshold: number }) {
  const pass = pct >= threshold;
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-0.5">
        <span className="text-muted-foreground">{label}</span>
        <span className={cn("font-mono", pass ? "text-emerald-400" : "text-red-400")}>{pct}%</span>
      </div>
      <div className="relative h-2 rounded bg-muted/40 overflow-hidden">
        <div
          className={cn("h-full rounded", pass ? "bg-emerald-500/60" : "bg-red-500/60")}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
        <div className="absolute top-0 bottom-0 w-px bg-amber-400/80" style={{ left: `${threshold}%` }} />
      </div>
    </div>
  );
}

function BugFixCard({ bug }: { bug: S171ValueBundle["bug_fixes"][number] }) {
  const sevColor = bug.severity === "critical" ? "border-l-red-500/60" : bug.severity === "high" ? "border-l-amber-500/60" : "border-l-gray-500/40";
  const statusBadge = {
    fixed: { label: "已修", tone: "bg-emerald-500/10 text-emerald-400" },
    pending: { label: "未验", tone: "bg-amber-500/10 text-amber-400" },
    annotated: { label: "已标注", tone: "bg-gray-500/10 text-gray-400" },
  }[bug.status];
  return (
    <div className={cn("rounded border border-l-2 border-border p-2", sevColor)}>
      <div className="flex items-center justify-between gap-1.5 mb-0.5">
        <span className="text-xs font-medium">#{bug.id} {bug.title}</span>
        <span className={cn("rounded px-1 py-0.5 text-[9px]", statusBadge.tone)}>{statusBadge.label}</span>
      </div>
      <div className="text-[10px] text-muted-foreground leading-relaxed">
        <span className="text-red-400/70">错：</span>{bug.detail}
      </div>
      <div className="text-[10px] text-muted-foreground leading-relaxed mt-0.5">
        <span className="text-emerald-400/70">修：</span>{bug.fix}
      </div>
    </div>
  );
}
