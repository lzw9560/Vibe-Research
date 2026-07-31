// S005 中长线价值选股漏斗 — 主页
import { useState } from "react";
import { loadLlm } from "@/lib/llm";
import {
  runValueFunnel, deepAi,
  type ValueFunnelResult, type QualityAssessment, type DeepAnalysisSkeleton,
} from "@/lib/value_funnel";
import { ApiError } from "@/lib/api";

export function ValueFunnel() {
  const [direction, setDirection] = useState("");
  const [stage, setStage] = useState("all");
  const [result, setResult] = useState<ValueFunnelResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function onRun() {
    if (!direction.trim()) { setErr("请输入行业/主题/指数"); return; }
    setLoading(true); setErr("");
    try {
      const r = await runValueFunnel(direction.trim(), stage);
      setResult(r);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setLoading(false); }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">中长线价值选股漏斗</h1>
        <p className="text-sm text-gray-500">
          输入行业/主题/指数 → L1 全市场扫描 → L2 去劣7条 → L3 精细分析 → L4 四大师深度（文字交 AI）
        </p>
      </header>

      {/* 输入 */}
      <div className="flex gap-2 items-end flex-wrap">
        <div className="flex-1 min-w-[240px]">
          <label className="text-xs text-gray-500">行业/主题/指数</label>
          <input
            value={direction} onChange={(e) => setDirection(e.target.value)}
            placeholder="如：AI算力 / 创新药 / 沪深300"
            className="w-full border rounded px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-gray-500">阶段</label>
          <select value={stage} onChange={(e) => setStage(e.target.value)}
            className="border rounded px-2 py-2 text-sm">
            <option value="all">全流程</option>
            <option value="L1">L1 扫描</option>
            <option value="L2">L2 去劣</option>
            <option value="L3">L3 分析</option>
            <option value="L4">L4 深度</option>
          </select>
        </div>
        <button onClick={onRun} disabled={loading}
          className="bg-orange-500 text-white px-4 py-2 rounded text-sm disabled:opacity-50">
          {loading ? "运行中…" : "运行漏斗"}
        </button>
      </div>
      {err && <div className="text-red-500 text-sm">{err}</div>}

      {result && (
        <>
          <FunnelLayers result={result} />
          <section className="space-y-3">
            <h2 className="text-lg font-semibold">L2 去劣 + 护城河（{Object.keys(result.l2_assessments).length}）</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {Object.entries(result.l2_assessments).map(([code, qa]) => (
                <QualityCard key={code} code={code} qa={qa} />
              ))}
            </div>
          </section>
          <section className="space-y-3">
            <h2 className="text-lg font-semibold">L3 精细分析（{Object.keys(result.l3_analyses).length}）</h2>
            {Object.entries(result.l3_analyses).map(([code, a]) => (
              <div key={code} className="border rounded p-3 text-sm">
                <div className="font-medium">{a.name}（{code}）</div>
                <div className="text-gray-600 mt-1">{a.financials_summary || "（财务数据未取得）"}</div>
                <div className="text-gray-600">{a.valuation_position || "（估值分位未取得）"}</div>
                {a.counter_arguments?.length > 0 && (
                  <div className="text-amber-700 mt-1">反面论据：{a.counter_arguments.join("；")}</div>
                )}
              </div>
            ))}
          </section>
          <section className="space-y-3">
            <h2 className="text-lg font-semibold">L4 四大师深度（终选 {result.l4_finals.length}）</h2>
            {result.l4_finals.map((d) => <DeepSkeleton key={d.code} skeleton={d} />)}
          </section>
        </>
      )}
    </div>
  );
}

