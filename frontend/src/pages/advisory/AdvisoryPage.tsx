// S179 Phase 2 R2.5: /advisory AI 顾问 cockpit。
// 替代 S042 Advisory.tsx（三场景建议中心 195 行）→ 重构为三区 cockpit：
//   1. 今日推荐（推荐/自选/持仓三场景建议，复用 S042 advisorySummary API）
//   2. 顾问团（grill-me 6-lens 对抗审查，接入待落地 → honest placeholder）
//   3. 多空辩论（/debate 独立全页 + 此处摘要入口链接，不内嵌完整流式组件）
//
// grill #4 决策：大辩论不内嵌完整 Debate 组件（一轮 100s / 3 次模型调用太重），
// 改为摘要描述 + 链接 /debate 全页；顾问团 grill-me 后端接入 deferred。
//
// 旧 Advisory.tsx 保留（Phase 3 删），本页为 /advisory 新路由目标（named export）。
// AdvisoryCard/Section 从旧文件复制而非导入——旧文件 default export 无具名导出，
// 且 Phase 3 会删旧文件，复制保持新文件自包含。
import { useState, useEffect, useCallback, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Loader2,
  RefreshCw,
  Info,
  Sparkles,
  Users,
  Swords,
  ArrowRight,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { api, type AdvisoryItem, type AdvisorySummary, type GrillResult } from "@/lib/api";

// ── 今日推荐：action/source 元数据 + AdvisoryCard（复用 S042 逻辑）──

const ACTION_META: Record<
  AdvisoryItem["action"],
  { color: string; bg: string; label: string }
> = {
  enter: { color: "text-emerald-600", bg: "bg-emerald-50", label: "入场" },
  add: { color: "text-emerald-600", bg: "bg-emerald-50", label: "加仓" },
  hold: { color: "text-gray-600", bg: "bg-muted/30", label: "持有" },
  reduce: { color: "text-amber-600", bg: "bg-amber-50", label: "减仓" },
  close: { color: "text-red-600", bg: "bg-red-50", label: "清仓" },
  no_signal: { color: "text-muted-foreground", bg: "bg-muted/30", label: "无信号" },
};

const SOURCE_LABEL: Record<AdvisoryItem["win_rate_source"], string> = {
  backtest_90d: "90天回测",
  synthetic: "合成估算",
  none: "无数据",
};

function winRateText(item: AdvisoryItem): string {
  if (item.win_rate === null) return "—";
  return `${(item.win_rate * 100).toFixed(0)}%`;
}

function AdvisoryCard({ item }: { item: AdvisoryItem }) {
  const meta = ACTION_META[item.action] ?? ACTION_META.hold;
  return (
    <GlassCard className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-base font-semibold">{item.name}</div>
          <div className="text-xs text-muted-foreground">{item.code}</div>
        </div>
        <span
          className={`rounded-full px-2 py-1 text-xs font-medium ${meta.color} ${meta.bg}`}
        >
          {meta.label}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          回测胜率：
          <span className="font-medium text-foreground">{winRateText(item)}</span>
          <span className="ml-1 text-xs">
            ({SOURCE_LABEL[item.win_rate_source]})
          </span>
        </span>
        {item.matched_strategy && (
          <span>
            战法：
            <span className="font-medium text-foreground">
              {item.matched_strategy}
            </span>
          </span>
        )}
        {item.scene === "recommendation" && item.suggested_pct !== undefined && (
          <span>
            研究仓位：
            <span className="font-medium text-foreground">
              {(item.suggested_pct * 100).toFixed(0)}%
            </span>
          </span>
        )}
        {item.scene === "holding" && item.pnl_pct != null && (
          <span>
            浮动盈亏：
            <span className="font-medium text-foreground">
              {item.pnl_pct >= 0 ? "+" : ""}
              {item.pnl_pct.toFixed(2)}%
            </span>
          </span>
        )}
        {item.scene === "holding" && item.pnl_pct == null && (
          <span>
            浮动盈亏：
            <span className="font-medium text-muted-foreground">数据缺失</span>
          </span>
        )}
        {item.scene === "recommendation" && item.gene_score !== undefined && (
          <span>
            基因：
            <span className="font-medium text-foreground">
              {item.gene_score.toFixed(0)}
            </span>
          </span>
        )}
      </div>

      <div className="space-y-1">
        {item.reasons.slice(0, 3).map((r, i) => (
          <div key={i} className="text-xs text-muted-foreground">
            • {r}
          </div>
        ))}
      </div>

      {item.risk_notes.length > 0 && (
        <div className="flex items-start gap-1 rounded-lg bg-amber-50 p-2 text-xs text-amber-700">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{item.risk_notes[0]}</span>
        </div>
      )}
    </GlassCard>
  );
}

interface SectionProps {
  title: string;
  items: AdvisoryItem[];
  loading: boolean;
}

function Section({ title, items, loading }: SectionProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-muted-foreground">
        {title}（{items.length}）
      </h3>
      {items.length > 0 ? (
        <div className="grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <AdvisoryCard key={`${item.scene}-${item.code}`} item={item} />
          ))}
        </div>
      ) : (
        !loading && (
          <GlassCard>
            <div className="p-4 text-sm text-muted-foreground">暂无数据</div>
          </GlassCard>
        )
      )}
    </div>
  );
}

