// 多维度 IA: 跨线实体 drawer——点信号/股→看它在各线的面
// 5 线面: 时间相位/选股来源/验证态/策略匹配/认知图谱
// 用 Sheet 组件，kg-summary 走 /api/stock/{code}/kg-summary，其余 honest-empty
import { type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Sheet } from "@/components/ui/Sheet";
import { GlassCard } from "@/components/ui/GlassCard";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { request } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export interface CrossLineDrawerProps {
  open: boolean;
  onClose: () => void;
  stockCode: string | null;
  stockName?: string;
}

// kg-summary 响应——按后端 stock_kg_summary 返回结构
interface KgSummary {
  summary?: string;
  concepts?: string[];
  sectors?: string[];
  [k: string]: unknown;
}

export function CrossLineDrawer({ open, onClose, stockCode, stockName }: CrossLineDrawerProps) {
  // 认知面: kg-summary
  const { data: kgSummary, isLoading: kgLoading } = useQuery({
    queryKey: ["stock", "kg-summary", stockCode] as const,
    queryFn: () => request<KgSummary>(`/stock/${stockCode}/kg-summary`),
    enabled: open && !!stockCode,
    staleTime: 5 * 60_000,
  });

  if (!open || !stockCode) return null;

  return (
    <Sheet open={open} onClose={onClose}>
      <div className="space-y-4">
        {/* 头: 股票代码+名称 */}
        <div className="border-b border-border/50 pb-3">
          <h2 className="text-lg font-bold">{stockName ?? stockCode}</h2>
          <p className="text-xs text-muted-foreground">{stockCode} · 跨线视图</p>
        </div>

        {/* ① 时间面 */}
        <CrossLineFace title="① 时间面" subtitle="当前时段相位">
          <HonestEmptyState
            message="时段相位由全局 useDateTriplet 驱动"
            hint="个股无独立相位，看 /today hub 的时段灯"
          />
        </CrossLineFace>

        {/* ② 选股面 */}
        <CrossLineFace title="② 选股面" subtitle="选股来源（漏斗/竞价/席位/板块）">
          <HonestEmptyState
            message="选股来源追溯待接线"
            hint="需后端记录候选来源（funnel/auction/seat/sector），当前无 endpoint"
          />
        </CrossLineFace>

        {/* ③ 验证面 */}
        <CrossLineFace title="③ 验证面" subtitle="§44 verdict + 信号验证态">
          <HonestEmptyState
            message="个股 §44 verdict 待接线"
            hint="verdict 按 dimension 非 per-stock，看 /review 验证 tab 全量 verdict"
          />
        </CrossLineFace>

        {/* ④ 策略面 */}
        <CrossLineFace title="④ 策略面" subtitle="战法匹配 + 回测胜率">
          <HonestEmptyState
            message="个股战法匹配待接线"
            hint="需 /api/strategy/match?code= 接口，当前看 /review 策略 tab"
          />
        </CrossLineFace>

        {/* ⑤ 认知面 */}
        <CrossLineFace title="⑤ 认知面" subtitle="M7 图谱 + 公告 JSON">
          {kgLoading ? (
            <p className="text-xs text-muted-foreground">加载 kg-summary…</p>
          ) : kgSummary ? (
            <div className="space-y-2">
              {kgSummary.summary && (
                <p className="text-xs text-muted-foreground">{kgSummary.summary}</p>
              )}
              {kgSummary.concepts && kgSummary.concepts.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {kgSummary.concepts.slice(0, 8).map((c) => (
                    <span key={c} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                      {c}
                    </span>
                  ))}
                </div>
              )}
              {kgSummary.sectors && kgSummary.sectors.length > 0 && (
                <div className="text-[11px] text-muted-foreground">
                  板块: {kgSummary.sectors.join(" / ")}
                </div>
              )}
            </div>
          ) : (
            <HonestEmptyState
              message="kg-summary 无数据"
              hint="该股图谱摘要待 M7 注入或 daily_kg_sync 采集"
            />
          )}
        </CrossLineFace>
      </div>
    </Sheet>
  );
}

function CrossLineFace({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <GlassCard tier="sub" className="space-y-2">
      <div>
        <h3 className="text-xs font-semibold">{title}</h3>
        <p className="text-[10px] text-muted-foreground">{subtitle}</p>
      </div>
      {children}
    </GlassCard>
  );
}

// 触发器——可点的小按钮，打开 drawer
export function CrossLineTrigger({
  stockCode,
  className,
  children,
}: {
  stockCode: string;
  className?: string;
  children?: ReactNode;
}) {
  // 此组件需配合上层 CrossLineDrawer 的 open state 使用
  // 用法: 上层管 state, 传 open/onClose/code 给 CrossLineDrawer
  // 这里只渲染一个可点 span, onClick 由上层传
  return (
    <span className={cn("cursor-pointer text-primary hover:underline", className)}>
      {children ?? stockCode}
    </span>
  );
}
