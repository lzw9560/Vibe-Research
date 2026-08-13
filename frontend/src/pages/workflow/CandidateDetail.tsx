// 候选标的诊断卡（S023 E4 + S031 R18 抽屉复用 + S033 R6 工作流状态卡）：
// - CandidateDetailPanel({code, date})：纯展示，调 candidatesApi.diagnosis(code)，内 Skeleton/错误态；
//   底部嵌 WorkflowStateCard（date 缺省时后端按最近交易日）。
// - CandidateDetail（路由页）：thin 包装——useParams 取 code + 返回按钮 + Panel。
// 合规：仅客观数据 + 命中规则 + 客观状态记录，不输出方向结论词。
import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { candidatesApi, type DiagnosisCard, type IndicatorSet } from "@/lib/candidates";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { WorkflowStateCard } from "@/components/workflow/WorkflowStateCard";

/** 问 AI 上下文——注入候选诊断卡真实数据 */
function buildCandidateContext(card: DiagnosisCard | null, code: string): string {
  if (!card) return `当前页面：候选详情 - ${code}\n诊断卡：未取得`;
  const ind = card.indicators;
  const eight = card.eight_standards;
  return [
    `当前页面：候选详情 - ${card.code} ${card.name}`,
    `活跃度：${card.activity?.tier ?? "--"}（命中规则：${card.activity?.rules_applied?.join("、") || "无"}）`,
    ind ? `量价：现价${ind.price ?? "--"}/涨跌${ind.change_pct != null ? ind.change_pct.toFixed(2) : "--"}%/换手${ind.turnover_pct ?? "--"}%/量比${ind.vol_ratio ?? "--"}/成交额${ind.amount_yi ?? "--"}亿/振幅${ind.amplitude_pct ?? "--"}%` : `量价：未取得`,
    ind ? `连板：${ind.consec_boards ?? "--"}板/封单额${ind.seal_amount != null ? (ind.seal_amount / 1e4).toFixed(0) + "万" : "--"}/竞价高开${ind.auction_open_pct ?? "--"}%` : `连板：未取得`,
    ind ? `资金：主力净流入${ind.main_net_inflow ?? "--"}/5日${ind.main_net_5d ?? "--"}/北向${ind.northbound ?? "--"}/龙虎席${ind.dragon_tiger_inst_net ?? "--"}` : `资金：未取得`,
    ind ? `均线：MA5=${ind.ma5 ?? "--"}/MA10=${ind.ma10 ?? "--"}/MA20=${ind.ma20 ?? "--"}` : `均线：未取得`,
    `风险标记：${card.risk_flags?.length ? card.risk_flags.join("、") : "无"}`,
    eight ? `八项标准：${eight.items.filter((i) => i.status === "pass").length}过/${eight.fail_count}fail/${eight.missing_count}missing${card.capped ? "（已封顶55）" : ""}` : `八项标准：未取得`,
    `取数时点：${card.as_of}`,
  ].join("\n");
}

export default function CandidateDetail() {
  const { code = "" } = useParams<{ code: string }>();
  const navigate = useNavigate();
  return (
    <div className="space-y-4 p-4">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 返回
      </button>
      <CandidateDetailPanel code={code} />
    </div>
  );
}

/** S031 R18：候选诊断卡纯展示组件——路由页与 Sheet 抽屉共用。
 * S033：date 由抽屉传 briefing.data_date；路由页不传（状态卡内用 state.trade_date 回填）。 */
export function CandidateDetailPanel({ code, date }: { code: string; date?: string }) {
  const [card, setCard] = useState<DiagnosisCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    // S049 C3：diagnosis 调用透传 date（抽屉查看快照日期时取该日诊断卡）
    candidatesApi
      .diagnosis(code, date)
      .then((c) => alive && setCard(c))
      .catch((e) => alive && setError(String(e?.message ?? e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [code, date]);

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton variant="rectangular" className="h-24" />
        <Skeleton variant="rectangular" className="h-20" />
        <Skeleton variant="rectangular" className="h-20" />
      </div>
    );
  }
  if (error) return <div className="p-6 text-sm text-danger">取数失败：{error}</div>;
  if (!card) return <div className="p-6 text-sm text-muted-foreground">无数据</div>;

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold">{card.name}</h2>
            <p className="text-xs text-muted-foreground">{card.code}</p>
          </div>
          <div className="flex items-center gap-3">
            <AskAiButton context={buildCandidateContext(card, code)} />
            <span className="text-sm text-muted-foreground">
              活跃度档位：<b className="text-foreground">{card.activity?.tier}</b>
            </span>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">取数时点：{card.as_of}</p>
      </GlassCard>

      <GlassCard className="p-4">
        <h3 className="mb-2 text-sm font-semibold">命中规则（怎么选的）</h3>
        {card.activity?.rules_applied?.length ? (
          <ul className="space-y-1 text-sm">
            {card.activity.rules_applied.map((r, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-muted-foreground">•</span> {r}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">无规则命中记录</p>
        )}
      </GlassCard>

      <IndicatorBlock title="量价" ind={card.indicators} />
      <IndicatorBlock title="情绪梯队" ind={card.indicators} />
      <IndicatorBlock title="资金流" ind={card.indicators} />

      {card.risk_flags?.length > 0 && (
        <GlassCard className="p-4">
          <h3 className="mb-2 text-sm font-semibold">风险标注</h3>
          <div className="flex flex-wrap gap-2">
            {card.risk_flags.map((f, i) => (
              <span key={i} className="rounded bg-warning/10 px-2 py-0.5 text-xs text-warning">{f}</span>
            ))}
          </div>
        </GlassCard>
      )}

      {Object.keys(card.indicators?.missing ?? {}).length > 0 && (
        <GlassCard className="p-4">
          <h3 className="mb-2 text-sm font-semibold">未取得（原因透明）</h3>
          <ul className="space-y-1 text-sm">
            {Object.entries(card.indicators.missing).map(([k, v]) => (
              <li key={k} className="flex justify-between">
                <span className="text-muted-foreground">{k}</span>
                <span>{v}</span>
              </li>
            ))}
          </ul>
        </GlassCard>
      )}

      {/* S033 R6：工作流状态卡——当前态徽标 + 流转历史 + 流转按钮 */}
      <WorkflowStateCard code={code} date={date} />
    </div>
  );
}

/** 指标块：呈现一组指标的取值 + 缺失标注。 */
function IndicatorBlock({ title, ind }: { title: string; ind: IndicatorSet }) {
  const groups: Record<string, [string, keyof IndicatorSet][]> = {
    量价: [
      ["换手率%", "turnover_pct"], ["量比", "vol_ratio"], ["成交额(亿)", "amount_yi"], ["振幅%", "amplitude_pct"],
      ["竞价开盘%", "auction_open_pct"],
    ],
    情绪梯队: [
      ["连板数", "consec_boards"],
    ],
    资金流: [
      ["主力净流入", "main_net_inflow"], ["5日累计", "main_net_5d"], ["龙虎榜机构", "dragon_tiger_inst_net"], ["北向", "northbound"],
    ],
  };
  const fields = groups[title] ?? [];
  return (
    <GlassCard className="p-4">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {fields.map(([label, key]) => {
          const val = ind[key] as number | null | undefined;
          const missing = ind.missing?.[String(key)];
          return (
            <div key={String(key)} className="rounded bg-muted/30 p-2">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="font-mono">
                {missing ? <span className="text-warning">未取得</span> : val != null ? val : "—"}
              </p>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}
