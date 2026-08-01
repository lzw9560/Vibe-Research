import { X, Info } from "lucide-react";
import {
  type STIResult,
  STI_WEIGHTS,
  DIMENSION_LABELS,
} from "./types";

interface Props {
  data: STIResult | null;
  onClose: () => void;
}

// 权重分布解释
const DIMENSION_EXPLANATIONS: Record<string, string> = {
  limit_up_count: "涨停家数越多，市场活跃度越高",
  limit_down_count: "跌停家数越多，亏钱效应越强（反向指标）",
  seal_rate: "封板率衡量涨停股封住的稳定性",
  advance_decline_ratio: "涨跌家数比，反映市场广度",
  promotion_rate: "晋级率是情绪周期最敏感的指标",
  prev_zt_performance: "昨日涨停股今日表现，反映情绪惯性",
  max_boards: "最高连板数，反映市场风险偏好上限",
};

export function STIDetailView({ data, onClose }: Props) {
  if (!data || !data.dimensions) return null;

  const dims = data.dimensions;
  const dimValues: Array<{ key: string; label: string; value: number; weight: number; direction: string }> = [
    { key: "limit_up_count", label: DIMENSION_LABELS.limit_up_count, value: dims.limit_up_count, weight: STI_WEIGHTS.limit_up_count, direction: "↑" },
    { key: "limit_down_count", label: DIMENSION_LABELS.limit_down_count, value: dims.limit_down_count, weight: STI_WEIGHTS.limit_down_count, direction: "↓" },
    { key: "seal_rate", label: DIMENSION_LABELS.seal_rate, value: dims.seal_rate, weight: STI_WEIGHTS.seal_rate, direction: "↑" },
    { key: "advance_decline_ratio", label: DIMENSION_LABELS.advance_decline_ratio, value: dims.advance_decline_ratio, weight: STI_WEIGHTS.advance_decline_ratio, direction: "↑" },
    { key: "promotion_rate", label: DIMENSION_LABELS.promotion_rate, value: dims.promotion_rate, weight: STI_WEIGHTS.promotion_rate, direction: "↑" },
    { key: "prev_zt_performance", label: DIMENSION_LABELS.prev_zt_performance, value: dims.prev_zt_performance, weight: STI_WEIGHTS.prev_zt_performance, direction: "↑" },
    { key: "max_boards", label: DIMENSION_LABELS.max_boards, value: dims.max_boards, weight: STI_WEIGHTS.max_boards, direction: "↑" },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div
        className="mx-4 max-h-[85vh] w-full max-w-2xl overflow-auto rounded-xl border border-border/60 bg-background/95 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold">STI 情绪温度 — 详细分析</h2>
            <p className="text-xs text-muted-foreground">
              {data.date} · 分数 {data.score?.toFixed(1)} · 阶段 {data.phase}
            </p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Summary */}
        <div className="mb-4 rounded-lg bg-muted/20 p-3 text-sm">
          <p className="text-muted-foreground">
            当前市场处于<span className="font-bold text-foreground">{data.phase}</span>阶段
            {data.phase_explanation && <span className="text-muted-foreground/70">（{data.phase_explanation}）</span>},
            STI 分数 {data.score?.toFixed(1)}/100，较昨日{
              data.change_from_yesterday == null ? "无数据" :
              data.change_from_yesterday > 0 ? `上升 ${data.change_from_yesterday.toFixed(1)}` :
              data.change_from_yesterday < 0 ? `下降 ${Math.abs(data.change_from_yesterday).toFixed(1)}` :
              "持平"
            }。
          </p>
        </div>

        {/* Dimension Table */}
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
              <th className="pb-2 pr-4 font-medium">维度</th>
              <th className="pb-2 pr-4 font-medium">归一化分</th>
              <th className="pb-2 pr-4 font-medium">权重</th>
              <th className="pb-2 pr-4 font-medium">方向</th>
              <th className="pb-2 font-medium">解释</th>
            </tr>
          </thead>
          <tbody>
            {dimValues.map((d) => (
              <tr key={d.key} className="border-b border-border/20">
                <td className="pr-4 py-2.5 font-medium">{d.label}</td>
                <td className="pr-4 py-2.5 font-mono">{d.value.toFixed(1)}</td>
                <td className="pr-4 py-2.5 font-mono text-xs">{d.weight}</td>
                <td className="pr-4 py-2.5 text-xs">{d.direction === "↑" ? "正向" : "反向"}</td>
                <td className="py-2.5 text-xs text-muted-foreground/70">{DIMENSION_EXPLANATIONS[d.key]}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Weight Distribution */}
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-muted-foreground">权重分布</p>
          <div className="flex h-6 overflow-hidden rounded bg-muted/30">
            {dimValues.map((d) => (
              <div
                key={d.key}
                className="h-full bg-primary/40"
                style={{ width: `${d.weight * 100}%` }}
                title={`${d.label}: ${d.weight}`}
              />
            ))}
          </div>
          <div className="mt-1 flex flex-wrap gap-2">
            {dimValues.map((d) => (
              <span key={d.key} className="flex items-center gap-1 text-[10px] text-muted-foreground">
                <span className="h-2 w-2 rounded-full bg-primary/50" />
                {d.label} {d.weight}
              </span>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="mt-4 flex items-start gap-1.5 rounded-lg border border-warning/20 bg-warning/[0.03] p-2 text-[11px] leading-relaxed text-muted-foreground/70">
          <Info className="mt-0.5 h-3 w-3 shrink-0 text-warning/60" />
          <span>{data.disclaimer}</span>
        </div>
      </div>
    </div>
  );
}
