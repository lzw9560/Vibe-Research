// 候选池主页：漏斗各层 + 最终候选 + 诊断卡抽屉（S002 F5）。
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SelectionPipeline } from "@/components/pipeline/SelectionPipeline";
import { DiagnosisCardView } from "@/components/candidate/DiagnosisCard";
import { ThresholdPanel } from "@/components/candidate/ThresholdPanel";
import { candidatesApi, type DiagnosisCard as Card, type FunnelResult } from "@/lib/candidates";
import { AskAiButton } from "@/components/ui/AskAiButton";

export function Candidates() {
  const [result, setResult] = useState<FunnelResult | null>(null);
  const [finalCards, setFinalCards] = useState<Card[]>([]);
  const [active, setActive] = useState<Card | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (date?: string) => {
    setLoading(true); setErr(null);
    try {
      const r = await candidatesApi.runFunnel("all", date);
      setResult(r);
      setFinalCards(r.final_candidates);
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  };

  // S149 修复：mount 读缓存（GET cache，秒开，默认最近交易日→非交易日也有数据），
  // 不再 POST run（慢 46s + 旧默认今日→周末/盘前 0 候选→空页）。
  // cache 404（首次/缓存清）回退 run（POST，后端默认最近交易日→有数据）。
  // "重跑漏斗"按钮才 POST run。
  const loadCache = async () => {
    setLoading(true); setErr(null);
    try {
      const r = await candidatesApi.readFunnelCache();
      setResult(r);
      setFinalCards(r.final_candidates);
      setLoading(false);
    } catch {
      // cache miss → 回退 run（POST，后端默认 last_trading_date_str→有候选）
      await run();
    }
  };

  useEffect(() => { loadCache(); }, []);

  const openDiagnosis = async (code: string) => {
    try { setActive(await candidatesApi.diagnosis(code)); }
    catch (e: any) { setErr(e?.message || String(e)); }
  };

  // S066 AskAi：注入漏斗各层 + 最终候选
  const askAiContext = [
    `当前页面：候选池（Candidates）`,
    result ? `run_id ${result.run_id} · 日期 ${result.date}` : `漏斗：未运行`,
    result && result.layers.length > 0
      ? `漏斗层：${result.layers.map((l) => `${l.name}(${l.input_count}→${l.output_count})`).join("，")}`
      : ``,
    finalCards.length > 0
      ? `最终候选 ${finalCards.length} 只：${finalCards.slice(0, 10).map((c) => `${c.code}(${c.name}${c.capped ? "/封顶" : ""})`).join("，")}`
      : `最终候选：空`,
    finalCards.length > 0
      ? `候选风险标注：${finalCards.slice(0, 5).map((c) => `${c.code}:${c.risk_flags.length ? c.risk_flags.join("/") : "无风险"}`).join("，")}`
      : ``,
  ].filter(Boolean).join("\n");

  return (
    <div className="space-y-4">
      <PageHeader title="候选池" subtitle="盘前漏斗式筛选 + 个股诊断卡（统一口径）" actions={<AskAiButton context={askAiContext} />} />
      <div className="text-xs text-muted-foreground">
        本页仅呈现客观事实与可复现分档，不输出买卖方向/参考价位。方向判断由用户 AI 给出。
      </div>
      <Disclaimer />

      <ThresholdPanel />

      <GlassCard className="p-4 flex items-center gap-2">
        <Button onClick={() => run()} disabled={loading}>{loading ? "运行中…" : "重跑漏斗"}</Button>
        {result && (
          <span className="text-sm text-muted-foreground">
            run_id {result.run_id} · 最终候选 {finalCards.length}
          </span>
        )}
      </GlassCard>

      {err && <div className="text-sm text-danger">{err}</div>}

      {result && (
        <SelectionPipeline
          funnelResult={result}
          mode="funnel-only"
          date={result.date}
          onPick={openDiagnosis}
          rerunHandlers={candidatesApi}
        />
      )}

      {active && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={() => setActive(null)}>
          <div className="max-w-2xl w-full max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <DiagnosisCardView card={active} />
          </div>
        </div>
      )}
    </div>
  );
}
