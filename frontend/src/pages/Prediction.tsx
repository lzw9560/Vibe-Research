// 短线预测工作台（S017 T12-T14）。
// 合规（CLAUDE.md §1）：
//   - 首次进入须过免责墙 opt-in（「研究参考·不构成投资建议」），存 localStorage。
//   - 所有概率旁挂研究参考 chip；S4 盘中框架为教育性「看什么/怎么判」清单，
//     无信号、无买入/卖出/止损/止盈按钮，仅客观值 + 教育提示 + 用户自标状态。

import { useEffect, useState, useCallback } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AlertTriangle, Clock, Gauge, ListChecks, ShieldCheck } from "lucide-react";
import {
  fetchIntradayFramework,
  fetchPrediction,
  isDisclaimerAccepted,
  acceptDisclaimer,
  type PredictionEnvelope,
  type IntradayFrameworkEnvelope,
} from "@/lib/prediction";

const STAGES = [
  { key: "s1", label: "S1 收盘后", desc: "T-1 收盘后大部分特征解锁" },
  { key: "s2", label: "S2 开盘前", desc: "+ 隔夜 A50/美股/美债" },
  { key: "s3", label: "S3 竞价", desc: "9:15-9:25 竞价数据" },
] as const;

const RESEARCH_CHIP = "研究参考·不构成投资建议";

function DisclaimerWall({ onAccept }: { onAccept: () => void }) {
  return (
    <div className="mx-auto mt-10 max-w-xl">
      <GlassCard className="p-6">
        <div className="mb-3 flex items-center gap-2 text-amber-600 dark:text-amber-400">
          <ShieldCheck className="h-5 w-5" />
          <h2 className="text-base font-semibold">研究参考 · 免责声明</h2>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">
          本预测工作台基于<b>公开数据与历史统计特征</b>给出研究参考性的概率与研判框架，
          属教育研究性判断，<b>不构成投资建议</b>。系统不承诺收益、不代用户决策、不推送买卖指令。
          请独立核实、风险自担。
        </p>
        <div className="mt-5 flex justify-end">
          <Button onClick={onAccept}>我已知悉，进入工作台</Button>
        </div>
      </GlassCard>
    </div>
  );
}

function ProbChip() {
  return (
    <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
      {RESEARCH_CHIP}
    </span>
  );
}

function StageTimeline({ predictions }: { predictions: Record<string, PredictionEnvelope | null> }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {STAGES.map((s) => {
        const env = predictions[s.key];
        const prob = env?.data?.prob;
        return (
          <GlassCard key={s.key} className="p-4">
            <div className="mb-1 flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{s.label}</span>
            </div>
            <p className="mb-3 text-xs text-muted-foreground">{s.desc}</p>
            {env == null ? (
              <Skeleton className="h-8 w-full" />
            ) : env.status === "no_snapshot" || !env.data ? (
              <div className="flex h-8 items-center text-xs text-muted-foreground">
                快照待生成
              </div>
            ) : (
              <div className="flex items-end gap-2">
                <Gauge className="h-5 w-5 text-primary" />
                <span className="text-2xl font-semibold tabular-nums">
                  {(prob! * 100).toFixed(1)}%
                </span>
                <span className="pb-1 text-xs text-muted-foreground">上涨概率</span>
              </div>
            )}
            <div className="mt-2">
              <ProbChip />
            </div>
          </GlassCard>
        );
      })}
    </div>
  );
}

function ProbabilityEvolution({ predictions }: { predictions: Record<string, PredictionEnvelope | null> }) {
  const points = STAGES.map((s) => {
    const env = predictions[s.key];
    return env?.data?.prob ?? null;
  });
  const max = 1;
  return (
    <GlassCard className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <Gauge className="h-4 w-4 text-muted-foreground" />
        <SectionHeader title="概率演进 S1→S2→S3" />
      </div>
      <div className="flex items-end gap-4">
        {points.map((p, i) => (
          <div key={i} className="flex flex-1 flex-col items-center gap-1">
            <div className="flex h-32 w-full items-end">
              <div
                className="w-full rounded-t bg-primary/70"
                style={{ height: p == null ? "8%" : `${Math.max(4, (p / max) * 100)}%` }}
                title={p == null ? "待生成" : `${(p * 100).toFixed(1)}%`}
              />
            </div>
            <span className="text-[10px] text-muted-foreground">
              {p == null ? "—" : `${(p * 100).toFixed(1)}%`}
            </span>
            <span className="text-[10px] text-muted-foreground">{STAGES[i].key}</span>
          </div>
        ))}
      </div>
      <div className="mt-3"><ProbChip /></div>
    </GlassCard>
  );
}

function IntradayFramework({ data }: { data: IntradayFrameworkEnvelope | null }) {
  return (
    <GlassCard className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <ListChecks className="h-4 w-4 text-muted-foreground" />
        <SectionHeader title="S4 盘中研判框架（教育性）" />
        <Badge className="ml-auto">无信号 · 无交易指令</Badge>
      </div>
      <div className="space-y-3">
        {data == null
          ? Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))
          : data.items.map((it) => (
              <div key={it.key} className="rounded-lg border border-border/60 p-3">
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-sm font-medium">{it.label}</span>
                  <span className="text-xs text-muted-foreground">
                    当前值：{it.current_value == null ? "待 S008 live" : String(it.current_value)}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{it.how_to_read}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  <b>参考：</b>{it.reference}
                </p>
                <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">{it.hint}</p>
              </div>
            ))}
      </div>
      {data && (
        <div className="mt-3">
          <ProbChip />
        </div>
      )}
    </GlassCard>
  );
}

export function Prediction() {
  const [accepted, setAccepted] = useState(isDisclaimerAccepted());
  const [predictions, setPredictions] = useState<Record<string, PredictionEnvelope | null>>({
    s1: null, s2: null, s3: null,
  });
  const [framework, setFramework] = useState<IntradayFrameworkEnvelope | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [s1, s2, s3, fw] = await Promise.all([
        fetchPrediction("short_sector", "s1").catch(() => null),
        fetchPrediction("short_sector", "s2").catch(() => null),
        fetchPrediction("short_sector", "s3").catch(() => null),
        fetchIntradayFramework().catch(() => null),
      ]);
      setPredictions({ s1, s2, s3 });
      setFramework(fw);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    if (accepted) load();
  }, [accepted, load]);

  if (!accepted) {
    return (
      <div>
        <PageHeader title="预测工作台" subtitle="短线板块预测级联 + 盘中研判框架（教育研究性）" />
        <DisclaimerWall
          onAccept={() => {
            acceptDisclaimer();
            setAccepted(true);
          }}
        />
        <Disclaimer />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="预测工作台" subtitle="短线板块预测级联 + 盘中研判框架（教育研究性）" />
      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-600 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}
      <div className="space-y-4">
        <StageTimeline predictions={predictions} />
        <ProbabilityEvolution predictions={predictions} />
        <IntradayFramework data={framework} />
      </div>
      <Disclaimer />
    </div>
  );
}

export default Prediction;
