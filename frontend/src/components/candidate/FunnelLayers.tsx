// 漏斗各层卡片：筛选条件 + 通过候选 + 调参重跑（S023 F2/F5）。
// 交互：调参→重跑该层→展示新结果→"下游全跑"按钮→用户点才往下。
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { FunnelLayer } from "@/lib/candidates";
import { candidatesApi } from "@/lib/candidates";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";

export function FunnelLayers({ layers, date }: { layers: FunnelLayer[]; date?: string }) {
  const navigate = useNavigate();
  if (!layers.length) return null;
  return (
    <div className="space-y-3">
      <SectionHeader title="漏斗各层" subtitle="筛选条件 / 通过候选 / 可调参重跑" />
      {layers.map((l) => (
        <FunnelLayerCard key={l.layer_id} layer={l} date={date} onPick={(code) => navigate(`/workflow/candidates/${code}`)} />
      ))}
    </div>
  );
}

function FunnelLayerCard({ layer, date, onPick }: { layer: FunnelLayer; date?: string; onPick: (code: string) => void }) {
  const [rerunResult, setRerunResult] = useState<FunnelLayer | null>(null);
  const [showDownBtn, setShowDownBtn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [turnoverInput, setTurnoverInput] = useState("");

  const display = rerunResult ?? layer;
  const missing = display.data_status === "未取得";

  const handleRerun = async () => {
    setBusy(true);
    try {
      const body = turnoverInput ? { turnover_cold: Number(turnoverInput) } : undefined;
      const res = await candidatesApi.rerunLayer(layer.layer_id, date, body);
      setRerunResult(res.layer);
      setShowDownBtn(true);
    } finally {
      setBusy(false);
    }
  };

  const handleRerunDownstream = async () => {
    setBusy(true);
    try {
      await candidatesApi.rerunDownstream(layer.layer_id, date);
      setShowDownBtn(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <GlassCard className="p-4">
      {/* 层标题 + 计数 */}
      <div className="flex items-center justify-between">
        <div className="font-medium">
          <span className="mr-2 text-muted-foreground">{display.layer_id}</span>
          {display.name}
        </div>
        <div className="text-sm text-muted-foreground">
          输入 <span className="text-foreground">{display.input_count}</span> → 输出{" "}
          <span className="text-foreground">{display.output_count}</span>
        </div>
      </div>

      {/* 数据未取得 */}
      {missing && (
        <div className="mt-2 text-sm text-warning">该层数据未取得：{display.data_reason}</div>
      )}

      {/* 筛选条件 */}
      {display.conditions && display.conditions.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs text-muted-foreground">筛选条件</div>
          <div className="flex flex-wrap gap-1">
            {display.conditions.map((c, i) => (
              <span key={i} className="rounded bg-muted/40 px-2 py-0.5 text-xs">{c}</span>
            ))}
          </div>
        </div>
      )}

      {/* 通过候选 */}
      {!missing && display.passed && display.passed.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs text-muted-foreground">通过候选（{display.passed.length}）</div>
          <div className="space-y-0.5">
            {display.passed.slice(0, 15).map((c) => (
              <button
                key={c.code}
                onClick={() => onPick(c.code)}
                className="flex w-full justify-between rounded px-2 py-1 text-left text-sm hover:bg-muted/50"
              >
                <span>{c.name} <span className="text-xs text-muted-foreground">{c.code}</span></span>
              </button>
            ))}
            {display.passed.length > 15 && <div className="text-xs text-muted-foreground">…共 {display.passed.length} 条</div>}
          </div>
        </div>
      )}

      {/* 被过滤 */}
      {display.filtered_out.length > 0 && (
        <div className="mt-3 grid gap-1 text-sm">
          <div className="text-muted-foreground">被过滤（{display.filtered_out.length}）：</div>
          {display.filtered_out.slice(0, 10).map((f) => (
            <div key={f.code} className="flex justify-between">
              <span>{f.name ? `${f.name} ${f.code}` : f.code}</span>
              <span className="text-muted-foreground">{f.reason}</span>
            </div>
          ))}
        </div>
      )}

      {/* 调参重跑（调试期灵活） */}
      {!missing && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border/50 pt-3">
          <input
            value={turnoverInput}
            onChange={(e) => setTurnoverInput(e.target.value)}
            placeholder="换手冷档%（如 10）"
            className="w-36 rounded border border-border bg-transparent px-2 py-1 text-sm"
          />
          <button
            onClick={handleRerun}
            disabled={busy}
            className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
          >
            {busy ? "重跑中…" : "重跑此层"}
          </button>
          {showDownBtn && (
            <button
              onClick={handleRerunDownstream}
              disabled={busy}
              className="rounded bg-accent px-3 py-1 text-sm disabled:opacity-50"
            >
              下游全跑
            </button>
          )}
        </div>
      )}
    </GlassCard>
  );
}
