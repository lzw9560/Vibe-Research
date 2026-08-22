// S093 T16：前瞻结论标的看板（spec R6 第一层）
// 三组分组：dual(漏斗∩breakout) / funnelOnly / breakoutOnly
// 每只票卡片：实时价格/涨跌幅/封板状态/持仓状态
// 点击跳 IntradayMonitor 个股详情
// 工程底线：不臆造——query 无数据返空数组；quote 缺字段标"—"；历史统计特征标注。
import { Link } from "react-router-dom";
import { useCrossValidationGroups } from "@/lib/query/useCrossValidation";
import { useQuote, useWorkflowStates } from "@/lib/query";
import { CrossValidationBadge } from "@/components/workflow/CrossValidationBadge";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { STATUS_COLORS, STATUS_LABELS } from "@/components/workflow/statusMeta";
import type { Quote } from "@/lib/api/types";

interface WatchlistBoardProps {
  /** 前瞻数据日（漏斗 final_candidates 数据源） */
  F: string;
  /** forward 日期（breakout 候选数据源） */
  forward: string;
  /** 当日数据日（useWorkflowStates 持仓状态查询用） */
  date: string;
}

export function WatchlistBoard({ F, forward, date }: WatchlistBoardProps) {
  const cv = useCrossValidationGroups(F, forward);

  const allCodes = [...cv.dual, ...cv.funnelOnly, ...cv.breakoutOnly];
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
        <SectionHeader title="前瞻结论标的看板" subtitle="双重确认 / 仅漏斗 / 仅 breakout" />
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
        <SectionHeader title="前瞻结论标的看板" subtitle="双重确认 / 仅漏斗 / 仅 breakout" />
        <GlassCard className="p-4">
          <p className="text-sm text-muted-foreground">
            前瞻 Tab 尚无选股结论，待 17:15 漏斗预计算完成后产出。
          </p>
        </GlassCard>
      </div>
    );
  }

  const groups: { key: "dual" | "funnelOnly" | "breakoutOnly"; codes: string[] }[] = [
    { key: "dual", codes: cv.dual },
    { key: "funnelOnly", codes: cv.funnelOnly },
    { key: "breakoutOnly", codes: cv.breakoutOnly },
  ];

  return (
    <div className="mb-6">
      <SectionHeader
        title="前瞻结论标的看板"
        subtitle="双重确认 / 仅漏斗 / 仅 breakout · 点击跳个股盯盘"
      />
      <div className="space-y-4">
        {groups.map(
          (g) =>
            g.codes.length > 0 && (
              <div key={g.key}>
                <div className="mb-2 flex items-center gap-2">
                  <CrossValidationBadge group={g.key} />
                  <span className="text-xs text-muted-foreground">{g.codes.length} 只</span>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {g.codes.map((code) => (
                    <WatchlistCard
                      key={code}
                      code={code}
                      quote={quoteMap?.[code]}
                      status={stateMap.get(code)}
                    />
                  ))}
                </div>
              </div>
            ),
        )}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/60">
        参考值，非执行指令；市场有风险
      </p>
    </div>
  );
}

/** 单只票卡片——实时价格/涨跌幅/封板状态/持仓状态徽章。 */
function WatchlistCard({
  code,
  quote,
  status,
}: {
  code: string;
  quote?: Quote;
  status?: string;
}) {
  const price = quote?.price;
  const changePct = quote?.change_pct;
  // 封板判定：price >= limit_up_price（浮点近似比较）
  const isSealed =
    quote != null &&
    quote.limit_up_price != null &&
    quote.price >= quote.limit_up_price;

  return (
    <Link to={`/workflow/intraday?code=${code}`} className="block">
      <GlassCard className="p-3 transition-all hover:ring-2 hover:ring-primary/30">
        <div className="flex items-center justify-between">
          <span className="font-mono text-sm">{code}</span>
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
        <div className="mt-1 text-[10px] text-muted-foreground">
          {quote ? (isSealed ? "封板" : "未封板") : "实时价格待接入"}
          {quote?.limit_up_price ? ` · 涨停 ${quote.limit_up_price.toFixed(2)}` : ""}
        </div>
      </GlassCard>
    </Link>
  );
}
