import { useState, useRef, useEffect, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Send, Loader2, AlertCircle, Trash2, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { cn } from "@/lib/utils";
import { chatStream, hasLlm, type ChatMsg } from "@/lib/llm";

// FE-3（backlog）：前端 chat 网页对话入口——不依赖飞书 bot 也能网页对话（调 /api/chat 流式）。
// 跟飞书 bot 互补：bot 是推送式（问股带融合研判静默注入 context），本页是交互式（用户主动多轮对话）。
// 简单实现：消息列表 + 输入框 + 流式吐字 + markdown 渲染。不持久化（AskAiButton 有持久化，本页轻量）。
export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const hasLlmCfg = hasLlm();

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setError(null);
    const userMsg: ChatMsg = { role: "user", content: text };
    const assistantMsg: ChatMsg = { role: "assistant", content: "" };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setLoading(true);

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await chatStream(
        [...messages, userMsg],
        "",
        {
          onDelta: (delta) => {
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                ...next[next.length - 1],
                content: next[next.length - 1].content + delta,
              };
              return next;
            });
          },
        },
        ctrl.signal,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "对话失败";
      setError(msg);
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }

  function handleClear() {
    setMessages([]);
    setError(null);
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="AI 对话" subtitle="网页直接对话（调 /api/chat 流式），不依赖飞书 bot" />
      {!hasLlmCfg && (
        <GlassCard className="p-4 text-sm text-amber-600">
          <AlertCircle className="mr-2 inline h-4 w-4" />
          未配置 LLM，先去 <Link to="/settings" className="underline">设置</Link> 配一个（API/预设/订阅 CLI 均可）。
        </GlassCard>
      )}
      <GlassCard className="flex h-[68vh] flex-col overflow-hidden">
        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              <Sparkles className="mr-2 h-4 w-4" />问点什么，例如「分析 600519」
            </div>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={cn(
                "flex flex-col gap-1 rounded-lg p-3 text-sm",
                m.role === "user" ? "bg-blue-50 dark:bg-blue-950/30" : "bg-muted/30 dark:bg-gray-900/40",
              )}
            >
              <div className="text-xs font-medium text-muted-foreground">
                {m.role === "user" ? "你" : "AI"}
              </div>
              <div className="prose prose-sm max-w-none dark:prose-invert">
                {m.role === "assistant" ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || (loading && i === messages.length - 1 ? "…" : "")}</ReactMarkdown>
                ) : (
                  m.content
                )}
              </div>
            </div>
          ))}
        </div>
        {error && (
          <div className="border-t border-red-200 px-4 py-2 text-sm text-red-600 dark:border-red-900">
            <AlertCircle className="mr-2 inline h-4 w-4" />{error}
          </div>
        )}
        <form onSubmit={handleSend} className="flex items-center gap-2 border-t p-3 dark:border-gray-800">
          <button
            type="button"
            onClick={handleClear}
            className="rounded p-2 text-muted-foreground hover:bg-muted/30 dark:hover:bg-gray-800"
            title="清空对话"
            disabled={messages.length === 0}
          >
            <Trash2 className="h-4 w-4" />
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="问点什么…（支持 function calling 查行情/研报/缺口/MACD/RSI）"
            className="flex-1 rounded-lg border px-3 py-2 text-sm dark:bg-gray-900 dark:text-gray-100"
            disabled={loading}
          />
          <button
            type="submit"
            className="rounded-lg bg-primary px-4 py-2 text-sm text-white hover:bg-primary disabled:opacity-50"
            disabled={loading || !input.trim()}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </form>
      </GlassCard>
      <Disclaimer />
    </div>
  );
}
