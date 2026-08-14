// S050 W0：行为闭环独立页——票根 + 影子对照 + 独立性基线。
// 与工作流解耦：不依赖盘前简报采集态，直接调 /api/winrate/shadow-comparison。
// 弱合规定位（私人投研助理）：可给方向性研判建议，保留工程底线（不臆造/可复现）。
import { useState } from "react";
import { ChevronDown, ChevronRight, Info, Lightbulb } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { useShadowComparison } from "@/lib/query";
import { deriveAssessmentTips } from "@/lib/winrate-assessment";
import type { ShadowComparison, ShadowBucket } from "@/lib/api/types";
import { AskAiButton } from "@/components/ui/AskAiButton";

const WINDOW_OPTIONS = [14, 28, 60] as const;

export default function BehaviorLoop() {
  const [windowDays, setWindowDays] = useState(28);
  const { data, isLoading, error, refetch } = useShadowComparison(windowDays);

  // S066 AskAi：注入影子对照三桶 + 独立性
  const askAiContext = [
    `当前页面：行为闭环（BehaviorLoop）`,
    `观察窗口：${windowDays} 天`,
    data ? `跟随单：${data.follow.n}笔/胜率${data.follow.win_rate != null ? (data.follow.win_rate * 100).toFixed(1) + "%" : "未取得"}/平均收益${data.follow.avg_return != null ? data.follow.avg_return.toFixed(2) + "%" : "未取得"}` : `影子对照：未取得`,
    data ? `感觉单：${data.feeling.n}笔/胜率${data.feeling.win_rate != null ? (data.feeling.win_rate * 100).toFixed(1) + "%" : "未取得"}` : ``,
    data ? `漏掉单：${data.missed.n}笔/胜率${data.missed.win_rate != null ? (data.missed.win_rate * 100).toFixed(1) + "%" : "未取得"}${data.missed.missing_kline ? `(缺K线${data.missed.missing_kline})` : ""}` : ``,
    data?.independence ? `独立性：一致率${data.independence.agreement_rate != null ? (data.independence.agreement_rate * 100).toFixed(1) + "%" : "未取得"}/感觉单胜率${data.independence.feeling_win_rate != null ? (data.independence.feeling_win_rate * 100).toFixed(1) + "%" : "未取得"}` : ``,
  ].filter(Boolean).join("\n");

  return (
    <div>
      <PageHeader
        title="行为闭环"
        subtitle="Behavior Loop · W0 票根 + 影子对照 + 独立性基线"
        actions={<AskAiButton context={askAiContext} />}
      />

      {/* 观察期说明 */}
      <GlassCard className="mb-4 p-4">
        <div className="flex items-start gap-2">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="text-sm text-muted-foreground">
            <p>
              W0 把行为测出来：每笔结算关联系统信号（候选/战法）或显式标「感觉单」，
              系统建议单 vs 用户实际单并排算账，含「漏掉候选」的影子收益。
              数据积累后给方向性研判，仍由你最终决策。
            </p>
            <p className="mt-1">
              ≥4 周观察期样本更稳；当前窗口数据已有研判参考价值，样本不足时会诚实标注。
            </p>
          </div>
        </div>
      </GlassCard>

      {/* 窗口选择 */}
      <div className="mb-4 flex items-center gap-2">
        <span className="text-sm text-muted-foreground">观察窗口</span>
        {WINDOW_OPTIONS.map((w) => (
          <button
            key={w}
            type="button"
            onClick={() => setWindowDays(w)}
            className={
              "rounded-lg px-3 py-1.5 text-sm transition-colors " +
              (windowDays === w
                ? "bg-primary text-primary-foreground"
                : "bg-muted/40 text-muted-foreground hover:bg-muted/60")
            }
          >
            {w} 天
          </button>
        ))}
        <button
          type="button"
          onClick={() => refetch()}
          className="ml-auto text-sm text-muted-foreground hover:text-primary"
        >
          刷新
        </button>
      </div>

      {isLoading && <Skeleton variant="rectangular" className="h-64" />}

      {error && (
        <GlassCard className="border border-warning/30 p-4">
          <p className="text-sm text-warning">影子对照取数失败：{String(error?.message ?? error)}</p>
        </GlassCard>
      )}

      {data && <ShadowReport data={data} />}
    </div>
  );
}

