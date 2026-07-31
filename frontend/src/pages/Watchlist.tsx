import { useEffect, useMemo, useState } from "react";
import { Plus, X, RefreshCw, Star } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { useQuote } from "@/lib/query";
import { saveWatch, apiWatchlist, addCodes } from "@/lib/watchlist";
import { cn } from "@/lib/utils";

// A 股红涨绿跌（与整个看板一致）。
const color = (v: number | undefined) =>
  v == null ? "text-muted-foreground" : v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-muted-foreground";
const pct = (v: number | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);

export function Watchlist() {
  const [codes, setCodes] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [hint, setHint] = useState<string | null>(null);

  // T9：原 useState(quotes/loading) + useEffect(refresh on ready) → useQuote(codes)。
  // codes 在 queryKey 中，增删自选后 codes 变化 → 自动重新查询（arg-driven requery）；
  // 手动刷新按钮走 refetch()。
  // 注：useQuote 经 Opts 参数化 data 已推断为 Record<string, Quote> | undefined，无需 cast。
  const { data: quotes, isLoading: loading, refetch } = useQuote(codes.join(","));

  // 初始化：从 API 加载自选股（codes 变非空后 useQuote 自动启用并发请求）
  useEffect(() => {
    apiWatchlist.fetch().then((cs) => setCodes(cs));
  }, []);

  const add = async () => {
    const { next, added } = addCodes(codes, input);
    if (added === 0) {
      setHint(input.trim() ? "没识别到新的 6 位代码（可能已在自选里）" : null);
      setInput("");
      return;
    }
    const result = await apiWatchlist.add(next);
    setCodes(next);
    saveWatch(next); // localStorage fallback 同步
    setInput("");
    setHint(`已添加 ${result.added} 只`);
    // codes 变化 → useQuote queryKey 变化 → 自动重新查询
  };

  const remove = async (c: string) => {
    await apiWatchlist.remove(c);
    // 重新从后端拉取最新列表，避免前后端状态不一致
    const updated = await apiWatchlist.fetch();
    setCodes(updated);
    saveWatch(updated);
    // codes 变化 → useQuote queryKey 变化 → 自动重新查询
  };

  const aiContext = useMemo(
    () =>
      codes.length
        ? "我的自选股：\n" +
          codes
            .map((c) => {
              const q = quotes?.[c];
              return q
                ? `${q.name}(${c}) 现价${q.price} ${pct(q.change_pct)} PE(TTM)${q.pe_ttm ?? "—"} 换手${q.turnover_rate ?? "—"}%`
                : `${c}（行情未取到）`;
            })
            .join("\n")
        : "还没有自选股。",
    [codes, quotes],
  );

  return (
    <div>
      <PageHeader
        title="自选股"
        subtitle="批量添加、一屏总览你关注的标的。数据已同步到云端。"
        actions={
          codes.length > 0 && (
            <AskAiButton
              context={aiContext}
              label="让 AI 读自选"
              suggestions={["这几只里哪些估值偏高", "帮我按赛道分组看看", "各自最大的风险点是什么"]}
            />
          )
        }
      />

      <GlassCard className="mb-4">
        <label className="mb-1.5 block text-xs text-muted-foreground">
          批量添加 —— 粘贴一串代码即可（逗号 / 空格 / 换行都行，自动识别 6 位 A 股代码）
        </label>
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add();
            }}
            rows={2}
            placeholder={"如：600519 000858, 002463\n300750 688017"}
            className="flex-1 resize-y rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <Button onClick={add} className="self-start">
            <Plus className="h-4 w-4" /> 添加
          </Button>
        </div>
        {hint && <p className="mt-2 text-xs text-muted-foreground/70">{hint}</p>}
      </GlassCard>

      <GlassCard glow>
        <SectionHeader
          title="自选总览"
          icon={<Star className="h-4 w-4 text-primary" />}
          action={
            <button
              onClick={() => refetch()}
              disabled={loading || !codes.length}
              className="text-muted-foreground hover:text-primary"
              title="刷新价格"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            </button>
          }
        />
        {codes.length === 0 ? (
          <EmptyState
            icon={<Star className="h-8 w-8 text-muted-foreground/40" />}
            title="还没有自选股"
            description="用上面的框粘贴一串代码批量添加。"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["名称", "代码", "现价", "涨跌%", "PE(TTM)", "PB", "换手%", ""].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {codes.map((c) => {
                  const q = quotes?.[c];
                  return (
                    <tr key={c} className="border-b border-border/30">
                      <td className="px-2 py-2.5 font-medium">{q?.name || "—"}</td>
                      <td className="px-2 py-2.5 font-mono text-xs text-muted-foreground">{c}</td>
                      <td className={cn("px-2 py-2.5 font-mono", color(q?.change_pct))}>{q ? q.price : "—"}</td>
                      <td className={cn("px-2 py-2.5 font-mono", color(q?.change_pct))}>{q ? pct(q.change_pct) : "—"}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{q?.pe_ttm ?? "—"}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{q?.pb ?? "—"}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{q?.turnover_rate ?? "—"}</td>
                      <td className="px-2 py-2.5">
                        <button
                          onClick={() => remove(c)}
                          className="text-muted-foreground/50 hover:text-destructive"
                          title="移除"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      <Disclaimer />
    </div>
  );
}
