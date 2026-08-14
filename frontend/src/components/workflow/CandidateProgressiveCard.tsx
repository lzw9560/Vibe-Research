// S066 §11.1 L0-L3 渐进式披露候选卡——一行/摘要/详情三层展开。
// spec §11.1：
//   L0 决策视图（默认）：[代码][名称][策略分][一句话理由][仓位建议][风险标签]
//   L1 摘要视图（点击展开）：板块阶段|日历因子|游资风险|板块热度排名|策略分构成
//   L2 详情视图（点击"更多"）：完整因子分解|质量标准|资讯雷达|游资席位|板块广度
//   L3 因子子页（已有 FactorDetailPage）
import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, ChevronDown, MoreHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { GlassCard } from "@/components/ui/GlassCard";

export interface CandidateCardData {
  code: string;
  name: string;
  strategy_code: string;
  strategy_name: string;
  strategy_score: number;
  one_line_reason: string;
  position_pct: number;            // 建议仓位 %
  risk_label: string;             // 高风险/中风险/低风险/无
  // L1 摘要数据
  sector_phase?: string;           // 启动/发酵/高潮/退潮/冷门
  sector_modifier?: number;
  calendar_factor?: number;        // 日历因子仓位乘数
  hot_money_risk?: string;         // 游资风险标签
  sector_rank?: number;            // 板块强度排名
  score_breakdown?: Record<string, number>;  // 策略分构成
  // L2 详情数据
  factors?: Record<string, number>;         // 完整因子值
  quality_standards?: Array<{ name: string; passed: boolean; required: boolean; detail: string }>;
  news_radar?: { heat_label: string; catalyst_label: string; risk_label: string };
  hot_money_detail?: { day_trip_ratio: number; relay_ratio: number };
  sector_breadth?: number;         // 板块广度 0-1
}

interface Props {
  candidate: CandidateCardData;
  /** 候选所在策略组（用于 L3 因子跳转面包屑上下文） */
  strategyGroup?: string;
}

const RISK_VARIANT: Record<string, "danger" | "warning" | "success" | "default"> = {
  高风险: "danger",
  中风险: "warning",
  低风险: "success",
  无风险: "default",
};

const PHASE_COLOR: Record<string, string> = {
  启动: "text-success",
  发酵: "text-primary",
  高潮: "text-warning",
  退潮: "text-destructive",
  冷门: "text-muted-foreground",
  无历史: "text-muted-foreground",
};

