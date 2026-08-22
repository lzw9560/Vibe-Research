import { useState, useEffect } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { STICard } from "@/components/sti/StiCard";
import { STIDetailView } from "@/components/sti/StiDetailView";
import {
  useIndices, useGlobalIndices, useMarketOverview,
  useEmotion, useTurnoverTop, useStiLatest, useQuote, useDailyReview, useDateTriplet,
} from "@/lib/query";
import { ApiError } from "@/lib/api";
import { IndexCards } from "./components/IndexCards";
import { GlobalMarket } from "./components/GlobalMarket";
import { WatchlistGrid } from "./components/WatchlistGrid";
import { AiReviewPanel } from "./components/AiReviewPanel";
import { EmotionSummary } from "./components/EmotionSummary";
import { SectorFundFlow } from "./components/SectorFundFlow";
import { ReviewReport } from "./components/ReviewReport";

const errMsg = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

export function DailyReview() {
  const indicesQ = useIndices();
  const globalQ = useGlobalIndices();
  const overviewQ = useMarketOverview();
  const emotionQ = useEmotion();
  const turnoverQ = useTurnoverTop();
  const stiQ = useStiLatest();
  const [watchCodes, setWatchCodes] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("watchCodes") || "[]"); } catch { return []; }
  });
  const quoteQ = useQuote(watchCodes.join(","));
  // 初始空串，等 dateTriplet（最近交易日锚）加载后再填——非交易日不再误用日历今日。
  // 仅在 reviewDate 仍为空时填充，用户手动选日后不覆盖。对齐 DailyReview.tsx 的修复模式。
  const [reviewDate, setReviewDate] = useState("");
  const { data: triplet } = useDateTriplet();
  useEffect(() => {
    if (triplet?.review && !reviewDate) {
      setReviewDate(triplet.review);
    }
  }, [triplet?.review, reviewDate]);
  const reviewQ = useDailyReview(reviewDate, { enabled: !!reviewDate });
  const [showStiDetail, setShowStiDetail] = useState(false);

  const indices = indicesQ.data ?? [];
  const idxErr = !!indicesQ.error;
  const globalIdx = globalQ.data ?? [];
  const overview = overviewQ.data ?? null;
  const emotion = emotionQ.data ?? null;
  const turnover = turnoverQ.data ?? null;
  const sectors = overview?.sectors || [];
  const sti = stiQ.data ?? null;
  const watchQuotes = quoteQ.data ?? {};

  const dataSummary = indices.length
    ? indices.map((i) => `${i.name} ${i.price}（${i.change_pct > 0 ? "+" : ""}${i.change_pct}%）`).join("；")
    : "（指数数据未取到）";
  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });

  const refreshAll = () => {
    void indicesQ.refetch(); void globalQ.refetch(); void overviewQ.refetch();
    void emotionQ.refetch(); void turnoverQ.refetch(); void stiQ.refetch(); void reviewQ.refetch();
  };

  const handleWatchCodesChange = (codes: string[]) => {
    setWatchCodes(codes);
    try { localStorage.setItem("watchCodes", JSON.stringify(codes)); } catch {}
  };

  return (
    <div>
      <PageHeader
        title="每日复盘"
        subtitle={`${today} · 大盘 / 情绪 / 板块资金一屏看全，交给你的 AI 做复盘`}
        actions={
          <AskAiButton context={dataSummary} label="问 AI"
            suggestions={["今天大盘怎么走", "哪些指数领涨领跌", "盘面有什么值得注意"]} />
        }
      />

      {/* 概览层 */}
      <IndexCards indices={indices} idxErr={idxErr} onRefresh={refreshAll} />
      <GlobalMarket globalIdx={globalIdx} />
      <STICard data={sti} loading={stiQ.isFetching}
        error={stiQ.error ? errMsg(stiQ.error, "STI 加载失败") : null}
        onClick={() => setShowStiDetail(true)} />
      <WatchlistGrid watchCodes={watchCodes} watchQuotes={watchQuotes}
        watchLoading={quoteQ.isFetching} onCodesChange={handleWatchCodesChange} onRefresh={() => quoteQ.refetch()} />

      {/* AI 复盘 */}
      <AiReviewPanel dataSummary={dataSummary} today={today} />

      {/* 下沉区 */}
      <EmotionSummary sentiment={emotion} emoDone={!emotionQ.isLoading}
        turnover={turnover} toDone={!turnoverQ.isLoading} />
      <SectorFundFlow sectors={sectors} done={!overviewQ.isLoading} />
      <ReviewReport date={reviewDate} report={reviewQ.data ?? null}
        loading={reviewQ.isFetching} error={reviewQ.error ? errMsg(reviewQ.error, "复盘报告加载失败") : null}
        onDateChange={setReviewDate} onRefresh={() => reviewQ.refetch()} />

      {showStiDetail && <STIDetailView data={sti} onClose={() => setShowStiDetail(false)} />}
    </div>
  );
}
