// S054 R3：盘后复盘去桩重写——三问（推了什么/买了什么/漏了什么）+ 昨日漏单结算 + 结算入口。
// 沿用 WorkflowStage 壳；调 useDailyWinReview + deriveAssessmentTips 研判嵌入。
// Q7：bought 占位「待判定」，不展示 live 临时票根；Q5：三问页嵌方向建议。
import { useState } from "react";
import { Link } from "react-router-dom";
import { WorkflowStage } from "./components/WorkflowStage";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { useDailyWinReview } from "@/lib/query";
import { deriveAssessmentTips } from "@/lib/winrate-assessment";
import { useShadowComparison } from "@/lib/query";

const TEACHING_POINTS = [
  "复盘的意义是迭代：每天回答三问，漏斗用你的真实数据校准",
  "票根标感觉单不是问责，是量出直觉值不值得留",
  "错过的成本是真实数字，不是感觉",
];

const EMPTY_STATES = {
  noSnapshot: "该日无盘前快照，无法回答三问",
  noBought: "当日无新建仓记录",
  noMissed: "当日无漏单（推了什么全买了或无推送）",
  noPrevMissed: "上一交易日无漏单或无快照",
};

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtSigned(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

export default function PostMarketReview() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const { data: review, isLoading } = useDailyWinReview(date);
  // 研判用 shadow-comparison window=28（daily-review 无 shadow 数据时兜底）
  const { data: shadow } = useShadowComparison(28);

  const tips = shadow ? deriveAssessmentTips(shadow) : [];

  return (
    <WorkflowStage title="盘后复盘" subtitle="Post-Market Review" loading={isLoading}>
      {/* 日期选择器 */}
      <div className="mb-4 flex items-center gap-2">
        <label className="text-xs text-muted-foreground">日期</label>
        <input
          type="date"
          value={date}
          max={today}
          onChange={(e) => setDate(e.target.value || today)}
          className="rounded border border-border/50 bg-background px-2 py-1 text-sm"
        />
      </div>

      {isLoading || !review ? (
        <div className="space-y-4">
          <Skeleton variant="rectangular" className="h-24" />
          <Skeleton variant="rounded" className="h-24" />
          <Skeleton variant="rounded" className="h-24" />
        </div>
      ) : review.no_snapshot ? (
        <GlassCard className="p-6">
          <p className="text-sm text-muted-foreground">{EMPTY_STATES.noSnapshot}</p>
        </GlassCard>
      ) : (
        <>
          {/* 三问区 */}
          <div className="mb-6 space-y-3">
            <SectionHeader title="复盘三问" subtitle="推了什么 / 买了什么 / 漏了什么" />

            {/* ① 系统推了什么 */}
            <GlassCard className="p-4">
              <p className="mb-2 text-sm font-medium">① 系统推了什么</p>
              {review.pushed.length === 0 ? (
                <p className="text-xs text-muted-foreground">当日无候选推送</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground">
                        <th className="px-2 py-1 text-left">代码</th>
                        <th className="px-2 py-1 text-left">名称</th>
                        <th className="px-2 py-1">基因分</th>
                        <th className="px-2 py-1">战法</th>
                      </tr>
                    </thead>
                    <tbody>
                      {review.pushed.map((p) => (
                        <tr key={p.code} className="border-t border-border/30">
                          <td className="px-2 py-1 font-mono">{p.code}</td>
                          <td className="px-2 py-1">{p.name}</td>
                          <td className="px-2 py-1 text-center">{p.gene_score ?? "—"}</td>
                          <td className="px-2 py-1 text-center">
                            {Array.isArray(p.strategies) && p.strategies.length > 0 ? p.strategies.join("，") : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </GlassCard>

            {/* ② 你买了什么 */}
            <GlassCard className="p-4">
              <p className="mb-2 text-sm font-medium">② 你买了什么</p>
              {review.bought.length === 0 ? (
                <p className="text-xs text-muted-foreground">{EMPTY_STATES.noBought}</p>
              ) : (
                <div className="space-y-2">
                  {review.bought.map((b) => (
                    <div key={b.code} className="flex items-center justify-between text-xs">
                      <span className="font-mono">{b.code}</span>
                      <span className="ml-2">{b.name}</span>
                      <span className="ml-2 text-muted-foreground">
                        买入价 {b.entry_price ?? "—"}
                      </span>
                      <span className="ml-2 rounded bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {b.placeholder}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-2 text-[10px] text-muted-foreground/70">
                占位标签「待判定」——结算后才显真票根，避免预判误导
              </p>
            </GlassCard>

            {/* ③ 漏了什么 */}
            <GlassCard className="p-4">
              <p className="mb-2 text-sm font-medium">③ 漏了什么</p>
              {review.missed.length === 0 ? (
                <p className="text-xs text-muted-foreground">{EMPTY_STATES.noMissed}</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {review.missed.map((m) => (
                    <span key={m.code} className="font-mono text-xs text-muted-foreground">
                      {m.code}
                    </span>
                  ))}
                </div>
              )}
              <p className="mt-2 text-[10px] text-muted-foreground/70">明日盘后补账</p>
            </GlassCard>
          </div>

          {/* 昨日漏的结算条 */}
          <div className="mb-6">
            <SectionHeader title="昨日漏的结算" subtitle="上一交易日漏单次日收益" />
            <GlassCard className="p-4">
              {review.prev_day_missed.items.length === 0 ? (
                <p className="text-xs text-muted-foreground">{EMPTY_STATES.noPrevMissed}</p>
              ) : (
                <>
                  <div className="space-y-2">
                    {review.prev_day_missed.items.map((it) => (
                      <div key={it.code} className="flex items-center justify-between text-xs">
                        <span className="font-mono">{it.code}</span>
                        <span className={it.next_day_return >= 0 ? "text-green-600" : "text-red-600"}>
                          {fmtSigned(it.next_day_return)}
                        </span>
                      </div>
                    ))}
                  </div>
                  {review.prev_day_missed.summary && (
                    <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
                      <span>共 {review.prev_day_missed.summary.n} 只</span>
                      <span>胜率 {fmtPct(review.prev_day_missed.summary.win_rate)}</span>
                      <span>均收益 {fmtSigned(review.prev_day_missed.summary.avg_return)}</span>
                      <span className="text-muted-foreground/70">
                        信号日 {review.prev_day_missed.summary.signal_date}
                      </span>
                    </div>
                  )}
                </>
              )}
              {review.missing_kline > 0 && (
                <p className="mt-2 text-[10px] text-muted-foreground/60">
                  {review.missing_kline} 只因 K 线缺失排除
                </p>
              )}
            </GlassCard>
          </div>

          {/* 结算入口卡 */}
          <div className="mb-6">
            <SectionHeader title="结算入口" subtitle="待结算持仓逐行去结算" />
            <GlassCard className="p-4">
              {review.bought.length === 0 ? (
                <p className="text-xs text-muted-foreground">无待结算持仓</p>
              ) : (
                <div className="space-y-2">
                  {review.bought.map((b) => (
                    <div key={b.code} className="flex items-center justify-between text-xs">
                      <span className="font-mono">{b.code}</span>
                      <span className="ml-2">{b.name}</span>
                      <Link
                        to={`/workflow/intraday?code=${b.code}&date=${date}`}
                        className="ml-2 text-primary hover:underline"
                      >
                        去结算 →
                      </Link>
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-2 text-[10px] text-muted-foreground/70">
                跳转既有状态机流转（S033/S034），含 attention_mode 选择
              </p>
            </GlassCard>
          </div>

          {/* 研判（Q5） */}
          {tips.length > 0 && (
            <GlassCard className="mb-6 border border-primary/20 p-4">
              <p className="mb-2 text-sm font-medium">行为研判</p>
              <ul className="space-y-1.5">
                {tips.map((t, i) => (
                  <li key={i} className="text-xs text-foreground/90">
                    · {t}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[10px] text-muted-foreground/60">
                研判基于 shadow-comparison window=28 近期行为模式
              </p>
            </GlassCard>
          )}

          {/* 教学点 */}
          <GlassCard className="mb-4 p-4">
            <p className="mb-2 text-xs font-medium text-muted-foreground">教学点</p>
            <ul className="space-y-1">
              {TEACHING_POINTS.map((t, i) => (
                <li key={i} className="text-[11px] text-muted-foreground/80">
                  · {t}
                </li>
              ))}
            </ul>
          </GlassCard>

          {/* 风险注记 */}
          <p className="text-[10px] text-muted-foreground/50">
            {review.disclaimer ?? "历史统计特征，市场有风险，研究参考"}
          </p>
        </>
      )}
    </WorkflowStage>
  );
}
