// S093 T11：从 PreMarketBriefing 私有函数抽为可复用组件。
// S079 P2 仓位闸 + 龙虎榜风控面板（R9-R10，spec §3.3）
// 展示：market_phase（绿/黄/红 + 档位名）+ market_phase_cap（仓位上限%）
//       seat_risk_flags（命中【拒绝介入】/独食独大/散户霸榜的标的 + 标记）
//       data_missing_flags（数据缺失警示）
//       execution_checklist（人工执行 checklist 列表）
//       param_disclaimer（"仓位参数参考值，非执行指令"）

import { TrendingUp } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { PreMarketBriefing } from "@/lib/api";

const TIER_STYLES: Record<string, { dot: string; label: string; text: string }> = {
  green: { dot: "bg-emerald-500", label: "绿档", text: "text-emerald-600" },
  yellow: { dot: "bg-amber-500", label: "黄档", text: "text-amber-600" },
  red: { dot: "bg-rose-500", label: "红档", text: "text-rose-600" },
};

interface P2RiskPanelProps {
  briefing: PreMarketBriefing;
}

export function P2RiskPanel({ briefing }: P2RiskPanelProps) {
  const phase = briefing.market_phase;
  const cap = briefing.market_phase_cap;
  const tier = briefing.position_cap_tier;
  const seatFlags = briefing.seat_risk_flags ?? {};
  const dataMissing = briefing.data_missing_flags ?? {};
  const checklist = briefing.execution_checklist ?? [];
  const disclaimer = briefing.param_disclaimer;

  // 无 P2 数据（旧快照或未采集）→ 不渲染
  if (
    !phase &&
    !cap &&
    Object.keys(seatFlags).length === 0 &&
    checklist.length === 0
  ) {
    return null;
  }

  const tierStyle = tier ? TIER_STYLES[tier] : null;
  const capPct = cap != null ? `${Math.round(cap * 100)}%` : "—";

  return (
    <GlassCard className="mb-6 p-4">
      <div className="flex items-center gap-2 border-b border-border/30 pb-2">
        <TrendingUp className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold">P2 仓位闸 + 龙虎榜风控</h3>
        {tierStyle && (
          <span className={`ml-auto inline-flex items-center gap-1 text-xs ${tierStyle.text}`}>
            <span className={`inline-block h-2 w-2 rounded-full ${tierStyle.dot}`} />
            {tierStyle.label}
          </span>
        )}
      </div>

      {/* 仓位闸档位 + cap */}
      <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
        <div>
          <span className="text-muted-foreground">市场档位：</span>
          <span className="font-medium">{phase ?? "—"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">仓位上限：</span>
          <span className="font-medium tabular-nums">{capPct}</span>
        </div>
      </div>

      {/* 龙虎榜风控标记（seat_risk_flags） */}
      {Object.keys(seatFlags).length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">龙虎榜风控标记：</p>
          <ul className="space-y-1">
            {Object.entries(seatFlags).map(([code, flags]) => (
              <li key={code} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono text-muted-foreground">{code}</span>
                {flags.map((f, i) => (
                  <span
                    key={i}
                    className={`rounded px-1.5 py-0.5 ${
                      f.includes("拒绝介入")
                        ? "bg-rose-500/10 text-rose-600"
                        : f.includes("独食独大")
                          ? "bg-amber-500/10 text-amber-600"
                          : f.includes("散户霸榜")
                            ? "bg-orange-500/10 text-orange-600"
                            : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {f}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 数据缺失警示（data_missing_flags） */}
      {Object.keys(dataMissing).length > 0 && (
        <div className="mt-3 rounded border border-amber-500/30 bg-amber-500/5 p-2">
          <p className="text-xs font-medium text-amber-600">⚠ 席位风控数据未取得</p>
          <ul className="mt-1 space-y-0.5 text-xs text-amber-600/80">
            {Object.entries(dataMissing).map(([code, msg]) => (
              <li key={code}>
                <span className="font-mono">{code}</span>：{msg}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 人工执行 checklist */}
      {checklist.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">人工执行 checklist：</p>
          <ul className="space-y-0.5 text-xs">
            {checklist.map((item, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="text-muted-foreground">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 合规免责声明 */}
      {disclaimer && (
        <p className="mt-3 border-t border-border/30 pt-2 text-[10px] text-muted-foreground">
          {disclaimer}
        </p>
      )}
    </GlassCard>
  );
}
