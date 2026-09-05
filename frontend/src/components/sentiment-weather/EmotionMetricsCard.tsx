import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { useConsecPremiumDetail } from "@/lib/query";
import type { EmotionMetrics } from "@/lib/limitup";

interface Props {
  metrics: EmotionMetrics | undefined;
  error?: unknown;
}

const pct = (v: number | null | undefined): string =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(0)}%`;
const signed = (v: number | null | undefined): string =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** S149 Phase 2：派生情绪指标卡片（赚钱效应/连板溢价/情绪周期）。
 * aggregate 无个股名（守 market.py:166 零个股名契约）；
 * cycle_position 是 STIPhase 辅助读数（双源规则——⚠️ 相对读数，不进 AI/journal 盖章）。
 * 补充卡片——error 不阻塞整页，但就地呈现（不静默吞错）。 */
export function EmotionMetricsCard({ metrics, error }: Props) {
  const [showDetail, setShowDetail] = useState(false);
  const detailQ = useConsecPremiumDetail(undefined, { enabled: showDetail });
  const me = metrics?.money_effect;
  const cp = metrics?.consec_premium;
  const cy = metrics?.cycle;

  if (error && !metrics) {
    return (
      <GlassCard className="p-5">
        <h3 className="text-sm font-medium text-foreground mb-2">派生情绪指标</h3>
        <p className="text-xs text-red-400">加载失败：{errMsg(error)}</p>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-foreground">派生情绪指标</h3>
        <span className="text-[10px] text-foreground/40">
          {metrics?.date ?? "—"} · 对照 {metrics?.prev_date ?? "—"}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* 赚钱效应 */}
        <div className="p-3 rounded-lg bg-foreground/5 border border-foreground/5">
          <p className="text-xs text-foreground/60 mb-2">赚钱效应</p>
          {me?.available ? (
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">样本</span>
                <span className="tabular-nums text-foreground">{me.sample ?? "—"}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">平均</span>
                <span className="tabular-nums text-foreground">{signed(me.avg)}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">中位</span>
                <span className="tabular-nums text-foreground font-medium">{signed(me.median)}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">翻红率</span>
                <span className="tabular-nums text-foreground">{pct(me.positive_rate)}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">再涨停</span>
                <span className="tabular-nums text-foreground">{pct(me.limit_up_again_rate)}</span>
              </div>
              {me.partial && (
                <p className="text-[10px] text-amber-400 mt-1">⚠️ 样本不全</p>
              )}
            </div>
          ) : (
            <p className="text-xs text-foreground/40">不可用（{me?.reason ?? "未知"}）</p>
          )}
        </div>

        {/* 连板溢价 aggregate */}
        <div className="p-3 rounded-lg bg-foreground/5 border border-foreground/5">
          <p className="text-xs text-foreground/60 mb-2">连板溢价（承接度）</p>
          {cp?.available ? (
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">高标样本</span>
                <span className="tabular-nums text-foreground">{cp.sample ?? "—"}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">平均</span>
                <span className="tabular-nums text-foreground">{signed(cp.avg)}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">中位</span>
                <span className="tabular-nums text-foreground font-medium">{signed(cp.median)}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">翻红率</span>
                <span className="tabular-nums text-foreground">{pct(cp.positive_rate)}</span>
              </div>
              {cp.partial && (
                <p className="text-[10px] text-amber-400 mt-1">⚠️ 样本不全</p>
              )}
            </div>
          ) : (
            <p className="text-xs text-foreground/40">不可用（{cp?.reason ?? "未知"}）</p>
          )}
        </div>

        {/* 情绪周期（双源规则：STIPhase=主，cycle=辅）*/}
        <div className="p-3 rounded-lg bg-foreground/5 border border-amber-500/20">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-foreground/60">情绪周期</p>
            <Badge variant="warning" className="text-[9px]">辅 · STIPhase 为主</Badge>
          </div>
          {cy?.available ? (
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">距低点</span>
                <span className="tabular-nums text-foreground">第 {cy.day_n ?? "—"} 天</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">分位</span>
                <span className="tabular-nums text-foreground">
                  {cy.pctile !== null && cy.pctile !== undefined ? `${(cy.pctile * 100).toFixed(0)}%` : "—"}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/50">走向</span>
                <span className="text-foreground">{cy.trend ?? "—"}</span>
              </div>
              <p className="text-[9px] text-foreground/40 mt-1">
                ⚠️ 十日窗口相对读数，无绝对含义；不进 AI/journal 盖章
              </p>
            </div>
          ) : (
            <p className="text-xs text-foreground/40">不可用（{cy?.reason ?? "未知"}）</p>
          )}
        </div>
      </div>

      {/* 连板溢价按股明细（带个股名，独立路由，不进 AI context）*/}
      <div className="mt-3 pt-3 border-t border-border">
        <button
          onClick={() => setShowDetail((s) => !s)}
          className="flex items-center gap-1 text-xs text-foreground/60 hover:text-foreground"
        >
          {showDetail ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          连板溢价按股明细（含个股名 · 不进 AI）
        </button>
        {showDetail && (
          <div className="mt-2 space-y-1">
            {detailQ.isLoading ? (
              <p className="text-xs text-foreground/40">加载中…</p>
            ) : detailQ.isError ? (
              <p className="text-xs text-red-400">明细加载失败：{errMsg(detailQ.error)}</p>
            ) : detailQ.data && !detailQ.data.available ? (
              <p className="text-xs text-foreground/40">{detailQ.data.reason ?? "取数失败"}</p>
            ) : detailQ.data && detailQ.data.count > 0 ? (
              <div className="space-y-1">
                {detailQ.data.detail.map((d) => (
                  <div key={d.code} className="flex items-center justify-between text-xs p-1.5 rounded bg-foreground/5">
                    <span className="text-foreground">
                      {d.code} {d.name}
                      <span className="text-foreground/40 ml-1">（{d.prev_boards ?? "—"}板）</span>
                    </span>
                    <span className={`tabular-nums ${(d.ret ?? 0) >= 0 ? "text-red-400" : "text-green-400"}`}>
                      {signed(d.ret)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-foreground/40">无 2 板以上个股明细</p>
            )}
          </div>
        )}
      </div>
    </GlassCard>
  );
}
