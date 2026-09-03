// S093 T16 + S146：前瞻结论标的看板（spec R6 第一层）
// 交叉验证（dual=finals∩scored）已删——两 <2x 弱信号交集无 validated edge（§44），且 scored⊆finals 非真双路。
// 改用 final_candidates（漏斗终选）直接列 52 只，去 CV 分组 + badges + CollapsibleGroup。
// 每只票卡片：股票名/基因分 + 实时价格/涨跌幅/封板状态/持仓状态
// 点击跳 IntradayMonitor 个股详情
// 工程底线：不臆造——query 无数据返空数组；quote 缺字段标"—"；历史统计特征标注。
import { Link } from "react-router-dom";
import { usePreMarketBriefing, useQuote, useWorkflowStates } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { STATUS_COLORS, STATUS_LABELS } from "@/components/workflow/statusMeta";
import type { Quote } from "@/lib/api/types";

interface WatchlistBoardProps {
  /** 当日数据日（briefing final_candidates + useWorkflowStates 持仓状态都用此） */
  date: string;
}

export function WatchlistBoard({ date }: WatchlistBoardProps) {
  const { data: briefing, isLoading } = usePreMarketBriefing(date);
  const finals = briefing?.final_candidates ?? [];

  const allCodes = finals.map((c) => c.code);
  const codesStr = allCodes.join(",");
  const { data: quoteMap } = useQuote(codesStr);
  const { data: workflowStates } = useWorkflowStates(date);

  // code → status 映射（用于持仓状态徽章）
  const stateMap = new Map<string, string>();
  for (const s of workflowStates?.states ?? []) {
    stateMap.set(s.code, s.status);
  }

  if (isLoading) {
    return (
      <div className="mb-6">
        <SectionHeader title="前瞻结论标的看板" subtitle="漏斗终选 final_candidates · §44 未 validated" />
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
        <SectionHeader title="前瞻结论标的看板" subtitle="漏斗终选 final_candidates · §44 未 validated" />
        <GlassCard className="p-4">
          <p className="text-sm text-muted-foreground">
            前瞻 Tab 尚无选股结论，待 17:15 漏斗预计算完成后产出。
          </p>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="mb-6">
      <SectionHeader
        title="前瞻结论标的看板"
        subtitle={`漏斗终选 ${total} 只 · §44 未 validated · 点击标的跳个股盯盘`}
      />
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {finals.map((item) => {
          const gs = item.gene_score?.total_score;
          return (
            <WatchlistCard
              key={item.code}
              code={item.code}
              name={item.name}
              geneScore={typeof gs === "number" ? gs : undefined}
              quote={quoteMap?.[item.code]}
              status={stateMap.get(item.code)}
            />
          );
        })}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/60">
        参考值，非执行指令；市场有风险
      </p>
    </div>
  );
}

/** 单只票卡片——股票名/基因分 + 实时价格/涨跌幅/封板状态/持仓状态。 */
function WatchlistCard({
  code,
  name,
  geneScore,
  quote,
  status,
}: {
  code: string;
  name: string;
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
        {/* 第二行：基因分 */}
        <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground/70">
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