// ── 三区 cockpit 通用 Zone 壳 ──

interface ZoneProps {
  title: string;
  icon: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
}

function Zone({ title, icon, badge, children }: ZoneProps) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-primary">{icon}</span>
        <h2 className="text-base font-semibold">{title}</h2>
        {badge}
      </div>
      {children}
    </section>
  );
}

// ── 主页 ──

export function AdvisoryPage() {
  const [summary, setSummary] = useState<AdvisorySummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [grillTopic, setGrillTopic] = useState("");
  const [grillContext, setGrillContext] = useState("");
  const [grillResult, setGrillResult] = useState<GrillResult | null>(null);
  const [grillLoading, setGrillLoading] = useState(false);
  const [grillError, setGrillError] = useState<string | null>(null);

  const runGrill = useCallback(async () => {
    if (!grillTopic.trim()) return;
    setGrillLoading(true);
    setGrillError(null);
    try {
      const data = await api.advisoryGrill(grillTopic, grillContext);
      setGrillResult(data);
    } catch (e: unknown) {
      setGrillError(e instanceof Error ? e.message : "grill 失败");
    } finally {
      setGrillLoading(false);
    }
  }, [grillTopic, grillContext]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.advisorySummary(20);
      setSummary(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const askAiContext = [
    `当前页面：AI 顾问 cockpit（今日推荐 + 顾问团 + 多空辩论）`,
    summary
      ? `推荐${summary.recommendations.length}只/自选${summary.watchlist.length}只/持仓${summary.holdings.length}只`
      : `今日推荐：未取得`,
    summary && summary.recommendations.length > 0
      ? `推荐入场：${summary.recommendations
          .slice(0, 8)
          .map(
            (r) =>
              `${r.code}(${r.name})${r.action}[胜率${r.win_rate != null ? (r.win_rate * 100).toFixed(0) + "%" : "无"}/${r.matched_strategy ?? "未匹配"}]`,
          )
          .join("，")}`
      : ``,
    summary && summary.holdings.length > 0
      ? `持仓建议：${summary.holdings
          .slice(0, 5)
          .map(
            (h) =>
              `${h.code}(${h.name})${h.action}盈${h.pnl_pct?.toFixed(1) ?? "?"}%`,
          )
          .join("，")}`
      : ``,
    `顾问团：grill-me 6-lens 对抗审查（接入待落地）`,
    `多空辩论：/debate 独立全页（此处摘要入口）`,
    summary?.partial
      ? `⚠ 端点超时降级（partial=true），部分场景未返回`
      : ``,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI 顾问"
        subtitle="今日推荐 · 顾问团 · 多空辩论 三区 cockpit"
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton context={askAiContext} />
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg bg-primary/90 px-3 py-2 text-sm text-primary-foreground hover:bg-primary disabled:opacity-60"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              刷新
            </button>
          </div>
        }
      />

      <Disclaimer compact />

      {/* Zone 1: 今日推荐（推荐/自选/持仓三场景，复用 S042 advisorySummary） */}
      <Zone title="今日推荐" icon={<Sparkles className="h-4 w-4" />}>
        {error && (
          <GlassCard>
            <div className="p-4 text-sm text-red-600">加载失败：{error}</div>
          </GlassCard>
        )}
        {summary ? (
          <>
            <Section
              title="推荐标的入场建议"
              items={summary.recommendations}
              loading={loading}
            />
            <Section
              title="自选股建议"
              items={summary.watchlist}
              loading={loading}
            />
            <Section
              title="持仓建议"
              items={summary.holdings}
              loading={loading}
            />
          </>
        ) : (
          !loading &&
          !error && (
            <EmptyState
              icon={<Info className="h-8 w-8 text-muted-foreground" />}
              title="暂无建议数据"
              description="未取得建议，稍后再试。"
            />
          )
        )}
      </Zone>

      {/* Zone 2: 顾问团（grill-me 6-lens 对抗审查，S216 后端集成 /api/advisory/grill） */}
      <Zone
        title="顾问团"
        icon={<Users className="h-4 w-4" />}
        badge={
          <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
            6-lens
          </span>
        }
      >
        <GlassCard className="p-4 space-y-3">
          <p className="text-xs text-muted-foreground">
            6-lens 对抗审查——方法论/数据/过拟合/执行/风险/一致性 6 视角反驳，逼出隐藏假设与盲点。
          </p>
          <div className="space-y-2">
            <input
              type="text"
              value={grillTopic}
              onChange={(e) => setGrillTopic(e.target.value)}
              placeholder="标的或论点（如：价值溢价在 A 股成不成立）"
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
            <textarea
              value={grillContext}
              onChange={(e) => setGrillContext(e.target.value)}
              placeholder="背景/数据（可选）"
              rows={2}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
            <button
              onClick={runGrill}
              disabled={grillLoading || !grillTopic.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-primary/90 px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary disabled:opacity-60"
            >
              {grillLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Users className="h-4 w-4" />}
              启动 6-lens 审查
            </button>
          </div>
          {grillError && (
            <p className="text-xs text-red-500">审查失败：{grillError}</p>
          )}
          {grillResult?.data_status === "missing" && (
            <p className="text-xs text-amber-600">{grillResult.note}</p>
          )}
          {grillResult?.data_status === "ok" && grillResult.lenses.length > 0 && (
            <div className="space-y-2">
              {grillResult.lenses.map((lens, i) => (
                <div key={i} className="border border-border rounded-lg p-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      lens.verdict === "pass" ? "bg-emerald-500/10 text-emerald-600" :
                      lens.verdict === "warn" ? "bg-amber-500/10 text-amber-600" :
                      "bg-red-500/10 text-red-600"
                    }`}>{lens.verdict}</span>
                    <span className="text-sm font-medium">{lens.name}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{lens.evidence}</p>
                </div>
              ))}
              {grillResult.synthesis && (
                <p className="text-xs text-foreground bg-muted/30 rounded p-2">
                  综合：{grillResult.synthesis}
                </p>
              )}
            </div>
          )}
          {grillResult?.data_status === "ok" && grillResult.lenses.length === 0 && grillResult.raw_content && (
            <div className="text-xs text-muted-foreground bg-muted/30 rounded p-2">
              <p className="font-medium mb-1">LLM 未返合法 JSON（raw 供人工核）：</p>
              <pre className="whitespace-pre-wrap">{grillResult.raw_content}</pre>
            </div>
          )}
        </GlassCard>
      </Zone>

      {/* Zone 3: 多空辩论（/debate 独立全页，此处摘要入口 + 链接） */}
      <Zone
        title="多空辩论"
        icon={<Swords className="h-4 w-4" />}
        badge={
          <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
            完整页
          </span>
        }
      >
        <GlassCard className="p-4">
          <p className="text-sm text-muted-foreground">
            同一份客观数据底稿，多方与空方各自立论、互相质疑，最后由中立主持归纳分歧点与验证清单——不给买卖结论，判断留给你自己。
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            一轮约 100 秒 · 3 次模型调用 · 约 3.5 万字进上下文（拉底稿约 35 秒走公开数据接口，不耗 token）。
          </p>
          <Link
            to="/debate"
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-primary/90 px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary"
          >
            进入多空辩论
            <ArrowRight className="h-4 w-4" />
          </Link>
        </GlassCard>
      </Zone>
    </div>
  );
}
