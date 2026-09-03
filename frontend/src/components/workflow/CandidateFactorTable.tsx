// S087 R2/R3 简化 A + R21：候选因子表格 + 行展开详情。
// 八项标准作表头列（动态 items label），内容 status+actual，未通过红背景。
import { Fragment, useState } from "react";
import { cn } from "@/lib/utils";
import type { DiagnosisCard, EightStandardItem } from "@/lib/candidates";
import { GlassCard } from "@/components/ui/GlassCard";

interface Props {
  candidates: DiagnosisCard[];
  date?: string;
}

// 八项 status → 颜色
function statusBg(it: EightStandardItem | undefined): string {
  if (!it) return "";
  if (it.status === "fail") return "bg-red-500/15 text-red-400";
  if (it.status === "pass") return "bg-emerald-500/10 text-emerald-400";
  return "bg-muted/10 text-muted-foreground/40"; // missing
}

export function CandidateFactorTable({ candidates }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!candidates.length) {
    return <GlassCard className="p-4"><p className="text-sm text-muted-foreground">无候选标的</p></GlassCard>;
  }

  // 八项 items（取第一个候选的 items 作表头，所有候选同构 8 项）
  const eightItems = candidates[0]?.eight_standards?.items ?? [];

  return (
    <GlassCard className="p-2">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border/40 text-muted-foreground/70">
              <th className="px-2 py-1 text-left">code</th>
              <th className="px-2 py-1 text-left">名称</th>
              <th className="px-2 py-1 text-right">基因分</th>
              {eightItems.map((it) => (
                <th key={it.key} className="px-1.5 py-1 text-center whitespace-nowrap" title={it.expected}>{it.label}</th>
              ))}
              <th className="px-2 py-1 text-center">展开</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => {
              const g = c.gene_score as { total_score?: number; factors?: Record<string, number | null> } | null;
              const ind = c.indicators;
              const isOpen = expanded === c.code;
              const items = c.eight_standards?.items ?? [];
              const failCount = c.eight_standards?.fail_count ?? 0;
              return (
                <Fragment key={c.code}>
                  <tr
                    onClick={() => setExpanded(isOpen ? null : c.code)}
                    className={cn("cursor-pointer border-b border-border/20 hover:bg-muted/10", c.capped && "bg-red-500/5")}
                  >
                    <td className="px-2 py-1 font-mono">{c.code}</td>
                    <td className="px-2 py-1 truncate max-w-[6rem]">{c.name}</td>
                    <td className="px-2 py-1 text-right font-mono">{g?.total_score ?? "—"}</td>
                    {eightItems.map((hdr, i) => {
                      const it = items[i];
                      return (
                        <td key={hdr.key} className={cn("px-1.5 py-1 text-center", statusBg(it))}>
                          {it ? (it.actual || it.status) : "—"}
                        </td>
                      );
                    })}
                    <td className="px-2 py-1 text-center text-muted-foreground/50">{isOpen ? "▾" : "▸"}</td>
                  </tr>
                  {isOpen && (
                    <tr key={`${c.code}-detail`}>
                      <td colSpan={3 + eightItems.length + 1} className="px-3 py-2 bg-muted/5">
                        <div className="space-y-2 text-xs">
                          {/* 八项详情 */}
                          {items.length > 0 && (
                            <div>
                              <div className="mb-1 font-semibold text-muted-foreground/70">八项标准（{failCount} 未过{c.capped ? "→封顶55" : ""}）</div>
                              <div className="flex flex-wrap gap-1">
                                {items.map((it) => (
                                  <span key={it.key} className={cn("rounded px-1.5 py-0.5", statusBg(it))} title={it.expected}>
                                    {it.label}: {it.status} {it.actual ? `(${it.actual})` : ""}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {/* 量价/资金 */}
                          <div>
                            <span className="text-muted-foreground/60">连板:</span> {ind.consec_boards ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">换手:</span> {ind.turnover_pct?.toFixed(1) ?? "—"}% |
                            <span className="text-muted-foreground/60 ml-2">量比:</span> {ind.vol_ratio?.toFixed(2) ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">成交额:</span> {ind.amount_yi?.toFixed(1) ?? "—"}亿 |
                            <span className="text-muted-foreground/60 ml-2">封板率:</span> {g?.factors?.["封板率"]?.toFixed(1) ?? "—"}%
                          </div>
                          <div>
                            <span className="text-muted-foreground/60">主力净流:</span> {ind.main_net_inflow ?? "—"}万 |
                            <span className="text-muted-foreground/60 ml-2">北向:</span> {ind.northbound ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">封单:</span> {ind.seal_amount ?? "—"} |
                            <span className="text-muted-foreground/60 ml-2">流通市值:</span> {ind.float_market_cap ? `${(ind.float_market_cap / 1e8).toFixed(1)}亿` : "—"}
                          </div>
                          {/* 基因 5 因子（S047 full 权重 40/25/25/0/10） */}
                          <div>
                            <span className="text-muted-foreground/60">基因因子:</span> 次日溢价率 {g?.factors?.["次日溢价率"]?.toFixed(1) ?? "—"} / 红盘率 {g?.factors?.["红盘率"]?.toFixed(1) ?? "—"} / 封板率 {g?.factors?.["封板率"]?.toFixed(1) ?? "—"} / 炸板后溢价 {g?.factors?.["炸板后溢价"]?.toFixed(1) ?? "—"} / 涨停频次 {g?.factors?.["涨停频次"]?.toFixed(1) ?? "—"}
                          </div>
                          {/* pool_item 涨停池原始（S084 解耦子对象） */}
                          {c.pool_item && (
                            <div>
                              <span className="text-muted-foreground/60">涨停池:</span> 连板 {(c.pool_item as Record<string, number | string | null>).lbc ?? "—"} / 炸板 {(c.pool_item as Record<string, number | string | null>).zbc ?? "—"} / 首封 {(c.pool_item as Record<string, number | string | null>).fbt ?? "—"} / 涨幅 {(c.pool_item as Record<string, number | string | null>).zdp ?? "—"}% / 换手 {(c.pool_item as Record<string, number | string | null>).hs ?? "—"}% / 价 {(c.pool_item as Record<string, number | string | null>).p ?? "—"}
                            </div>
                          )}
                          {/* derived S070 R7 分时派生 */}
                          {c.derived && (
                            <div>
                              <span className="text-muted-foreground/60">分时派生:</span> 炸板时长 {(c.derived as Record<string, number | string | null>).broken_duration_min ?? "—"}min / 最大回撤 {(c.derived as Record<string, number | string | null>).max_drop_pct ?? "—"}% / 尾封 {(c.derived as Record<string, number | string | null>).last_lock_time ?? "—"}
                            </div>
                          )}
                          {/* K线派生（S081 PRD 战法因子） */}
                          <div>
                            <span className="text-muted-foreground/60">K线:</span> 最高涨幅 {ind.max_high_pct?.toFixed(1) ?? "—"}% / 上影线 {ind.shadow_length_pct?.toFixed(1) ?? "—"}% / MA5状态 {ind.ma_5_status ?? "—"} / 前日换手 {ind.prev_turnover_pct?.toFixed(1) ?? "—"}%
                          </div>
                          {/* 未取得数据源（补充 missing 数据源显示——哪些字段缺数据 + 原因）*/}
                          {ind.missing && Object.keys(ind.missing).length > 0 && (
                            <div className="text-yellow-500/70">
                              <span className="text-muted-foreground/60">未取得:</span>{" "}
                              {Object.entries(ind.missing).map(([k, v]) => `${k}(${v})`).join(" · ")}
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