/** 三桶算账 + 独立性指标 + 行为研判。 */
function ShadowReport({ data }: { data: ShadowComparison }) {
  return (
    <>
      {/* 概览指标卡 */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <OverviewCard
          label="一致率"
          value={data.independence.agreement_rate != null
            ? `${(data.independence.agreement_rate * 100).toFixed(1)}%`
            : "—"}
          hint="follow / (follow + feeling)"
        />
        <OverviewCard
          label="feeling 胜率"
          value={data.independence.feeling_win_rate != null
            ? `${(data.independence.feeling_win_rate * 100).toFixed(1)}%`
            : "—"}
          hint="感觉单历史胜率"
        />
        <OverviewCard
          label="观察窗口"
          value={`${data.window_days} 天`}
          hint={`无建议日 ${data.no_suggestion_days}`}
        />
        <OverviewCard
          label="样本充足性"
          value={data.sufficient ? "充足" : "不足"}
          hint={data.sufficient ? "三桶均 ≥5" : "三桶任一 <5，研判仅供参考"}
          warn={!data.sufficient}
        />
      </div>

      {/* 行为研判（弱合规：可给方向性建议，数据驱动非臆造） */}
      <BehaviorAssessment data={data} />

      {/* 三桶算账表 */}
      <div className="mb-6">
        <SectionHeader title="三桶算账" subtitle="follow（跟系统）/ feeling（感觉单）/ missed（漏掉候选影子）" />
        <GlassCard className="p-4">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground">
                  <th className="py-2 pr-4">桶</th>
                  <th className="py-2 pr-4">N</th>
                  <th className="py-2 pr-4">胜率</th>
                  <th className="py-2 pr-4">均收益</th>
                  <th className="py-2">说明</th>
                </tr>
              </thead>
              <tbody>
                <BucketRow label="跟系统（follow）" b={data.follow} note="signal_source ∈ funnel_candidate / strategy_hit" />
                <BucketRow label="感觉单（feeling）" b={data.feeling} note="signal_source = feeling（快照与战法均未命中）" />
                <BucketRow label="漏掉候选（missed）" b={data.missed} note={data.missed.approx_note} />
              </tbody>
            </table>
          </div>
          {data.missed.missing_kline > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              missed K 线缺失排除 {data.missed.missing_kline} 笔（不计入算账）
            </p>
          )}
          {data.no_suggestion_days > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              无系统建议日（无快照）{data.no_suggestion_days} 天（不计算 missed）
            </p>
          )}
        </GlassCard>
      </div>

      {/* 桶详解 */}
      <div className="mb-6 space-y-3">
        <SectionHeader title="桶详解" subtitle="每桶的语义与数据来源" />
        <BucketExplanation
          title="follow · 跟系统"
          code="signal_source ∈ (funnel_candidate, strategy_hit)"
          desc="用户实际买入且结算的标的中，当日快照 final_candidates 命中或战法回测 trades 命中的。代表「跟系统建议做」的行为。"
        />
        <BucketExplanation
          title="feeling · 感觉单"
          code="signal_source = feeling"
          desc="快照与战法 trades 均未命中，用户自行决策买入的。代表「凭感觉做」的行为。"
        />
        <BucketExplanation
          title="missed · 漏掉候选"
          code="快照 final_candidates − 当日 holding/settled codes"
          desc="系统建议了但用户未买入的标的，用 close-to-close 影子收益估算「如果跟了会怎样」。近似口径，与 S047 证据基线同口径。"
        />
      </div>

      <Disclaimer />
    </>
  );
}

/** 行为研判：基于三桶算账给方向性建议（弱合规定位，数据驱动非臆造）。 */
function BehaviorAssessment({ data }: { data: ShadowComparison }) {
  const tips = _deriveAssessmentTips(data);
  if (tips.length === 0) return null;
  return (
    <GlassCard className="mb-6 border border-primary/20 p-4">
      <div className="mb-2 flex items-center gap-2">
        <Lightbulb className="h-4 w-4 text-primary" />
        <span className="font-medium">行为研判</span>
        {!data.sufficient && (
          <span className="text-xs text-muted-foreground">· 样本不足，仅供参考</span>
        )}
      </div>
      <ul className="space-y-1.5">
        {tips.map((t) => (
          <li key={t.slice(0, 20)} className="flex items-start gap-2 text-sm">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
            <span className="text-foreground/90">{t}</span>
          </li>
        ))}
      </ul>
    </GlassCard>
  );
}

/** 从三桶数据派生研判建议（S054 R8 抽为共享纯函数，三页共用）。 */
const _deriveAssessmentTips = deriveAssessmentTips;

function OverviewCard({ label, value, hint, warn }: { label: string; value: string; hint: string; warn?: boolean }) {
  return (
    <GlassCard className="p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={"mt-1 text-2xl font-bold " + (warn ? "text-warning" : "")}>{value}</p>
      <p className="mt-1 text-xs text-muted-foreground/70">{hint}</p>
    </GlassCard>
  );
}

function BucketRow({ label, b, note }: { label: string; b: ShadowBucket; note: string }) {
  const pct = (v: number | null) => v != null ? `${(v * 100).toFixed(1)}%` : "—";
  const num = (v: number | null) => v != null ? `${v.toFixed(2)}%` : "—";
  return (
    <tr className="border-t border-border/30">
      <td className="py-2 pr-4 font-medium">{label}</td>
      <td className="py-2 pr-4 font-mono">{b.n}</td>
      <td className="py-2 pr-4 font-mono">{b.n > 0 ? pct(b.win_rate) : "—"}</td>
      <td className="py-2 pr-4 font-mono">{b.n > 0 ? num(b.avg_return) : "—"}</td>
      <td className="py-2 text-xs text-muted-foreground">{note}</td>
    </tr>
  );
}

function BucketExplanation({ title, code, desc }: { title: string; code: string; desc: string }) {
  const [open, setOpen] = useState(false);
  return (
    <GlassCard className="p-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        {open ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
        <span className="font-medium">{title}</span>
        <code className="ml-auto text-xs text-muted-foreground">{code}</code>
      </button>
      {open && <p className="mt-2 pl-6 text-sm text-muted-foreground">{desc}</p>}
    </GlassCard>
  );
}
