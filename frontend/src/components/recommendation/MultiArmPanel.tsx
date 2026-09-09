// S175 R9/R12 — 多臂推荐面板（替换 gene 卡，各臂 honest_label + floor sizing + 谋士 posture）。
// fetch GET /api/recommendation/multi-arm → 各臂 honest_label 卡（floor actionable + breakout §44证否
// + limitup/trend mock + gap dead）。actionable 臂显"可选实盘小仓位"，paper 臂显"不推荐真金"。
import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { authHeaders, ApiError } from "@/lib/api";

interface MultiArmRec {
  arm: string;
  honest_label: string;
  action_type: string;
  code: string | null;
  name: string | null;
  sizing_suggestion: string | null;
  coverage_rate: number | null;
  days_tracked: number | null;
  validated: boolean;
  note: string;
}

function verdictCls(label: string): string {
  if (label === "externally_validated") return "bg-blue-500/15 text-blue-600";
  if (label === "§44_falsified") return "bg-red-500/15 text-red-600";
  if (label === "dead_arm") return "bg-red-500/15 text-red-500";
  if (label === "mock_not_ready") return "bg-gray-500/15 text-gray-500";
  return "bg-gray-500/15 text-gray-500";
}

function verdictText(label: string): string {
  if (label === "externally_validated") return "外部验证";
  if (label === "§44_falsified") return "§44证否";
  if (label === "dead_arm") return "已证否·dead";
  if (label === "mock_not_ready") return "mock·未就绪";
  return label;
}

export function MultiArmPanel() {
  const [recs, setRecs] = useState<MultiArmRec[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const resp = await fetch("/api/recommendation/multi-arm", { headers: authHeaders() });
        if (!resp.ok) throw new ApiError(`多臂推荐失败 HTTP ${resp.status}`, resp.status);
        const data = (await resp.json()) as { data: MultiArmRec[] };
        setRecs(data.data ?? []);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />加载多臂推荐…
      </div>
    );
  }
  if (error) {
    return (
      <GlassCard>
        <div className="p-4 text-sm text-red-600">多臂推荐加载失败：{error}</div>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">多臂模拟推荐（各臂标 §44 验证状态 · 真盘你定）</h3>
      <div className="grid gap-3 md:grid-cols-2">
        {recs.map((r) => (
          <GlassCard key={r.arm} className={`flex flex-col gap-2 ${r.action_type === "none" ? "opacity-70" : ""}`}>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-base font-semibold">{r.arm}{r.name ? ` · ${r.name}` : ""}</div>
                {r.code && <div className="text-xs text-muted-foreground">{r.code}</div>}
              </div>
              <span className={`rounded-full px-2 py-1 text-xs font-medium ${verdictCls(r.honest_label)}`}>
                {verdictText(r.honest_label)}
              </span>
            </div>
            {r.sizing_suggestion && (
              <div className="text-xs text-muted-foreground">
                仓位建议：<span className="font-medium text-foreground">{r.sizing_suggestion}</span>
              </div>
            )}
            <div className="text-xs leading-relaxed text-muted-foreground">{r.note}</div>
            {r.action_type === "batch_buy" && (
              <div className="rounded bg-green-500/10 px-2 py-1 text-[10px] text-green-700">
                actionable · 可选实盘小仓位（真盘你执行）
              </div>
            )}
            {r.action_type === "paper_track" && (
              <div className="rounded bg-yellow-500/10 px-2 py-1 text-[10px] text-yellow-700">
                paper tracking · 不推荐真金（§44 证否，盘中 conditioning 未测）
              </div>
            )}
          </GlassCard>
        ))}
      </div>
    </div>
  );
}
