// S093 T16 + S146：前瞻结论标的看板（spec R6 第一层）
// breakout 降级研究后 CV 重定向涨停叉内：三组分组 dual(漏斗终选∩战法命中) / funnelOnly / strategyOnly
// 每只票卡片：实时价格/涨跌幅/封板状态/持仓状态
// 点击跳 IntradayMonitor 个股详情
// 工程底线：不臆造——query 无数据返空数组；quote 缺字段标"—"；历史统计特征标注。
import { Link } from "react-router-dom";
import { useState } from "react";
import { useCrossValidationGroups } from "@/lib/query/useCrossValidation";
import { useQuote, useWorkflowStates } from "@/lib/query";
import { CrossValidationBadge } from "@/components/workflow/CrossValidationBadge";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { STATUS_COLORS, STATUS_LABELS } from "@/components/workflow/statusMeta";
import type { Quote } from "@/lib/api/types";
import type { CrossValidationGroup } from "@/lib/query/useCrossValidation";

interface WatchlistBoardProps {
  /** 前瞻数据日（briefing 数据源：final_candidates + scored_candidates 都从 briefing 取） */
  F: string;
  /** 当日数据日（useWorkflowStates 持仓状态查询用） */
  date: string;
}

export function WatchlistBoard({ F, date }: WatchlistBoardProps) {
  const cv = useCrossValidationGroups(F);

  const allCodes = [...cv.dual, ...cv.funnelOnly, ...cv.strategyOnly].map((c) => c.code);
  const codesStr = allCodes.join(",");
  const { data: quoteMap } = useQuote(codesStr);
  const { data: workflowStates } = useWorkflowStates(date);

  // code → status 映射（用于持仓状态徽章）
  const stateMap = new Map<string, string>();
  for (const s of workflowStates?.states ?? []) {
    stateMap.set(s.code, s.status);
  }

  if (cv.isLoading) {
    return (
      <div className="mb-6">
        <SectionHeader title="前瞻结论标的看板" subtitle="双指标重叠 / 仅漏斗终选 / 仅战法命中" />
        <GlassCard className="p-4">
          <Skeleton variant="rounded" className="h-32" />
        </GlassCard>
      </div>
    );
  }

  const total = allCodes.length;
  if (total === 0) {
    return (
      <div className="mb-6">
        <SectionHeader title="前瞻结论标的看板" subtitle="双指标重叠 / 仅漏斗终选 / 仅战法命中" />
        <GlassCard className="p-4">
          <p className="text-sm text-muted-foreground">
            前瞻 Tab 尚无选股结论，待 17:15 漏斗预计算完成后产出。
          </p>
        </GlassCard>
      </div>
    );
  }

  const groups: { key: CrossValidationGroup; items: typeof cv.dual }[] = [
    { key: "dual", items: cv.dual },
    { key: "funnelOnly", items: cv.funnelOnly },
    { key: "strategyOnly", items: cv.strategyOnly },
  ];

  return (
    <div className="mb-6">
      <SectionHeader
        title="前瞻结论标的看板"
        subtitle="双指标重叠 / 仅漏斗终选 / 仅战法命中 · 点击展开 · 点击标的跳个股盯盘"
      />
      <div className="space-y-2">
        {groups.map(
          (g) =>
            g.items.length > 0 && (
              <CollapsibleGroup key={g.key} group={g.key} count={g.items.length}>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {g.items.map((item) => (
                    <WatchlistCard
                      key={item.code}
                      code={item.code}
                      name={item.name}
                      strategyName={item.strategyName}
                      strategyScore={item.strategyScore}
                      geneScore={item.geneScore}
                      quote={quoteMap?.[item.code]}
                      status={stateMap.get(item.code)}
                    />
                  ))}
                </div>
              </CollapsibleGroup>
            ),
        )}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/60">
        参考值，非执行指令；市场有风险
      </p>
    </div>
  );
}

/** 可收缩分组——双重确认默认展开，其余默认收缩；懒渲染（仅 open 时渲染候选网格）。 */
function CollapsibleGroup({
  group,
  count,
  children,
}: {
  group: CrossValidationGroup;
  count: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(group === "dual");
  return (
    <GlassCard className="p-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        <CrossValidationBadge group={group} />
        <span className="text-xs text-muted-foreground">{count} 只</span>
        <span className="ml-auto text-[10px] text-muted-foreground/60">
          {open ? "▼" : "▶"}
        </span>
      </button>
      {open && <div className="mt-3">{children}</div>}
    </GlassCard>
  );
}

/** 单只票卡片——股票名/战法/分数 + 实时价格/涨跌幅/封板状态/持仓状态。 */
function WatchlistCard({
  code,
  name,
  strategyName,
  strategyScore,
  geneScore,
  quote,
  status,
}: {
  code: string;
  name: string;
  strategyName?: string;
  strategyScore?: number;
  geneScore?: number;
  quote?: Quote;
  status?: string;
}) {
  const price = quote?.price;
  const changePct = quote?.change_pct;
  const isSealed =
    quote != null &&
    quote.limit_up_price != null &&
    quote.price >= quote.limit_up_price;

  return (
    <Link to={`/workflow/intraday?code=${code}`} className="block">
      <GlassCard className="p-3 transition-all hover:ring-2 hover:ring-primary/30">
        {/* 第一行：股票名 + code + 持仓状态 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium">{name}</span>
            <span className="font-mono text-[10px] text-muted-foreground/60">{code}</span>
          </div>
          {status && (
            <span
              className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-white ${
                STATUS_COLORS[status] ?? "bg-gray-300"
              }`}
            >
              {STATUS_LABELS[status] ?? status}
            </span>
          )}
        </div>
        {/* 第二行：战法 + 分数 */}
        <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground/70">
          {strategyName && <span>{strategyName}</span>}
          {strategyScore != null && <span className="font-mono">战法分 {strategyScore.toFixed(1)}</span>}
          {geneScore != null && <span className="font-mono">基因 {geneScore.toFixed(1)}</span>}
        </div>
        {/* 第三行：价格 + 涨跌幅 */}
        <div className="mt-2 flex items-baseline justify-between">
          <span className="text-lg font-semibold tabular-nums">
            {price != null ? price.toFixed(2) : "—"}
          </span>
          {changePct != null && (
            <span
              className={`text-sm tabular-nums ${
                changePct >= 0 ? "text-red-600" : "text-green-600"
              }`}
            >
              {changePct >= 0 ? "+" : ""}
              {changePct.toFixed(2)}%
            </span>
          )}
        </div>
        {/* 第四行：封板状态 */}
        <div className="mt-1 text-[10px] text-muted-foreground">
          {quote ? (isSealed ? "封板" : "未封板") : "实时价格待接入"}
          {quote?.limit_up_price ? ` · 涨停 ${quote.limit_up_price.toFixed(2)}` : ""}
        </div>
      </GlassCard>
    </Link>
  );
}
