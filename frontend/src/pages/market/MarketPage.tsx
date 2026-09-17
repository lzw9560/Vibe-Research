// S179 Phase 1: /market 市场全景 cockpit。
// 替代 daily-review + intel + sectors + sector-divergence + prediction 5 页散布
// （旧路由 Phase 3 才删，此处只加 /market + 改 root redirect）。
// 六区块：指数卡片 + ECharts treemap + 涨停/炸板/连板摘要 + 情绪天气 + 全球情报折叠 + 涨跌预测。
import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  Globe,
  Gauge,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Sparkles,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { cn, pctColor } from "@/lib/utils";
import {
  useIndices,
  useGlobalIndices,
  useMarketOverview,
  useEmotion,
  useSentimentWeatherLatest,
  useRadar,
} from "@/lib/query";
import {
  fetchPrediction,
  isDisclaimerAccepted,
  type PredictionEnvelope,
} from "@/lib/prediction";
import type { IndexQuote, GlobalIndex, SectorFlow } from "@/lib/api";
import { MarketTreemap } from "./MarketTreemap";
import { LimitupSummary } from "./LimitupSummary";

export function MarketPage() {
  const indicesQ = useIndices();
  const globalQ = useGlobalIndices();
  const overviewQ = useMarketOverview();
  const emotionQ = useEmotion();
  const weatherQ = useSentimentWeatherLatest();
  const radarQ = useRadar();

  const indices: IndexQuote[] = indicesQ.data ?? [];
  const globalIdx: GlobalIndex[] = globalQ.data ?? [];
  const sectors: SectorFlow[] = overviewQ.data?.sectors ?? [];
  const emotion = emotionQ.data ?? null;
  const weather = weatherQ.data ?? null;
  const radar = radarQ.data ?? null;

  // 涨跌预测紧凑卡：仅当用户已在 /prediction 过免责墙时加载（isDisclaimerAccepted）
  const [prediction, setPrediction] = useState<PredictionEnvelope | null>(null);
  const [showIntel, setShowIntel] = useState(false);

  const loadPrediction = useCallback(async () => {
    if (!isDisclaimerAccepted()) return;
    try {
      setPrediction(await fetchPrediction("short_sector", "s1"));
    } catch {
      /* silent: prediction 是可选区块，失败不阻塞 cockpit */
    }
  }, []);

  useEffect(() => {
    void loadPrediction();
  }, [loadPrediction]);

  const refreshAll = () => {
    void indicesQ.refetch();
    void globalQ.refetch();
    void overviewQ.refetch();
    void emotionQ.refetch();
    void weatherQ.refetch();
    void radarQ.refetch();
    void loadPrediction();
  };

  const dataSummary = indices.length
    ? indices
        .map(
          (i) =>
            `${i.name} ${i.price}（${i.change_pct > 0 ? "+" : ""}${i.change_pct}%）`,
        )
        .join("；")
    : "（指数数据未取到）";

  const askAiContext = [
    `当前页面：市场全景 cockpit`,
    `大盘：${dataSummary}`,
    `涨停${emotion?.emotion?.limit_up_count ?? "?"}家 / 跌停${emotion?.emotion?.limit_down_count ?? "?"}家 / 最高连板${emotion?.emotion?.max_boards ?? "?"}板`,
    `情绪天气：${weather?.weather_state ?? "未取得"}`,
  ].join("\n");

  return (
    <div>
      <PageHeader
        title="市场全景"
        subtitle="大盘 / 板块热力 / 涨停情绪 / 天气 / 情报 / 预测一屏看全"
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton context={askAiContext} label="问 AI" />
            <button
              onClick={refreshAll}
              className="text-muted-foreground hover:text-primary"
              title="刷新全部"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        }
      />

      {/* 1. 大盘指数（上证/深证/创业板/科创） */}
      <div className="mb-6">
        <h3 className="mb-2 text-sm font-semibold text-muted-foreground">
          大盘指数
        </h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {indices.length === 0
            ? [1, 2, 3, 4].map((i) => (
                <GlassCard key={i} className="p-3">
                  <p className="text-xs text-muted-foreground">
                    {indicesQ.error ? "行情未接通" : "加载中…"}
                  </p>
                  <p className="mt-1 font-mono text-lg font-bold text-muted-foreground">
                    —
                  </p>
                </GlassCard>
              ))
            : indices.map((i) => (
                <GlassCard key={i.name} className="p-3">
                  <p className="truncate text-xs text-muted-foreground">
                    {i.name}
                  </p>
                  <p
                    className={cn(
                      "mt-1 font-mono text-lg font-bold",
                      pctColor(i.change_pct),
                    )}
                  >
                    {i.price}
                  </p>
                  <p className={cn("text-xs", pctColor(i.change_pct))}>
                    {i.change_pct > 0 ? "+" : ""}
                    {i.change_pct}%
                  </p>
                </GlassCard>
              ))}
        </div>
      </div>

      {/* 1b. 全球市场（隔夜外围：美股/港股指数，沿用红涨绿跌） */}
      {globalIdx.length > 0 && (
        <div className="mb-6">
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
            <Globe className="h-4 w-4" /> 全球市场
          </h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {globalIdx.map((g) => (
              <GlassCard key={g.key} className="p-3">
                <p className="truncate text-xs text-muted-foreground">
                  {g.name}{" "}
                  <span className="text-muted-foreground">{g.region}</span>
                </p>
                <p
                  className={cn(
                    "mt-1 font-mono text-base font-bold",
                    g.change_pct == null
                      ? "text-foreground"
                      : pctColor(g.change_pct),
                  )}
                >
                  {g.price ?? "—"}
                </p>
                <p
                  className={cn(
                    "text-xs",
                    g.change_pct == null
                      ? "text-muted-foreground"
                      : pctColor(g.change_pct),
                  )}
                >
                  {g.change_pct == null
                    ? "—"
                    : `${g.change_pct > 0 ? "+" : ""}${g.change_pct}%`}
                </p>
              </GlassCard>
            ))}
          </div>
        </div>
      )}

      {/* 2. 申万板块热力图（ECharts treemap，聚合一级 30 板块） */}
      <div className="mb-6">
        <MarketTreemap
          sectors={sectors}
          loading={overviewQ.isLoading}
          error={overviewQ.error ? "板块数据未取得" : null}
          onRefresh={() => void overviewQ.refetch()}
        />
        {/* 热门板块详情入口（/sectors/:key 不再孤儿） */}
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">热门板块详情：</span>
          {[
            { to: "/sectors/humanoid", label: "人形机器人" },
            { to: "/sectors/ai-computing", label: "AI 算力" },
            { to: "/sectors/hbm", label: "HBM" },
            { to: "/sectors/cpo", label: "光互联" },
            { to: "/sectors/business-space", label: "商业航天" },
            { to: "/sectors/ai-pharma", label: "生物医药" },
          ].map((s) => (
            <Link
              key={s.to}
              to={s.to}
              className="rounded bg-muted/40 px-1.5 py-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {s.label}
            </Link>
          ))}
        </div>
      </div>

      {/* 3. 涨停 / 炸板 / 连板摘要 */}
      <div className="mb-6">
        <LimitupSummary emotion={emotion} loading={emotionQ.isLoading} />
      </div>

      {/* 4. 情绪天气（WeatherState：综合得分 + STI + 置信度） */}
      <div className="mb-6">
        <GlassCard className="p-4">
          <div className="mb-3 flex items-center gap-1.5">
            <Gauge className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">情绪天气</h3>
            {weather?.data_updated && (
              <span className="ml-auto text-[11px] text-muted-foreground">
                {weather.data_updated}
              </span>
            )}
          </div>
          {!weather ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {weatherQ.isLoading ? "加载中…" : "暂无天气数据"}
            </p>
          ) : (
            <div className="flex items-center gap-4">
              <div className="text-center">
                <p className="text-3xl">{weather.weather_icon}</p>
                <p className="mt-1 text-sm font-bold">{weather.weather_state}</p>
              </div>
              <div className="flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-2xl font-bold text-primary">
                    {weather.composite_score.toFixed(0)}
                  </span>
                  <span className="text-xs text-muted-foreground">综合得分</span>
                </div>
                {weather.sti_score != null && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    STI {weather.sti_score.toFixed(0)} ·{" "}
                    {weather.sti_phase ?? "—"}
                  </p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  置信度：{weather.confidence}
                </p>
              </div>
              <Link
                to="/sentiment/weather"
                className="shrink-0 text-xs text-primary hover:underline"
              >
                详情 →
              </Link>
            </div>
          )}
        </GlassCard>
      </div>

      {/* 5. 全球情报折叠（radar 12 赛道公开 RSS，默认折叠） */}
      <div className="mb-6">
        <button
          onClick={() => setShowIntel((v) => !v)}
          className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-foreground"
        >
          {showIntel ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronUp className="h-4 w-4" />
          )}
          全球情报
          {radar && (
            <span className="text-[11px] text-muted-foreground">
              {radar.stats.total_sources} 源 · {radar.industries.length} 赛道
            </span>
          )}
        </button>
        {showIntel && (
          <GlassCard className="p-4">
            {radarQ.isLoading ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                加载中…
              </p>
            ) : !radar || radar.industries.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                暂无情报。
                <Link to="/intel" className="text-primary">
                  去资讯雷达页刷新抓取 →
                </Link>
              </p>
            ) : (
              <div className="space-y-1.5">
                {radar.industries.slice(0, 6).map((ind) => (
                  <div
                    key={ind.key}
                    className="flex items-center gap-2 text-sm"
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: ind.accent }}
                    />
                    <span className="flex-1 truncate">{ind.name}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {ind.items.length} 条
                    </span>
                    {ind.items[0] && (
                      <span className="truncate text-xs text-muted-foreground/70">
                        {ind.items[0].zh || ind.items[0].title}
                      </span>
                    )}
                  </div>
                ))}
                <Link
                  to="/intel"
                  className="mt-2 block text-xs text-primary hover:underline"
                >
                  查看全部 →
                </Link>
              </div>
            )}
          </GlassCard>
        )}
      </div>

      {/* 6. 涨跌预测（紧凑卡，仅当已过免责墙时加载；否则链到 /prediction） */}
      <div className="mb-6">
        <GlassCard className="p-4">
          <div className="mb-3 flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">涨跌预测</h3>
            <span className="ml-auto rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
              研究参考
            </span>
          </div>
          {!isDisclaimerAccepted() ? (
            <p className="text-sm text-muted-foreground">
              预测需先知悉免责声明。
              <Link
                to="/prediction"
                className="text-primary hover:underline"
              >
                进入预测工作台确认 →
              </Link>
            </p>
          ) : !prediction || prediction.status === "no_snapshot" || !prediction.data ? (
            <p className="text-sm text-muted-foreground">
              {prediction ? "快照待生成" : "加载中…"}
            </p>
          ) : (
            <div className="flex items-end gap-3">
              <div>
                <p className="text-xs text-muted-foreground">S1 收盘后上涨概率</p>
                <p className="font-mono text-2xl font-bold text-primary">
                  {(prediction.data.prob * 100).toFixed(1)}%
                </p>
              </div>
              {prediction.data.shap_topk.length > 0 && (
                <div className="flex-1 text-xs text-muted-foreground">
                  <p>主要驱动因子：</p>
                  <p>
                    {prediction.data.shap_topk
                      .slice(0, 3)
                      .map(([f, v]) => `${f}(${v.toFixed(2)})`)
                      .join(" · ")}
                  </p>
                </div>
              )}
              <Link
                to="/prediction"
                className="shrink-0 text-xs text-primary hover:underline"
              >
                详情 →
              </Link>
            </div>
          )}
        </GlassCard>
      </div>

      <Disclaimer />
    </div>
  );
}
