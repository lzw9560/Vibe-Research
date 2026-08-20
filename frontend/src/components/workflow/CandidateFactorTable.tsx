// S087 R2/R3 简化 A + R21：候选因子表格 + 行展开详情。
// 替代 FunnelLayers 三层 + SelectionPipeline 卡片——表格呈现候选 × 因子列，点击行展开因子详情。
import { Fragment, useState } from "react";
import { cn } from "@/lib/utils";
import type { DiagnosisCard } from "@/lib/api/types";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";

interface Props {
  candidates: DiagnosisCard[];
  date?: string;
}

export function CandidateFactorTable({ candidates }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!candidates.length) {
    return <GlassCard className="p-4"><p className="text-sm text-muted-foreground">无候选标的</p></GlassCard>;
  }

  return (
    <GlassCard className="p-2">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border/40 text-muted-foreground/70">
              <th className="px-2 py-1 text-left">code</th>
              <th className="px-2 py-1 text-left">名称</th>
              <th className="px-2 py-1 text-right">基因分</th>
              <th className="px-2 py-1 text-right">封板率</th>
              <th className="px-2 py-1 text-right">换手%</th>
              <th className="px-2 py-1 text-right">量比</th>
              <th className="px-2 py-1 text-right">成交额亿</th>
              <th className="px-2 py-1 text-center">八项</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => {
              const g = c.gene_score as { total_score?: number; factors?: Record<string, number | null> } | null;
              const ind = c.indicators;
              const isOpen = expanded === c.code;
              const failCount = c.eight_standards?.fail_count ?? 0;
              return (
                <Fragment key={c.code}>
                  <tr
                    onClick={() => setExpanded(isOpen ? null : c.code)}
                    className={cn("cursor-pointer border-b border-border/20 hover:bg-muted/10", c.capped && "bg-red-500/5")}
                  >
                    <td className="px-2 py-1 font-mono">{c.code}</td>
                    <td className="px-2 py-1 truncate max-w-[8rem]">{c.name}</td>
                    <td className="px-2 py-1 text-right font-mono">{g?.total_score ?? "—"}</td>
                    <td className="px-2 py-1 text-right">{g?.factors?.["封板率"]?.toFixed(1) ?? "—"}</td>
                    <td className="px-2 py-1 text-right">{ind.turnover_pct?.toFixed(1) ?? "—"}</td>
                    <td className="px-2 py-1 text-right">{ind.vol_ratio?.toFixed(2) ?? "—"}</td>
                    <td className="px-2 py-1 text-right">{ind.amount_yi?.toFixed(1) ?? "—"}</td>
                    <td className="px-2 py-1 text-center">
                      {c.capped ? <Badge variant="warning">封顶{failCount}未过</Badge> : <Badge variant="success">通过{failCount}</Badge>}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr key={`${c.code}-detail`}>
                      <td colSpan={8} className="px-3 py-2 bg-muted/5">
                        <div className="space-y-2 text-xs">
                          <div>
                            <span className="text-muted-foreground/60">连板:</span> {ind.consec_boards ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">振幅:</span> {ind.amplitude_pct?.toFixed(1) ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">主力净流:</span> {ind.main_net_inflow ?? "—"}万 |
                            <span className="text-muted-foreground/60 ml-2">北向:</span> {ind.northbound ?? "—"}
                          </div>
                          <div>
                            <span className="text-muted-foreground/60">竞价开盘:</span> {ind.auction_open_pct ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">封单:</span> {ind.seal_amount ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">流通市值:</span> {ind.float_market_cap ? `${(ind.float_market_cap / 1e8).toFixed(1)}亿` : "—"}
                          </div>
                          <div>
                            <span className="text-muted-foreground/60">MA5/10/20:</span> {ind.ma5?.toFixed(2) ?? "—"}/{ind.ma10?.toFixed(2) ?? "—"}/{ind.ma20?.toFixed(2) ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">概念:</span> {(ind.concepts ?? []).slice(0, 5).join("、") || "—"}
                          </div>
                          {c.eight_standards?.items && c.eight_standards.items.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {c.eight_standards.items.map((it) => (
                                <Badge key={it.key} variant={it.status === "pass" ? "success" : it.status === "fail" ? "warning" : "default"}>
                                  {it.label}: {it.status}
                                </Badge>
                              ))}
                            </div>
                          )}
                          {c.cap_reason && <div className="text-amber-200/70">{c.cap_reason}</div>}
                          {c.risk_flags.length > 0 && <div className="text-red-300/70">风险: {c.risk_flags.join("、")}</div>}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}
