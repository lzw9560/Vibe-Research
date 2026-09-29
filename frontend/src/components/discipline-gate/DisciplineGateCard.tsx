// components/discipline-gate/DisciplineGateCard.tsx — S231 打板纪律门禁看板。
// 风控工具非 edge 基建。cap=0 terminal BLOCK + C1-C7 7 条件展示。
import { useDisciplineGateVerdict, type DisciplineCondition } from "@/lib/query/discipline_gate";
import { GlassCard } from "@/components/ui/GlassCard";

const STATUS_EMOJI: Record<string, string> = { BLOCK: "🔴", CAUTION: "🟡", PASS: "🟢" };
const LIGHT_COLOR: Record<string, string> = { red: "text-red-500", yellow: "text-amber-500", green: "text-green-500" };

function ConditionRow({ c }: { c: DisciplineCondition }) {
  const emoji = c.pass ? "✅" : c.red_line ? "❌" : "⚠️";
  const val = c.value;
  let valStr: string;
  if (val && typeof val === "object" && !Array.isArray(val)) {
    valStr = Object.entries(val as Record<string, unknown>).map(([k, v]) => `${k}=${v}`).join(", ");
  } else if (Array.isArray(val)) {
    valStr = `scores=${val.join(",")}`;
  } else {
    valStr = String(val);
  }
  const missing = c.missing ? " (missing)" : "";
  return (
    <li className="flex justify-between text-xs">
      <span className="truncate pr-2">{emoji} {c.id} {c.name}{missing}</span>
      <span className="text-muted-foreground">{valStr} (阈值 {String(c.threshold)})</span>
    </li>
  );
}

export function DisciplineGateCard({ date }: { date?: string }) {
  const { data, isLoading, isError } = useDisciplineGateVerdict(date);
  const verdict = data as unknown as { date: string; status: string; cap: number; terminal: boolean; conditions: DisciplineCondition[]; merged_light: string; reasons: string[] } | undefined;

  return (
    <GlassCard className="p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">打板纪律门禁</h3>
        <span className="text-xs text-muted-foreground">{verdict?.date ?? "加载中"} · 风控工具非 edge</span>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : isError ? (
        <p className="text-sm text-red-500">门禁数据未接通</p>
      ) : !verdict ? (
        <p className="text-sm text-muted-foreground">暂无数据</p>
      ) : (
        <div className="space-y-2">
          <p className={`text-sm font-medium ${LIGHT_COLOR[verdict.merged_light] ?? ""}`}>
            {STATUS_EMOJI[verdict.status] ?? "⚪"} 当前判定：{verdict.status}（cap={verdict.cap}）
          </p>
          {verdict.terminal ? (
            <div className="space-y-1">
              <p className="text-xs text-amber-500">⚠️ Terminal BLOCK: cap=0（consecutive_relay falsified ARCHIVED）</p>
              <p className="text-xs text-muted-foreground">不评估 C1-C7——每日产出"市场天气+不交易提醒"</p>
              <p className="text-xs text-muted-foreground">{verdict.reasons.join(" ")}</p>
            </div>
          ) : (
            <div className="space-y-1">
              <p className="text-xs font-medium text-foreground">【7 条件门禁】</p>
              <ul className="space-y-1">
                {verdict.conditions.map((c) => <ConditionRow key={c.id} c={c} />)}
              </ul>
              {verdict.reasons.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-foreground">【不交易理由】</p>
                  {verdict.reasons.map((r, i) => <p key={i} className="text-xs text-muted-foreground">• {r}</p>)}
                </div>
              )}
            </div>
          )}
          <p className="text-xs text-muted-foreground">⚠️ 历史统计特征，市场有风险，真钱仓位与止损你最终决策。</p>
        </div>
      )}
    </GlassCard>
  );
}
