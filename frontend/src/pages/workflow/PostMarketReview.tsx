// S054 R3：盘后复盘去桩重写——三问（推了什么/买了什么/漏了什么）+ 昨日漏单结算 + 结算入口。
// 沿用 WorkflowStage 壳；调 useDailyWinReview + deriveAssessmentTips 研判嵌入。
// Q7：bought 占位「待判定」，不展示 live 临时票根；Q5：三问页嵌方向建议。
import { useState } from "react";
import { Link } from "react-router-dom";
import { WorkflowStage } from "./components/WorkflowStage";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { VerificationCardBlock } from "@/components/workflow/VerificationCardBlock";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { PipelineProgressBar } from "@/components/workflow/PipelineProgressBar";
import { WeatherDecisionBar } from "@/components/workflow/WeatherDecisionBar";
import { ForwardTestPanel } from "@/components/workflow/ForwardTestPanel";
import { useDailyWinReview, useShadowComparison, useTransitionWorkflowState, usePreMarketBriefing } from "@/lib/query";
import { deriveAssessmentTips } from "@/lib/winrate-assessment";
import type { TransitionRequest } from "@/lib/api";

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
  // S063 T27：读盘前简报取 sentiment_context（T+1 准备面板复用 T-1 天气）
  const { data: briefing } = usePreMarketBriefing(date);
  // 研判用 shadow-comparison window=28（daily-review 无 shadow 数据时兜底）
  const { data: shadow } = useShadowComparison(28);
  const transition = useTransitionWorkflowState();
  const [entryCode, setEntryCode] = useState<string | null>(null);

  const tips = shadow ? deriveAssessmentTips(shadow) : [];

  const handleEntrySubmit = (req: TransitionRequest) => {
    transition.mutate(req);
    setEntryCode(null);
  };

  // 问 AI 上下文——注入盘后复盘真实数据
  const pmrCtx = briefing?.sentiment_context;
  const askAiContext = [
    `当前页面：盘后复盘`,
    `日期：${review?.date ?? date ?? "未取得"}`,
    review?.no_snapshot
      ? `三问：无盘前快照`
      : `三问：推了${review?.pushed.length ?? 0}只（${(review?.pushed ?? []).map((p) => p.code).join("、") || "无"}）/买了${review?.bought.length ?? 0}只（${(review?.bought ?? []).map((b) => b.code).join("、") || "无"}）/漏了${review?.missed.length ?? 0}只（${(review?.missed ?? []).map((m) => m.code).join("、") || "无"}）`,
    review?.prev_day_missed
      ? `昨日漏单：${review.prev_day_missed.items.length}只${review.prev_day_missed.summary ? `（胜率${review.prev_day_missed.summary.win_rate}%/均收益${review.prev_day_missed.summary.avg_return}）` : ""}`
      : `昨日漏单：未取得`,
    pmrCtx
      ? `情绪天气：${pmrCtx.weather_state}，STI=${pmrCtx.sti_score ?? "--"}（${pmrCtx.sti_phase ?? "--"}）`
      : `情绪天气：未取得`,
    shadow
      ? `影子对照（${shadow.window_days}日）：跟随${shadow.follow.n}笔胜率${shadow.follow.win_rate ?? "--"}%/感觉${shadow.feeling.n}笔/漏单${shadow.missed.n}笔，独立一致率${shadow.independence.agreement_rate ?? "--"}%`
      : `影子对照：未取得`,
  ].join("\n");

  return (
    <WorkflowStage title="盘后复盘" subtitle="Post-Market Review" loading={isLoading} actions={<AskAiButton context={askAiContext} />}>
      {/* S063 T27：Pipeline 进度条（盘后阶段高亮） */}
      <div className="mb-4">
        <PipelineProgressBar current="post" />
      </div>

      {/* S063 T27：当日 STI 结算条（T vs T-1 天气对比） */}
      {briefing?.sentiment_context && (
        <div className="mb-4">
          <SectionHeader title="当日情绪结算" subtitle="T-1 天气硬标准（次日硬标准已生成）" />
          <div className="mt-2">
            <WeatherDecisionBar ctx={briefing.sentiment_context} />
          </div>
        </div>
      )}

      {/* S066 §0e 前向测试命中率 + 衰减监控（盘后追踪推荐 vs 实际） */}
      <div className="mb-6">
        <ForwardTestPanel />
      </div>

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
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-medium">② 你买了什么</p>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEntryCode("manual")}
                >
                  + 录入今日买入
                </Button>
              </div>
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
              {entryCode && (
                <div className="mt-3">
                  <p className="mb-2 text-xs text-muted-foreground">
                    录入 {date} 新建仓（target=holding）
                  </p>
                  <ManualEntryForm
                    date={date}
                    submitting={transition.isPending}
                    onSubmit={handleEntrySubmit}
                    onCancel={() => setEntryCode(null)}
                  />
                </div>
              )}
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
                {tips.map((t) => (
                  <li key={t.slice(0, 20)} className="text-xs text-foreground/90">
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
              {TEACHING_POINTS.map((t) => (
                <li key={t.slice(0, 16)} className="text-[11px] text-muted-foreground/80">
                  · {t}
                </li>
              ))}
            </ul>

            {/* S060：当晚新生成的条件预览 */}
            <div className="mt-3">
              <VerificationCardBlock />
            </div>
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

/** 手动录入建仓表单——code/name/entry_price + target=holding，调 transitionWorkflowState。 */
function ManualEntryForm({
  date,
  submitting,
  onSubmit,
  onCancel,
}: {
  date: string;
  submitting: boolean;
  onSubmit: (req: TransitionRequest) => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [entryPrice, setEntryPrice] = useState("");
  const [strategy, setStrategy] = useState("");

  const handleSubmit = () => {
    if (!code.trim()) return;
    const ep = entryPrice.trim() ? Number(entryPrice) : undefined;
    onSubmit({
      code: code.trim(),
      date,
      target: "holding",
      reason: name.trim() || undefined,
      entry_price: Number.isFinite(ep) ? ep : undefined,
      strategy: strategy || undefined,
    });
  };

  return (
    <div className="space-y-2 rounded-lg border border-border/40 bg-muted/20 p-3">
      <div className="flex gap-2">
        <input
          className="flex-1 rounded border border-border/50 bg-background px-2 py-1 text-xs"
          placeholder="股票代码（如 600519）"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <input
          className="flex-1 rounded border border-border/50 bg-background px-2 py-1 text-xs"
          placeholder="名称（可选）"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <input
          className="flex-1 rounded border border-border/50 bg-background px-2 py-1 text-xs"
          placeholder="买入价（可选）"
          inputMode="decimal"
          value={entryPrice}
          onChange={(e) => setEntryPrice(e.target.value)}
        />
        <select
          className="flex-1 rounded border border-border/50 bg-background px-2 py-1 text-xs"
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
        >
          <option value="">战法（可选）</option>
          <option value="first_plate">首板挖掘</option>
          <option value="consecutive_relay">连板接力</option>
          <option value="break_reseal">炸板回封</option>
          <option value="low_absorption">低吸龙头</option>
          <option value="reverse_package">反包战法</option>
          <option value="n_shape_counterattack">N字反击</option>
          <option value="platform_breakout">平台突破</option>
          <option value="end_of_day_sneak">尾盘偷袭</option>
        </select>
      </div>
      <div className="flex gap-2 pt-1">
        <Button size="sm" onClick={handleSubmit} disabled={submitting || !code.trim()}>
          确认录入
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={submitting}>
          取消
        </Button>
      </div>
    </div>
  );
}
