// 漏斗各层卡片（S023 F2/F5 + S031 R16 公共 FunnelLayerCard 抽取）。
// 交互：调参→重跑该层→展示新结果→"下游全跑"按钮→用户点才往下。
// S031：渲染委托公共 FunnelLayerCard，本文件只持有 rerun/downstream 状态 + footer 槽注入。
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { FunnelLayer } from "@/lib/candidates";
import { candidatesApi } from "@/lib/candidates";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { FunnelLayerCard } from "@/components/ui/FunnelLayerCard";

export function FunnelLayers({ layers, date, onPick }: { layers: FunnelLayer[]; date?: string; onPick?: (code: string) => void }) {
  const navigate = useNavigate();
  const pick = onPick ?? ((code: string) => navigate(`/workflow/candidates/${code}`));
  if (!layers.length) return null;
  return (
    <div className="space-y-3">
      <SectionHeader title="漏斗各层" subtitle="筛选条件 / 通过候选 / 可调参重跑" />
      {layers.map((l) => (
        <FunnelLayerRow key={l.layer_id} layer={l} date={date} onPick={pick} />
      ))}
    </div>
  );
}

function FunnelLayerRow({ layer, date, onPick }: { layer: FunnelLayer; date?: string; onPick: (code: string) => void }) {
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

  const footer = !missing ? (
    <>
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
    </>
  ) : null;

  return <FunnelLayerCard layer={display} variant="neutral" onPick={onPick} footer={footer} date={date} />;
}
