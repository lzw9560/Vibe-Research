// 候选标的诊断卡详情（S023 E4）：依据链呈现——入口层/规则/取值/missing/阈值档位。
// 合规：仅客观数据 + 命中规则，不输出方向结论词。
import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { candidatesApi, type DiagnosisCard, type IndicatorSet } from "@/lib/candidates";
import { GlassCard } from "@/components/ui/GlassCard";

export default function CandidateDetail() {
  const { code = "" } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const [card, setCard] = useState<DiagnosisCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    candidatesApi
      .diagnosis(code)
      .then((c) => alive && setCard(c))
      .catch((e) => alive && setError(String(e?.message ?? e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [code]);

  if (loading) return <div className="p-6 text-muted-foreground">加载诊断卡…</div>;
  if (error) return <div className="p-6 text-danger">取数失败：{error}</div>;
  if (!card) return <div className="p-6 text-muted-foreground">无数据</div>;

  return (
    <div className="space-y-4 p-4">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 返回
      </button>

      <GlassCard className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold">{card.name}</h2>
            <p className="text-xs text-muted-foreground">{card.code}</p>
          </div>
          <span className="text-sm text-muted-foreground">
            活跃度档位：<b className="text-foreground">{card.activity?.tier}</b>
          </span>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">取数时点：{card.as_of}</p>
      </GlassCard>

      {/* 命中规则（可复现依据） */}
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

      {/* 六类指标取值 */}
      <IndicatorBlock title="量价" ind={card.indicators} />
      <IndicatorBlock title="情绪梯队" ind={card.indicators} />
      <IndicatorBlock title="资金流" ind={card.indicators} />

      {/* 客观风险标注 */}
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

      {/* 数据缺失透明（AC6） */}
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
    </div>
  );
}

/** 指标块：呈现一组指标的取值 + 缺失标注。 */
function IndicatorBlock({ title, ind }: { title: string; ind: IndicatorSet }) {
  const groups: Record<string, [string, keyof IndicatorSet][]> = {
    量价: [
      ["换手率%", "turnover_pct"], ["量比", "vol_ratio"], ["成交额(亿)", "amount_yi"], ["振幅%", "amplitude_pct"],
    ],
    情绪梯队: [
      ["连板数", "consec_boards"], ["封板率%", "seal_rate"], ["炸板率%", "bomb_rate"], ["晋级率%", "advance_rate"],
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
