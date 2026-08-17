// 漏斗各层卡片（S023 F2/F5 + S031 R16 公共 FunnelLayerCard 抽取）。
// 交互：调参→重跑该层→展示新结果→"下游全跑"按钮→用户点才往下。
// S031：渲染委托公共 FunnelLayerCard，本文件只持有 rerun/downstream 状态 + footer 槽注入。
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { FunnelLayer } from "@/lib/candidates";
import { candidatesApi } from "@/lib/candidates";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { FunnelLayerCard } from "@/components/ui/FunnelLayerCard";
import { useForwardTestSummary } from "@/lib/query/strategy";

export function FunnelLayers({ layers, date, onPick }: { layers: FunnelLayer[]; date?: string; onPick?: (code: string) => void }) {
  const navigate = useNavigate();
  const pick = onPick ?? ((code: string) => navigate(`/workflow/candidates/${code}`));
  if (!layers.length) return null;
  return (
    <div className="space-y-3">
      <HonestyBanner />
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

// S072 §44 诚实标注层：涨停叉 pipeline 信号均无 validated edge，前置可见。
// 调 forward-test verdict（lift/winrate vs random）+ 静态标注各信号 §44 状态。
function HonestyBanner() {
  const { data: ft, isLoading } = useForwardTestSummary();
  // win_rate 单位防御：>1 当百分比，否则 ×100（endpoint 返回百分比，fresh 兜底可能小数）
  const pct = (v?: number) => (v == null ? "—" : `${(v > 1 ? v : v * 100).toFixed(1)}%`);
  const lift = ft?.lift;
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
      <div className="font-semibold text-amber-200">⚠ §44 诚实标注：涨停叉无 validated edge</div>
      <ul className="mt-1 space-y-0.5 text-xs text-amber-100/80">
        <li>· 第一步=当日涨停股池（em_zt_topic_pool，T 日涨停标的 → 选 T+1 候选）</li>
        <li>· screener total_score：Phase 0b 二轮证伪（within-day r≈0，5 因子 CI 全含 0）</li>
        <li>· 策略分：limitup 权重已回等权 placeholder（rebound pooled-r=0.179 是 IID 假象，within-day r=-0.010，已收回主因子）</li>
        <li>· S071 盘前选股：breakout 1.72x&lt;2x 弱正，孤立未并入（universe=1121 涨停史股非当日），定位撕裂待决</li>
      </ul>
      {ft && (
        <div className="mt-2 text-xs text-amber-100/90">
          前向测试（{ft.total_days}天 / {ft.settled_count}已结算）：策略 {pct(ft.win_rate)} vs 随机{" "}
          {pct(ft.random_baseline_win_rate)}，lift {lift != null ? lift.toFixed(3) : "—"}
          （{ft.passed ? "通过" : "未通过"}{ft.is_exploratory ? "，探索性" : ""}）
          {ft.note ? `；${ft.note}` : ""}
        </div>
      )}
      {isLoading && <div className="mt-2 text-xs text-amber-100/60">前向 verdict 加载中…</div>}
    </div>
  );
}
