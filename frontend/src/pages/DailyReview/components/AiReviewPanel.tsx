/** AI 当日复盘 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { GlassCard } from "@/components/ui/GlassCard";
import { Sparkles, Loader2, AlertCircle } from "lucide-react";
import { hasLlm, chatStream } from "@/lib/llm";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";
import { ApiError } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  dataSummary: string;
  today: string;
}
export function AiReviewPanel({ dataSummary, today }: Props) {
  const [review, setReview] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [needConfig, setNeedConfig] = useState(false);

  const run = async () => {
    setErr(null); setNeedConfig(false);
    if (!hasLlm()) { setNeedConfig(true); return; }
    setLoading(true); setReview("");
    const prompt = `以下是今天 A 股大盘的客观数据：\n${dataSummary}\n\n请用中文做一段当天大盘复盘：整体涨跌、主要指数表现、盘面值得注意的点。只做客观陈述与多视角分析，不预测涨跌、不推荐任何标的、不构成投资建议。`;
    try {
      await chatStream([{ role: "user", content: prompt }], `今日大盘数据：${dataSummary}`, {
        onDelta: (t) => setReview((r) => r + t),
      });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "复盘失败");
    } finally { setLoading(false); }
  };

  return (
    <>
      <GlassCard glow className="mb-6">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 font-semibold"><Sparkles className="h-4 w-4 text-primary" /> AI 当日复盘</h3>
          <button onClick={run} disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {review ? "重新复盘" : "让 AI 复盘今天"}
          </button>
        </div>
        {needConfig && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground">
            <AlertCircle className="h-4 w-4 shrink-0 text-warning" />
            还没接入 AI。<Link to="/settings" className="text-primary">先去接入你的 AI</Link>，之后一键出复盘。
          </div>
        )}
        {err && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {err}
          </div>
        )}
        {review ? (
          <>
            <div className="prose prose-sm prose-invert mt-4 max-w-none text-foreground"><ReactMarkdown remarkPlugins={[remarkGfm]}>{review}</ReactMarkdown></div>
            {!loading && <div className="mt-3"><SaveNoteButton kind="复盘" title={`每日复盘 ${today}`} content={review} /></div>}
          </>
        ) : !needConfig && !err && !loading ? (
          <p className="mt-3 text-sm text-muted-foreground">点上方按钮，系统把当天客观数据打包给你的 AI，由它生成复盘。<b className="text-foreground">分析是它给的，我们只负责喂数据。</b></p>
        ) : null}
      </GlassCard>
      <Disclaimer />
    </>
  );
}
