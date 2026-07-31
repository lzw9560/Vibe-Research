import { useState } from "react";
import { Link } from "react-router-dom";
import { Sparkles, Loader2, AlertCircle, RefreshCw, Gauge, ArrowDownUp, TrendingUp, TrendingDown, Plus, X, Flame, BarChart3, Globe } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { ApiError, type IndexQuote, type Quote, type MarketOverview, type ShortTermEmotion, type TurnoverTop, type GlobalIndex, type STIResult, type DailyReviewReport } from "@/lib/api";
import { hasLlm, chatStream } from "@/lib/llm";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";
import { loadWatch, saveWatch, addCodes } from "@/lib/watchlist";
import { cn, pctColor } from "@/lib/utils";
import { STICard } from "@/components/sti/StiCard";
import { STIDetailView } from "@/components/sti/StiDetailView";
import {
  useIndices,
  useGlobalIndices,
  useMarketOverview,
  useEmotion,
  useTurnoverTop,
  useStiLatest,
  useQuote,
  useDailyReview,
} from "@/lib/query";

// A股红涨绿跌。全球市场（美股/港股指数）**也沿用红涨**——与整个看板及东财等中国平台一致，
// 对中国用户最不易看错（Simon 2026-07-05 确认；非国际绿涨惯例，是有意选择，勿改）。
const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const yi = (v: number | null) => (v == null ? "—" : `${fmt(v / 1e8)} 亿`); // 元 → 亿

// 统一把 hook 抛出的 error 折成文案：ApiError 取其 message，其它兜底。
const errMsg = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