// ---------- 漏斗各层 ----------
function FunnelLayers({ result }: { result: ValueFunnelResult }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">漏斗各层</h2>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
        {result.layers.map((l) => (
          <div key={l.layer_id} className="border rounded p-2 text-sm">
            <div className="font-medium">{l.layer_id} · {l.name}</div>
            <div>输入 {l.input_count} → 输出 {l.output_count}</div>
            {l.filtered_out.length > 0 && (
              <details className="mt-1 text-xs text-gray-500">
                <summary>被弃 {l.filtered_out.length}</summary>
                {l.filtered_out.map((f, i) => (
                  <div key={i}>{f.code || "—"}：{f.reason}</div>
                ))}
              </details>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------- 去劣 + 护城河 ----------
function QualityCard({ code, qa }: { code: string; qa: QualityAssessment }) {
  return (
    <div className="border rounded p-3 text-sm">
      <div className="flex justify-between">
        <span className="font-medium">{code}</span>
        <span>通过 {qa.pass_count}/{qa.inapplicable_count > 0 ? 7 - qa.inapplicable_count : 7}</span>
      </div>
      <div className="text-xs text-gray-500">
        绝对 {qa.pass_rate_absolute.toFixed(4)} · 调整 {qa.pass_rate_adjusted?.toFixed(4) ?? "—"}
        {qa.data_years_note && <span className="ml-1 text-amber-700">（{qa.data_years_note}）</span>}
      </div>
      <div className="mt-2 space-y-0.5 text-xs">
        {qa.metrics.map((m) => (
          <div key={m.index} className="flex justify-between">
            <span>
              {m.index}. {m.name}
              {m.exempt && <span className="text-blue-600"> 豁免{m.exempt_rule}</span>}
            </span>
            <span className={
              m.inapplicable ? "text-gray-400" :
              m.missing ? "text-gray-400" :
              m.passed ? "text-green-600" : "text-red-600"
            }>
              {m.inapplicable ? "不适用" : m.missing ? "未取得" : m.passed ? "通过" : "未通过"}
              {m.value != null ? ` (${m.value})` : ""}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 text-xs text-gray-500 border-t pt-1">
        护城河代理：毛利率持续{qa.moat.gross_margin_persistence ? "高" : "—"} ·
        ROE均值{qa.moat.roe_stability ?? "—"}%
        <div className="text-[10px]">{qa.moat.note}</div>
      </div>
    </div>
  );
}

// ---------- L4 四大师（交AI） ----------
function DeepSkeleton({ skeleton }: { skeleton: DeepAnalysisSkeleton }) {
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(skeleton);
  const [err, setErr] = useState("");

  async function onAi() {
    const llm = loadLlm();
    const isCli = llm?.provider?.startsWith("cli-");
    if (!llm || (!isCli && !llm.baseURL)) {
      setErr("请先在「接入 AI」配置（API 接入需 baseURL+key，或用订阅接入 cli-claude）");
      return;
    }
    setBusy(true); setErr("");
    try {
      const r = await deepAi(data.code, {
        provider: llm.provider || "", baseURL: llm.baseURL || "",
        apiKey: llm.apiKey || "", model: llm.model,
      });
      setData(r);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="border rounded p-3 text-sm space-y-2">
      <div className="flex justify-between items-center">
        <span className="font-medium">{data.name}（{data.code}）</span>
        <button onClick={onAi} disabled={busy || !data.ai_pending}
          className="px-3 py-1 rounded text-xs bg-blue-600 text-white disabled:opacity-50"
          title={data.ai_pending ? "调 AI 填四大师文字" : "已生成"}>
          {busy ? "AI 生成中…" : data.ai_pending ? "交 AI 生成" : "已生成"}
        </button>
      </div>
      {err && <div className="text-red-500 text-xs">{err}</div>}
      <div className="space-y-2">
        {data.perspectives.map((p) => (
          <div key={p.master} className="border-l-2 border-gray-300 pl-2">
            <div className="font-medium text-xs">【{p.master}】{p.framework}</div>
            <div className="text-xs text-gray-500">数据：{p.data_skeleton}</div>
            {p.ai_text && <div className="text-xs mt-1 whitespace-pre-wrap">{p.ai_text}</div>}
            {!p.ai_text && <div className="text-xs text-gray-400">（待 AI 生成）</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