export function CandidateProgressiveCard({ candidate }: Props) {
  const [level, setLevel] = useState<0 | 1 | 2>(0);  // L0 默认

  const c = candidate;

  const toggle = (newLevel: 0 | 1 | 2) => {
    setLevel((prev) => (prev === newLevel ? 0 : newLevel));
  };

  return (
    <GlassCard className="overflow-hidden p-0">
      {/* L0 决策视图（默认，一行） */}
      <button
        onClick={() => toggle(1)}
        className="flex w-full items-center gap-3 p-3 text-left transition-colors hover:bg-muted/10"
      >
        {level >= 1 ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
        <span className="font-mono text-xs text-muted-foreground/70">{c.code}</span>
        <span className="font-medium">{c.name}</span>
        <Badge variant="primary">分{c.strategy_score.toFixed(1)}</Badge>
        <span className="flex-1 truncate text-xs text-muted-foreground">{c.one_line_reason}</span>
        <span className="font-mono text-xs text-primary">{c.position_pct.toFixed(1)}%</span>
        {c.risk_label && c.risk_label !== "无风险" && (
          <Badge variant={RISK_VARIANT[c.risk_label] ?? "default"}>{c.risk_label}</Badge>
        )}
      </button>

      {/* L1 摘要视图 */}
      {level >= 1 && (
        <div className="border-t border-border/30 bg-muted/5 p-3">
          <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-5">
            {c.sector_phase && (
              <div>
                <p className="text-muted-foreground">板块阶段</p>
                <p className={cn("font-bold", PHASE_COLOR[c.sector_phase] ?? "")}>{c.sector_phase}</p>
                {c.sector_modifier != null && c.sector_modifier !== 1.0 && (
                  <span className="text-muted-foreground">×{c.sector_modifier.toFixed(2)}</span>
                )}
              </div>
            )}
            {c.calendar_factor != null && (
              <div>
                <p className="text-muted-foreground">日历因子</p>
                <p className="font-bold">×{c.calendar_factor.toFixed(1)}</p>
              </div>
            )}
            {c.hot_money_risk && (
              <div>
                <p className="text-muted-foreground">游资风险</p>
                <p className="font-bold">{c.hot_money_risk}</p>
              </div>
            )}
            {c.sector_rank != null && (
              <div>
                <p className="text-muted-foreground">板块排名</p>
                <p className="font-bold">#{c.sector_rank}</p>
              </div>
            )}
            <div>
              <p className="text-muted-foreground">战法</p>
              <p className="font-bold truncate">{c.strategy_name}</p>
            </div>
          </div>

          {/* 策略分构成 */}
          {c.score_breakdown && Object.keys(c.score_breakdown).length > 0 && (
            <div className="mt-2">
              <p className="text-xs text-muted-foreground">策略分构成</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {Object.entries(c.score_breakdown).map(([k, v]) => (
                  <span key={k} className="rounded bg-muted/20 px-1.5 py-0.5 font-mono text-[10px]">
                    {k}: {v.toFixed(1)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* L2 展开入口 */}
          <button
            onClick={() => toggle(2)}
            className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary"
          >
            <MoreHorizontal className="h-3 w-3" />
            {level >= 2 ? "收起详情" : "更多详情"}
          </button>
        </div>
      )}

      {/* L2 详情视图 */}
      {level >= 2 && (
        <div className="border-t border-border/30 bg-muted/10 p-3 space-y-3">
          {/* 完整因子分解 */}
          {c.factors && Object.keys(c.factors).length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">完整因子分解</p>
              <div className="mt-1 grid grid-cols-2 gap-1 sm:grid-cols-3">
                {Object.entries(c.factors).map(([k, v]) => (
                  <div key={k} className="flex justify-between rounded bg-muted/20 px-2 py-1 text-xs">
                    <span className="text-muted-foreground">{k}</span>
                    <span className="font-mono">{v.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 质量标准检查 */}
          {c.quality_standards && c.quality_standards.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">质量标准检查</p>
              <div className="mt-1 space-y-1">
                {c.quality_standards.map((q) => (
                  <div key={q.name} className="flex items-center gap-2 text-xs">
                    <span className={cn("font-mono", q.passed ? "text-success" : q.required ? "text-destructive" : "text-muted-foreground")}>
                      {q.passed ? "✓" : q.required ? "✗" : "—"}
                    </span>
                    <span className={q.required ? "text-foreground" : "text-muted-foreground"}>{q.name}</span>
                    <span className="text-muted-foreground">{q.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 资讯雷达 */}
          {c.news_radar && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">资讯雷达</p>
              <div className="mt-1 flex flex-wrap gap-1">
                <Badge variant="info">热度：{c.news_radar.heat_label}</Badge>
                <Badge variant={c.news_radar.catalyst_label.includes("风险") ? "danger" : "success"}>
                  {c.news_radar.catalyst_label}
                </Badge>
                {c.news_radar.risk_label !== "无风险" && (
                  <Badge variant="danger">{c.news_radar.risk_label}</Badge>
                )}
              </div>
            </div>
          )}

          {/* 游资席位明细 */}
          {c.hot_money_detail && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">游资席位明细</p>
              <div className="mt-1 flex gap-3 text-xs">
                <span>一日游占比 <span className="font-mono font-bold">{(c.hot_money_detail.day_trip_ratio * 100).toFixed(0)}%</span></span>
                <span>接力型占比 <span className="font-mono font-bold">{(c.hot_money_detail.relay_ratio * 100).toFixed(0)}%</span></span>
              </div>
            </div>
          )}

          {/* 板块广度 */}
          {c.sector_breadth != null && (
            <div className="text-xs text-muted-foreground">
              板块广度 <span className="font-mono font-bold text-foreground">{(c.sector_breadth * 100).toFixed(0)}%</span>
              （{c.sector_breadth > 0.5 ? "普涨健康" : "个股行情无板块效应"}）
            </div>
          )}

          {/* L3 因子子页跳转 */}
          <Link
            to="/workflow/factor/1"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            查看因子详情 <ChevronRight className="h-3 w-3" />
          </Link>
        </div>
      )}
    </GlassCard>
  );
}