export function DailyReview() {
  // T9：8 个只读端点全部由 TanStack Query 接管（原 useState/useEffect + fetch 全部撤除）。
  // AI 当日复盘（chatStream）是写流，保留 useState。refetchOnWindowFocus 全局已关，
  // isFetching 仅在初次加载与点刷新时为 true，与原手写 loading 语义一致。
  const indicesQ = useIndices();
  const globalQ = useGlobalIndices();
  const overviewQ = useMarketOverview();
  const emotionQ = useEmotion();
  const turnoverQ = useTurnoverTop();
  const stiQ = useStiLatest();

  // 关注股票（自选，存本地）
  const [watchCodes, setWatchCodes] = useState<string[]>(loadWatch);
  const [watchInput, setWatchInput] = useState("");
  const quoteQ = useQuote(watchCodes.join(","));

  // 每日复盘报告（日期由用户控制 —— 改日期即改 queryKey，自动重查）
  const [reviewReportDate, setReviewReportDate] = useState(new Date().toISOString().slice(0, 10));
  const reviewQ = useDailyReview(reviewReportDate);

  // AI 当日复盘（chatStream 写流，非只读端点，不走 hook）
  const [review, setReview] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewErr, setReviewErr] = useState<string | null>(null);
  const [needConfig, setNeedConfig] = useState(false);
  // STI 详情弹窗
  const [showStiDetail, setShowStiDetail] = useState(false);
  // 复盘报告标签页
  const [reviewTab, setReviewTab] = useState<"sector" | "zt" | "auction">("sector");

  // ---- 各数据块派生（保持原变量名，JSX 不动）----
  // hook data 已类型化（S013 收紧后），不再需要 as unknown as 窄→宽 cast。
  // 大盘指数：原 .catch(()=>setIdxErr(true)) —— hook error 退化为布尔 idxErr，保持静默兜底。
  const indices: IndexQuote[] = indicesQ.data ?? [];
  const idxErr = !!indicesQ.error;
  // 全球指数：原 .catch(()=>{}) 吞错→空。hook error 不渲染，data ?? [] 兜空。
  const globalIdx: GlobalIndex[] = globalQ.data ?? [];
  // 市场总览：原 .catch(()=>{}) 吞错→null。done = !isLoading（请求是否结束）。
  const overview: MarketOverview | null = overviewQ.data ?? null;
  const ovDone = !overviewQ.isLoading;
  // 短线情绪：同上。
  const emotion: ShortTermEmotion | null = emotionQ.data ?? null;
  const emoDone = !emotionQ.isLoading;
  // 成交额 TOP：同上。
  const turnover: TurnoverTop | null = turnoverQ.data ?? null;
  const toDone = !turnoverQ.isLoading;
  // STI：原显式 stiError 文案，保留映射。
  const sti: STIResult | null = stiQ.data ?? null;
  const stiLoading = stiQ.isFetching;
  const stiError: string | null = stiQ.error ? errMsg(stiQ.error, "STI 加载失败") : null;
  // 关注股票行情：原 .catch(()=>{}) 吞错→空。
  const watchQuotes: Record<string, Quote> = quoteQ.data ?? {};
  const watchLoading = quoteQ.isFetching;
  // 复盘报告：原显式 reviewReportError 文案，保留映射；日期改即重查，刷新按钮走 refetch。
  const reviewReport: DailyReviewReport | null = reviewQ.data ?? null;
  const reviewReportLoading = reviewQ.isFetching;
  const reviewReportError: string | null = reviewQ.error ? errMsg(reviewQ.error, "复盘报告加载失败") : null;

  // 数据块占位：请求没回来 = 加载中；回来了但为空 = 数据源暂不可用（非交易时段/被限流时后端返回空）
  const pending = (done: boolean) => (
    <p className="py-4 text-center text-sm text-muted-foreground/60">
      {done ? "暂无数据：可能是非交易时段或数据源暂时不可用，可点「大盘指数」旁的刷新重试" : "加载中…"}
    </p>
  );

  // 大盘指数旁刷新：原 loadIndices 重拉 7 个端点（不含自选行情）。逐个 refetch。
  const refreshAll = () => {
    void indicesQ.refetch();
    void globalQ.refetch();
    void overviewQ.refetch();
    void emotionQ.refetch();
    void turnoverQ.refetch();
    void stiQ.refetch();
    void reviewQ.refetch();
  };

  const addWatch = () => {
    // 支持一次粘贴多只（逗号 / 空格分隔）；全部无效或重复则清空输入、无副作用。
    // watchCodes 变 → quoteQ 的 queryKey 变 → 自动重查，无需手动 refreshWatch。
    const { next, added } = addCodes(watchCodes, watchInput);
    setWatchInput("");
    if (!added) return;
    setWatchCodes(next);
    saveWatch(next);
  };

  const removeWatch = (c: string) => {
    const next = watchCodes.filter((x) => x !== c);
    setWatchCodes(next);
    saveWatch(next);
  };

  const onReviewDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    // 改日期即改 useDailyReview 的 queryKey，自动重查 —— 无需手动 loadReviewReport。
    setReviewReportDate(e.target.value);
  };

  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });

  const dataSummary = indices.length
    ? indices.map((i) => `${i.name} ${i.price}（${i.change_pct > 0 ? "+" : ""}${i.change_pct}%）`).join("；")
    : "（指数数据未取到）";

  const runReview = async () => {
    setReviewErr(null);
    setNeedConfig(false);
    if (!hasLlm()) { setNeedConfig(true); return; }
    setReviewLoading(true);
    setReview("");
    const prompt =
      `以下是今天 A 股大盘的客观数据：\n${dataSummary}\n\n` +
      "请用中文做一段当天大盘复盘：整体涨跌、主要指数表现、盘面值得注意的点。" +
      "只做客观陈述与多视角分析，不预测涨跌、不推荐任何标的、不构成投资建议。";
    try {
      await chatStream([{ role: "user", content: prompt }], `今日大盘数据：${dataSummary}`, {
        onDelta: (t) => setReview((r) => r + t),
      });
    } catch (e) {
      setReviewErr(e instanceof ApiError ? e.message : "复盘失败");
    } finally {
      setReviewLoading(false);
    }
  };

  const sentiment = overview?.sentiment;
  const sectors = overview?.sectors || [];
  const sentCells = sentiment ? [
    { k: "上涨家数", v: sentiment.up, up: true },
    { k: "下跌家数", v: sentiment.down, up: false },
    { k: "平盘", v: sentiment.flat, up: null },
    { k: "涨停", v: sentiment.zt, up: true },
    { k: "真实涨停", v: sentiment.zt_real, up: true },
    { k: "跌停", v: sentiment.dt, up: false },
    { k: "真实跌停", v: sentiment.dt_real, up: false },
    { k: "活跃度", v: sentiment.active, up: null },
  ] : [];

  return (
    <div>
      <PageHeader
        title="每日复盘"
        subtitle={`${today} · 大盘 / 情绪 / 板块资金一屏看全，交给你的 AI 做复盘`}
        actions={
          <AskAiButton
            context={`今日大盘数据：${dataSummary}`}
            label="问 AI"
            suggestions={["今天大盘怎么走", "哪些指数领涨领跌", "盘面有什么值得注意"]}
          />
        }
      />

      {/* 1. 大盘指数（实时） */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">大盘指数</h3>
        <button onClick={refreshAll} className="text-muted-foreground hover:text-primary" title="刷新"><RefreshCw className="h-3.5 w-3.5" /></button>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {indices.length === 0
          ? [1, 2, 3, 4].map((i) => (
              <GlassCard key={i} className="p-3">
                <p className="text-xs text-muted-foreground">{idxErr ? "行情未接通" : "加载中…"}</p>
                <p className="mt-1 font-mono text-lg font-bold text-muted-foreground/40">—</p>
              </GlassCard>
            ))
          : indices.map((i) => (
              <GlassCard key={i.name} className="p-3">
                <p className="truncate text-xs text-muted-foreground">{i.name}</p>
                <p className={cn("mt-1 font-mono text-lg font-bold", pctColor(i.change_pct))}>{i.price}</p>
                <p className={cn("text-xs", pctColor(i.change_pct))}>{i.change_pct > 0 ? "+" : ""}{i.change_pct}%</p>
              </GlassCard>
            ))}
      </div>

      {/* 1b. 全球市场（隔夜外围脸色：A 股常看美股 / 港股） */}
      {globalIdx.length > 0 && (
        <>
          <div className="mb-3 flex items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Globe className="h-4 w-4" /> 全球市场</h3>
            <span className="text-[11px] text-muted-foreground/50">隔夜外围 · A 股常看美股 / 港股脸色</span>
          </div>
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {globalIdx.map((g) => (
              <GlassCard key={g.key} className="p-3">
                <p className="truncate text-xs text-muted-foreground">{g.name} <span className="text-muted-foreground/40">{g.region}</span></p>
                <p className={cn("mt-1 font-mono text-lg font-bold", g.change_pct == null ? "text-foreground" : pctColor(g.change_pct))}>{g.price ?? "—"}</p>
                <p className={cn("text-xs", g.change_pct == null ? "text-muted-foreground" : pctColor(g.change_pct))}>
                  {g.change_pct == null ? "—" : `${g.change_pct > 0 ? "+" : ""}${g.change_pct}%`}
                </p>
              </GlassCard>
            ))}
          </div>
        </>
      )}

      {/* 1c. 情绪温度指数 (STI) — 与个股数据视觉隔离 */}
      <STICard
        data={sti}
        loading={stiLoading}
        error={stiError}
        onClick={() => setShowStiDetail(true)}
      />

      {/* 2. 关注股票（自选） */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">关注股票</h3>
        {watchCodes.length > 0 && (
          <button onClick={() => quoteQ.refetch()} className="text-muted-foreground hover:text-primary" title="刷新价格">
            {watchLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        )}
      </div>
      <GlassCard className="mb-6">
        <div className="mb-3 flex gap-2">
          <input
            value={watchInput}
            onChange={(e) => setWatchInput(e.target.value.replace(/[^\d,\s]/g, "").slice(0, 80))}
            onKeyDown={(e) => e.key === "Enter" && addWatch()}
            placeholder="加自选：可批量，如 600519 000858"
            className="w-60 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button onClick={addWatch}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25">
            <Plus className="h-4 w-4" /> 增加
          </button>
        </div>
        {watchCodes.length === 0 ? (
          <p className="text-sm text-muted-foreground/60">加上你关注的股票，随时看它们的实时价格与涨跌。数据存本地，不上传。</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {watchCodes.map((c) => {
              const q = watchQuotes[c];
              return (
                <div key={c} className="group relative rounded-lg bg-muted/25 p-3">
                  <button onClick={() => removeWatch(c)} title="移除"
                    className="absolute right-1.5 top-1.5 text-muted-foreground/40 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100">
                    <X className="h-3.5 w-3.5" />
                  </button>
                  <p className="truncate text-xs text-muted-foreground">{q?.name || c}</p>
                  <p className={cn("mt-1 font-mono text-lg font-bold", q ? pctColor(q.change_pct) : "text-muted-foreground/40")}>{q ? q.price : "—"}</p>
                  <p className={cn("text-xs", q ? pctColor(q.change_pct) : "text-muted-foreground/40")}>
                    {q ? `${q.change_pct > 0 ? "+" : ""}${q.change_pct}%` : c}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </GlassCard>

      {/* 3. AI 当日复盘 */}
      <GlassCard glow className="mb-6">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 font-semibold"><Sparkles className="h-4 w-4 text-primary" /> AI 当日复盘</h3>
          <button onClick={runReview} disabled={reviewLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
            {reviewLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {review ? "重新复盘" : "让 AI 复盘今天"}
          </button>
        </div>
        {needConfig && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground">
            <AlertCircle className="h-4 w-4 shrink-0 text-warning" />
            还没接入 AI。<Link to="/settings" className="text-primary">先去接入你的 AI</Link>，之后一键出复盘。
          </div>
        )}
        {reviewErr && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {reviewErr}
          </div>
        )}
        {review ? (
          <>
            <div className="prose prose-sm prose-invert mt-4 max-w-none text-foreground"><ReactMarkdown remarkPlugins={[remarkGfm]}>{review}</ReactMarkdown></div>
            {!reviewLoading && <div className="mt-3"><SaveNoteButton kind="复盘" title={`每日复盘 ${today}`} content={review} /></div>}
          </>
        ) : !needConfig && !reviewErr && !reviewLoading ? (
          <p className="mt-3 text-sm text-muted-foreground">点上方按钮，系统把当天客观数据打包给你的 AI，由它生成复盘。<b className="text-foreground">分析是它给的，我们只负责喂数据。</b></p>
        ) : null}
      </GlassCard>

      {/* 4. 市场情绪 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Gauge className="h-4 w-4" /> 市场情绪</h3>
        {sentiment?.date && <span className="text-[11px] text-muted-foreground/50">{sentiment.date}</span>}
      </div>
      <GlassCard className="mb-6">
        {!sentiment?.breadth ? (
          pending(ovDone)
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                { k: "大盘宽度", v: sentiment.breadth, hint: "冰点 / 偏弱 / 中性 / 偏强 / 普涨" },
                { k: "题材投机", v: sentiment.speculation, hint: "冰点 / 普通 / 活跃 / 亢奋" },
              ].map((m) => (
                <div key={m.k} className="rounded-lg bg-muted/25 p-4">
                  <p className="text-xs text-muted-foreground">{m.k}</p>
                  <p className="mt-1 text-2xl font-bold text-primary">{m.v}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground/60">{m.hint}</p>
                </div>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-4 gap-2">
              {sentCells.map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2 text-center">
                  <p className="truncate text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.up === null ? "text-foreground" : c.up ? "text-danger" : "text-success")}>{c.v}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </GlassCard>

      {/* 4b. 短线情绪（连板梯队 / 打板情绪，聚合口径零个股名） */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Flame className="h-4 w-4" /> 短线情绪</h3>
        <span className="text-[11px] text-muted-foreground/50">连板股 · 打板情绪 · 客观公开榜单</span>
        {emotion?.date && <span className="ml-auto text-[11px] text-muted-foreground/50">{emotion.date}</span>}
      </div>
      <GlassCard className="mb-6">
        {!emotion || emotion.emotion?.limit_up_count === undefined ? (
          pending(emoDone)
        ) : (
          <>
            {/* 关键计数 */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { k: "涨停", v: `${emotion.emotion?.limit_up_count}`, cls: "text-danger" },
                { k: "跌停", v: `${emotion.emotion?.limit_down_count}`, cls: "text-success" },
                { k: "最高连板", v: `${emotion.emotion?.max_boards} 板`, cls: "text-primary" },
                { k: "连板（2板+）", v: `${emotion.lianban_count} 家`, cls: "text-primary" },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/25 p-3 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-xl font-bold", c.cls)}>{c.v}</p>
                </div>
              ))}
            </div>
            {/* 打板情绪比率 */}
            <div className="mt-2 grid grid-cols-3 gap-2">
              {[
                { k: "封板率", v: emotion.emotion?.seal_rate, hint: "封住 / 尝试涨停", strong: true },
                { k: "炸板率", v: emotion.emotion?.broken_rate, hint: "炸板 / 尝试涨停", strong: false },
                { k: "晋级率", v: emotion.emotion?.advance_rate, hint: "昨涨停今又停", strong: true },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.strong ? "text-danger" : "text-success")}>
                    {c.v == null ? "—" : `${(c.v * 100).toFixed(1)}%`}
                  </p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground/50">{c.hint}</p>
                </div>
              ))}
            </div>
            {/* 连板股清单（2 板以上，客观公开榜单） */}
            <div className="mt-3">
              <p className="mb-1.5 text-[11px] text-muted-foreground">连板股（2 板以上连续涨停）· 客观公开榜单，非推荐 / 非预测</p>
              {emotion.lianban_stocks.length === 0 ? (
                <p className="text-xs text-muted-foreground/50">今日无 2 板以上个股</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                        {["名称", "连板", "现价", "涨停%", "成交额", "流通市值", "概念"].map((h) => (
                          <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {emotion.lianban_stocks.map((s) => (
                        <tr key={s.code} className="border-b border-border/30">
                          <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono font-bold text-primary">{s.boards} 板</td>
                          <td className="px-2 py-2 font-mono">{s.price}</td>
                          <td className="px-2 py-2 font-mono text-danger">+{s.pct}%</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.float_cap)}</td>
                          <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </GlassCard>

      {/* 4c. 全市场成交额 TOP20（客观公开榜单） */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><BarChart3 className="h-4 w-4" /> 全市场成交额 TOP20</h3>
        <span className="text-[11px] text-muted-foreground/50">客观公开榜单，非推荐 / 非预测 / 不构成投资建议</span>
        {turnover?.updated && <span className="ml-auto text-[11px] text-muted-foreground/50">{turnover.updated}</span>}
      </div>
      <GlassCard className="mb-6">
        {!turnover || turnover.stocks.length === 0 ? (
          pending(toDone)
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["#", "名称", "现价", "涨跌%", "成交额", "总市值", "行业"].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {turnover.stocks.map((s, i) => (
                  <tr key={s.code} className="border-b border-border/30">
                    <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                    <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                    <td className="px-2 py-2 font-mono">{s.price ?? "—"}</td>
                    <td className={cn("px-2 py-2 font-mono", s.pct == null ? "text-muted-foreground" : pctColor(s.pct))}>
                      {s.pct == null ? "—" : `${s.pct > 0 ? "+" : ""}${s.pct}%`}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 font-mono">{yi(s.amount)}</td>
                    <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.mcap)}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* 5. 板块资金趋势榜（行业） */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><TrendingUp className="h-4 w-4" /> 板块资金趋势榜</h3>
        <span className="text-[11px] text-muted-foreground/50">行业 · 按今日净流入排序</span>
      </div>
      <GlassCard className="mb-6">
        {sectors.length === 0 ? (
          pending(ovDone)
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["行业", "涨跌%", "今日净流入", "流入", "流出", "家数"].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sectors.slice(0, 15).map((s) => (
                  <tr key={s.name} className="border-b border-border/30">
                    <td className="px-2 py-2 font-medium">{s.name}</td>
                    <td className={cn("px-2 py-2 font-mono", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</td>
                    <td className={cn("px-2 py-2 font-mono", pctColor(s.net))}>{s.net > 0 ? "+" : ""}{fmt(s.net)} 亿</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{fmt(s.inflow)}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{fmt(s.outflow)}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{s.firms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* 6. 资金轮动 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><ArrowDownUp className="h-4 w-4" /> 资金轮动</h3>
        <span className="text-[11px] text-muted-foreground/50">板块级净流入 / 流出</span>
      </div>
      <div className="mb-2 grid gap-4 md:grid-cols-2">
        {[
          { title: "流入 Top", icon: TrendingUp, color: "text-danger", rows: sectors.slice(0, 6) },
          { title: "流出 Top", icon: TrendingDown, color: "text-success", rows: [...sectors].slice(-6).reverse() },
        ].map((col) => (
          <GlassCard key={col.title}>
            <h4 className={cn("mb-3 flex items-center gap-1.5 text-sm font-semibold", col.color)}><col.icon className="h-4 w-4" /> {col.title}</h4>
            {col.rows.length === 0 ? (
              pending(ovDone)
            ) : (
              <div className="space-y-1.5">
                {col.rows.map((s, i) => (
                  <div key={s.name} className="flex items-center gap-3 border-b border-border/30 pb-1.5 text-sm last:border-0">
                    <span className="w-5 text-xs text-muted-foreground/50">{i + 1}</span>
                    <span className="flex-1 truncate">{s.name}</span>
                    <span className={cn("font-mono text-xs", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</span>
                    <span className={cn("w-20 text-right font-mono text-xs", pctColor(s.net))}>{s.net > 0 ? "+" : ""}{fmt(s.net)} 亿</span>
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        ))}
      </div>

      {/* 7. 每日复盘报告 */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">复盘报告</h3>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={reviewReportDate}
            onChange={onReviewDateChange}
            className="rounded-lg border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
          />
          <button
            onClick={() => reviewQ.refetch()}
            className="text-muted-foreground hover:text-primary"
            title="刷新"
          >
            {reviewReportLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
      <GlassCard className="mb-6">
        {reviewReportLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            <span className="ml-2 text-sm text-muted-foreground">加载复盘报告…</span>
          </div>
        ) : reviewReportError ? (
          <div className="flex items-center justify-center py-8 text-sm text-destructive">
            <AlertCircle className="mr-1.5 h-4 w-4" /> {reviewReportError}
          </div>
        ) : !reviewReport ? (
          <p className="py-6 text-center text-sm text-muted-foreground/60">暂无复盘数据（可能是非交易时段或数据源暂不可用）</p>
        ) : (
          <>
            {/* 摘要栏 */}
            <div className="mb-3 grid grid-cols-2 gap-2 rounded-lg bg-muted/20 p-2.5 sm:grid-cols-4 md:grid-cols-7">
              <div>
                <p className="text-[11px] text-muted-foreground">STI 得分</p>
                <p className="font-mono text-lg font-bold text-primary">
                  {reviewReport.sti_score ?? "—"}
                </p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">STI 阶段</p>
                <p className={cn("font-mono text-lg font-bold",
                  reviewReport.sti_phase === "高潮" || reviewReport.sti_phase === "启动" ? "text-danger"
                  : reviewReport.sti_phase === "冰点" || reviewReport.sti_phase === "退潮" ? "text-success"
                  : "text-muted-foreground"
                )}>
                  {reviewReport.sti_phase ?? "—"}
                </p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">涨停</p>
                <p className="font-mono text-lg font-bold text-danger">{reviewReport.zt_total}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">跌停</p>
                <p className="font-mono text-lg font-bold text-success">{reviewReport.dt_total}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">炸板</p>
                <p className="font-mono text-lg font-bold text-warning">{reviewReport.zb_total}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">上涨</p>
                <p className="font-mono text-lg font-bold text-danger">{reviewReport.advance_count}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">下跌</p>
                <p className="font-mono text-lg font-bold text-success">{reviewReport.decline_count}</p>
              </div>
            </div>

            {/* 标签页 */}
            <div className="mb-3 flex gap-1 rounded-lg bg-muted/15 p-1">
              {([
                { key: "sector" as const, label: "板块热度" },
                { key: "zt" as const, label: "涨停明细" },
                { key: "auction" as const, label: "竞价回顾" },
              ]).map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setReviewTab(tab.key)}
                  className={cn(
                    "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    reviewTab === tab.key ? "bg-muted/30 text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* 板块热度 */}
            {reviewTab === "sector" && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                      {["#", "板块", "涨停数", "总家数", "涨停率", "均价变动"].map((h) => (
                        <th key={h} className="whitespace-nowrap px-3 py-2.5 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20">
                    {reviewReport.sector_heat?.length === 0 ? (
                      <tr><td colSpan={6} className="py-6 text-center text-sm text-muted-foreground/60">暂无板块数据</td></tr>
                    ) : (
                      reviewReport.sector_heat?.slice(0, 10).map((s, i) => (
                        <tr key={s.sector} className="transition-colors hover:bg-muted/20">
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                          <td className="px-3 py-2.5 font-medium">{s.sector}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-danger">{s.zt_count}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.total_count}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.zt_rate != null ? `${(s.zt_rate * 100).toFixed(1)}%` : "—"}</td>
                          <td className={cn("whitespace-nowrap px-3 py-2.5 font-mono text-xs", pctColor(s.avg_change))}>
                            {s.avg_change != null ? `${s.avg_change > 0 ? "+" : ""}${s.avg_change.toFixed(2)}%` : "—"}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* 涨停明细 */}
            {reviewTab === "zt" && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                      {["#", "代码", "名称", "连板数", "封板率", "换手率", "成交额(亿)"].map((h) => (
                        <th key={h} className="whitespace-nowrap px-3 py-2.5 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20">
                    {reviewReport.zt_stocks?.length === 0 ? (
                      <tr><td colSpan={7} className="py-6 text-center text-sm text-muted-foreground/60">暂无涨停数据</td></tr>
                    ) : (
                      reviewReport.zt_stocks?.slice(0, 20).map((s, i) => (
                        <tr key={s.code} className="transition-colors hover:bg-muted/20">
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">{s.code}</td>
                          <td className="px-3 py-2.5 font-medium">{s.name}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono font-bold text-primary">{s.lbc}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.seal_rate != null ? `${(s.seal_rate * 100).toFixed(1)}%` : "—"}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.fbt != null ? `${s.fbt}%` : "—"}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.zbc != null ? `${(s.zbc / 1e8).toFixed(1)} 亿` : "—"}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* 竞价回顾 */}
            {reviewTab === "auction" && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                      {["#", "代码", "名称", "评分", "信号"].map((h) => (
                        <th key={h} className="whitespace-nowrap px-3 py-2.5 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20">
                    {reviewReport.auction_top?.length === 0 ? (
                      <tr><td colSpan={5} className="py-6 text-center text-sm text-muted-foreground/60">暂无竞价数据</td></tr>
                    ) : (
                      reviewReport.auction_top?.slice(0, 10).map((a, i) => (
                        <tr key={JSON.stringify(a)} className="transition-colors hover:bg-muted/20">
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">{(a as any).code ?? "—"}</td>
                          <td className="px-3 py-2.5 font-medium">{(a as any).name ?? "—"}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-primary">{(a as any).score ?? (a as any).rating ?? "—"}</td>
                          <td className="px-3 py-2.5 text-xs text-muted-foreground">{(a as any).signal ?? (a as any).note ?? "—"}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* 前一日涨停统计 */}
            {Object.keys(reviewReport.prev_zt_stats).length > 0 && (
              <div className="mt-3 rounded-lg bg-muted/20 p-2.5">
                <p className="mb-1.5 text-[11px] text-muted-foreground">前一日涨停次日表现</p>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {Object.entries(reviewReport.prev_zt_stats).map(([k, v]) => (
                    <div key={k} className="text-center">
                      <p className="text-[11px] text-muted-foreground/60">{k}</p>
                      <p className="font-mono text-sm font-bold text-foreground">{typeof v === "number" ? `${v.toFixed(2)}%` : v}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {reviewReport.updated && (
              <p className="mt-2 text-[11px] text-muted-foreground/50">更新时间: {reviewReport.updated}</p>
            )}
          </>
        )}
      </GlassCard>

      <Disclaimer />

      {/* STI 详情 Modal */}
      {showStiDetail && (
        <STIDetailView data={sti} onClose={() => setShowStiDetail(false)} />
      )}
    </div>
  );
}
