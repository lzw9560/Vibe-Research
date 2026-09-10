// S179 Phase 2 R2.4: /portfolio 投资管理加维度。
// 替代 Portfolio.tsx（295 行持仓管理）→ 重构为四维 cockpit：
//   1. 持仓管理（复用原 Portfolio 逻辑：holdings + add/remove + 清仓记录）
//   2. 风险仪表盘（接 risk-dashboard API：风险分布 + 风险因素 + 高风险股 + 席位）
//   3. 健康分（数据源待接入 → honest placeholder）
//   4. PB-ROE 散点图（数据源待接入 → honest placeholder）
//
// grill 决策：四维用页内 TabBar（L2 tab），不垂直堆叠——持仓表 + 风险分布
// 各自密度高，堆叠会超长滚动；tab 切换各为焦点，符合 StandardLayout 单焦点页。
// 风险仪表盘从 RiskDashboard.tsx 复制精简，聚焦"我的持仓"风险维度而非全市场扫描。
// 健康分 + PB-ROE 散点数据源待接入（后端无聚合端点），标 honest placeholder。
//
// 旧 Portfolio.tsx 保留（Phase 3 删），本页为 /portfolio 新路由目标（named export）。
// 持仓 + 风险逻辑从旧文件复制而非导入——旧文件 Phase 3 会删，复制保持新文件自包含。
import { useState, useEffect, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  ShieldCheck,
  RefreshCw,
  Loader2,
  Trash2,
  AlertCircle,
  Activity,
  HeartPulse,
  ScatterChart,
  Info,
  TrendingDown,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { MetricCard } from "@/components/ui/MetricCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { TabBar } from "@/components/ui/TabBar";
import { EmptyState } from "@/components/ui/EmptyState";
import { api, ApiError } from "@/lib/api";
import { usePortfolio } from "@/lib/query";
import { cn } from "@/lib/utils";

// ── 持仓格式化（从 Portfolio.tsx 复制，保持行为一致）──

const REFRESH_MS = 30 * 60 * 1000; // 每半小时自动刷新
const pnlColor = (v: number | null | undefined) =>
  v == null
    ? "text-muted-foreground"
    : v > 0
      ? "text-danger"
      : v < 0
        ? "text-success"
        : "text-muted-foreground";
const fmt = (v: number | null | undefined) =>
  v == null ? "数据缺失" : v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
// 单价类（现价/成本/清仓价）最多 4 位小数：ETF/基金常见 3-4 位，截断成 2 位会与市值/盈亏对不上账
const fmtPx = (v: number | null | undefined) =>
  v == null ? "数据缺失" : v.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
// pnl_pct 显示——null（行情取数失败 degraded）→"数据缺失"，否则带 +/-
const fmtPnlPct = (v: number | null | undefined) =>
  v == null ? "数据缺失" : (v > 0 ? "+" : "") + v + "%";

// ── 风险仪表盘类型（从 RiskDashboard.tsx 复制）──

interface RiskDashboardData {
  date: string;
  total_stocks: number;
  high_risk_count: number;
  medium_risk_count: number;
  low_risk_count: number;
  risk_distribution: Array<{
    code: string;
    name: string;
    risk_score: number;
    risk_level: string;
    factors: string[];
  }>;
  top_risk_factors: Array<{ factor: string; count: number }>;
  sector_risk: Array<{ sector: string; avg_risk: number; count: number }>;
}

interface HighRiskStock {
  code: string;
  name: string;
  risk_score: number;
  risk_level: string;
  factors: string[];
  last_updated: string;
}

interface RiskSeatsData {
  one_day_seats: Array<{
    seat_name: string;
    one_day_rate: number;
    avg_return: number;
    type: string;
  }>;
  multi_day_seats: Array<{
    seat_name: string;
    one_day_rate: number;
    avg_return: number;
    type: string;
  }>;
  disclaimer: string;
}

const riskLevelColor = (level: string) => {
  switch (level) {
    case "HIGH":
      return "text-red-600 bg-red-50";
    case "MEDIUM":
      return "text-amber-600 bg-amber-50";
    case "LOW":
      return "text-emerald-600 bg-emerald-50";
    default:
      return "text-gray-600 bg-gray-50";
  }
};

const riskLevelLabel = (level: string) => {
  switch (level) {
    case "HIGH":
      return "高风险";
    case "MEDIUM":
      return "中风险";
    case "LOW":
      return "低风险";
    default:
      return level;
  }
};

// ── Tab 定义 ──

const TABS = [
  { key: "holdings", label: "持仓管理", icon: <ShieldCheck className="h-3.5 w-3.5" /> },
  { key: "risk", label: "风险仪表盘", icon: <Activity className="h-3.5 w-3.5" /> },
  { key: "health", label: "健康分", icon: <HeartPulse className="h-3.5 w-3.5" /> },
  { key: "pb-roe", label: "PB-ROE 散点", icon: <ScatterChart className="h-3.5 w-3.5" /> },
];

// ── 风险仪表盘 Tab（自包含：按需加载，独立刷新）──

function RiskDashboardTab() {
  const [data, setData] = useState<RiskDashboardData | null>(null);
  const [highRiskList, setHighRiskList] = useState<HighRiskStock[]>([]);
  const [seats, setSeats] = useState<RiskSeatsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dashboard, highRisk, seatsData] = await Promise.all([
        api.riskDashboard(),
        api.riskOnedayList(undefined, 70).catch(() => []),
        api.riskSeats().catch(() => null),
      ]);
      setData(dashboard as RiskDashboardData);
      setHighRiskList(Array.isArray(highRisk) ? (highRisk as HighRiskStock[]) : []);
      setSeats(seatsData as RiskSeatsData | null);
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
    `当前页面：投资管理 · 风险仪表盘维度`,
    data
      ? `日期${data.date}：扫描${data.total_stocks}只/高${data.high_risk_count}/中${data.medium_risk_count}/低${data.low_risk_count}`
      : `风险分布：未取得`,
    highRiskList.length > 0
      ? `高风险股：${highRiskList
          .slice(0, 8)
          .map((s) => `${s.code}(${s.name})分${s.risk_score}/[${s.factors.slice(0, 2).join("/")}]`)
          .join("，")}`
      : `高风险股：无`,
  ].join("\n");

  if (loading && !data) {
    return (
      <div className="flex h-[40vh] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载风险数据…
      </div>
    );
  }

  if (error && !data) {
    return (
      <EmptyState
        icon={<AlertCircle className="h-8 w-8 text-muted-foreground/40" />}
        title="风险数据加载失败"
        description={error}
        action={
          <Button onClick={load} size="sm">
            <RefreshCw className="h-3.5 w-3.5" /> 重试
          </Button>
        }
      />
    );
  }

  if (!data) {
    return (
      <EmptyState
        icon={<Activity className="h-8 w-8 text-muted-foreground/40" />}
        title="暂无风险数据"
        description="未取得风险分布数据，稍后再试。"
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <AskAiButton context={askAiContext} />
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </button>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <MetricCard label="高风险" value={data.high_risk_count} valueClassName="text-red-600" />
        <MetricCard label="中风险" value={data.medium_risk_count} valueClassName="text-amber-600" />
        <MetricCard label="低风险" value={data.low_risk_count} valueClassName="text-emerald-600" />
      </div>

      {/* 风险分布列表（前 20） */}
      <GlassCard>
        <SectionHeader title="风险分布（前 20 只）" />
        <div className="space-y-2">
          {data.risk_distribution.slice(0, 20).map((item) => (
            <div
              key={item.code}
              className="flex items-center justify-between rounded-lg border border-border/50 p-3"
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm">{item.code}</span>
                  <span className="text-sm font-medium">{item.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${riskLevelColor(item.risk_level)}`}>
                    {riskLevelLabel(item.risk_level)}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {item.factors.slice(0, 3).map((factor, idx) => (
                    <span key={idx} className="text-xs text-muted-foreground">
                      {factor}
                    </span>
                  ))}
                </div>
              </div>
              <div className="ml-4 text-right">
                <div className="text-lg font-bold">{item.risk_score}</div>
                <div className="text-xs text-muted-foreground">风险评分</div>
              </div>
            </div>
          ))}
        </div>
      </GlassCard>

      {/* 风险因素 TOP 10 */}
      <GlassCard>
        <SectionHeader title="风险因素 TOP 10" />
        <div className="space-y-2">
          {data.top_risk_factors.map((item, idx) => (
            <div key={idx} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{item.factor}</span>
              <span className="font-medium">{item.count} 只</span>
            </div>
          ))}
        </div>
      </GlassCard>

      {/* 高风险个股列表 */}
      {highRiskList.length > 0 && (
        <GlassCard>
          <SectionHeader title="高风险个股（实时）" />
          <div className="space-y-2">
            {highRiskList.slice(0, 20).map((item) => (
              <div
                key={item.code}
                className="flex items-center justify-between rounded-lg border border-border/50 p-3"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm">{item.code}</span>
                    <span className="text-sm font-medium">{item.name}</span>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${riskLevelColor(item.risk_level)}`}>
                      {riskLevelLabel(item.risk_level)}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {item.factors.slice(0, 3).map((factor, idx) => (
                      <span key={idx} className="text-xs text-muted-foreground">
                        {factor}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="ml-4 text-right">
                  <div className="text-lg font-bold">{item.risk_score}</div>
                  <div className="text-xs text-muted-foreground">风险评分</div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* 一日游特征席位库 */}
      {seats && (
        <GlassCard>
          <SectionHeader title="一日游特征席位库" />
          <div className="mb-3 text-xs text-muted-foreground">{seats.disclaimer}</div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <h4 className="mb-2 text-xs font-semibold text-red-600">一日游席位（高风险）</h4>
              <div className="space-y-1">
                {seats.one_day_seats.map((seat, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{seat.seat_name}</span>
                    <span className="font-medium">
                      一日游概率 {(seat.one_day_rate * 100).toFixed(0)}% · 平均收益{" "}
                      {(seat.avg_return >= 0 ? "+" : "") + seat.avg_return.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h4 className="mb-2 text-xs font-semibold text-emerald-600">多日持仓席位（低风险）</h4>
              <div className="space-y-1">
                {seats.multi_day_seats.map((seat, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{seat.seat_name}</span>
                    <span className="font-medium">
                      一日游概率 {(seat.one_day_rate * 100).toFixed(0)}% · 平均收益{" "}
                      {(seat.avg_return >= 0 ? "+" : "") + seat.avg_return.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </GlassCard>
      )}
    </div>
  );
}

// ── 健康分 Tab（数据源待接入 → honest placeholder）──

function HealthScoreTab() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
          数据源待接入
        </span>
        <span className="text-xs text-muted-foreground">健康分聚合端点未落地</span>
      </div>
      <GlassCard className="p-6">
        <EmptyState
          icon={<HeartPulse className="h-10 w-10 text-muted-foreground/40" />}
          title="持仓健康分待接入"
          description={
            <span className="space-y-1 text-left">
              <p>健康分计划从持仓维度聚合：集中度（单股权重）、行业暴露、</p>
              <p>估值分位（PE/PB 历史百分位）、波动率、最大回撤。</p>
              <p>后端需新增 /portfolio/health-score 聚合端点，</p>
              <p>读 valuation_percentile + holdings 交叉计算。</p>
            </span>
          }
        />
      </GlassCard>
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <span>
          健康分是主观聚合指标（非客观数据），落地后须标"参考性"而非"确定性"。
          数据源：valuation_percentile（5yr PE/PB 分位）+ holdings 权重 + 行业分类。
        </span>
      </div>
    </div>
  );
}

// ── PB-ROE 散点 Tab（数据源待接入 → honest placeholder）──

function PbRoeScatterTab() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
          数据源待接入
        </span>
        <span className="text-xs text-muted-foreground">PB-ROE 聚合端点未落地</span>
      </div>
      <GlassCard className="p-6">
        <EmptyState
          icon={<ScatterChart className="h-10 w-10 text-muted-foreground/40" />}
          title="PB-ROE 散点图待接入"
          description={
            <span className="space-y-1 text-left">
              <p>散点图计划横轴 PB（市净率）、纵轴 ROE（净资产收益率），</p>
              <p>每个点一只持仓股，颜色/大小区分权重。</p>
              <p>后端需新增 /portfolio/pb-roe 端点，</p>
              <p>读 financials.roe + valuation.pb 交叉拼接持仓列表。</p>
            </span>
          }
        />
      </GlassCard>
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <span>
          PB-ROE 散点用于判断持仓估值 vs 盈利能力的匹配度——低 PB 高 ROE 区间
          （左上）通常是价值机会，高 PB 低 ROE（右下）是泡沫风险区。
          数据源：financials.roe（单股逐个取）+ valuation.pb，当前无聚合端点。
        </span>
      </div>
      <GlassCard className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <TrendingDown className="h-3.5 w-3.5" />
          <span>
            参考雪球个股页 PB-ROE 散点设计。落地后此 tab 展示持仓散点 + 行业基准线 + 合理区间标注。
          </span>
        </div>
      </GlassCard>
    </div>
  );
}

// ── 主页：四维 cockpit ──

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error, refetch } = usePortfolio({ refetchInterval: REFRESH_MS });
  const [activeTab, setActiveTab] = useState("holdings");
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [code, setCode] = useState("");
  const [shares, setShares] = useState("");
  const [cost, setCost] = useState("");
  const [adding, setAdding] = useState(false);
  // 清仓录入
  const [cCode, setCCode] = useState("");
  const [cDate, setCDate] = useState("");
  const [cPrice, setCPrice] = useState("");
  const [cShares, setCShares] = useState("");
  const [cCost, setCCost] = useState("");
  const [closing, setClosing] = useState(false);

  const loadErr = error instanceof Error ? error.message : error ? String(error) : null;
  const errMsg = err ?? loadErr;

  const manualRefresh = async () => {
    setRefreshing(true);
    try {
      const fresh = await api.refreshPortfolio();
      queryClient.setQueryData(["market", "portfolio"], fresh);
      setErr(null);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "刷新失败");
    } finally {
      setRefreshing(false);
    }
  };

  const add = async () => {
    if (!/^\d{6}$/.test(code.trim())) {
      setErr("请输入 6 位股票代码");
      return;
    }
    const s = parseFloat(shares),
      c = parseFloat(cost);
    if (!(s > 0) || !Number.isFinite(c)) {
      setErr("数量须大于 0，成本价请填数字（可为负）");
      return;
    }
    setAdding(true);
    setErr(null);
    try {
      await api.addHolding(code.trim(), s, c);
      await refetch();
      setCode("");
      setShares("");
      setCost("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "添加失败");
    } finally {
      setAdding(false);
    }
  };

  const remove = async (c: string) => {
    try {
      await api.removeHolding(c);
      await refetch();
    } catch {
      /* ignore */
    }
  };

  const addClose = async () => {
    if (!/^\d{6}$/.test(cCode.trim())) {
      setErr("清仓记录：请输入 6 位代码");
      return;
    }
    const p = parseFloat(cPrice),
      s = parseFloat(cShares),
      c = parseFloat(cCost);
    if (!cDate) {
      setErr("请选清仓日期");
      return;
    }
    if (!(p > 0) || !(s > 0) || !Number.isFinite(c)) {
      setErr("清仓价 / 股数须大于 0，成本请填数字（可为负）");
      return;
    }
    setClosing(true);
    setErr(null);
    try {
      await api.closePosition(cCode.trim(), cDate, p, s, c);
      await refetch();
      setCCode("");
      setCDate("");
      setCPrice("");
      setCShares("");
      setCCost("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "添加清仓记录失败");
    } finally {
      setClosing(false);
    }
  };

  const removeClosed = async (i: number) => {
    try {
      await api.removeClosed(i);
      await refetch();
    } catch {
      /* ignore */
    }
  };

  const holdings = data?.holdings || [];
  const totals = data?.totals;
  const closed = data?.closed || [];

  const aiContext = totals
    ? `我的持仓（本地数据）：\n` +
      holdings
        .map(
          (h) =>
            `${h.name}(${h.code}) ${h.shares}股 成本${h.cost} 现价${h.price ?? "数据缺失"} 浮盈${h.pnl ?? "数据缺失"}(${h.pnl_pct ?? "数据缺失"}%)`,
        )
        .join("\n") +
      `\n汇总：市值${totals.market_value} 总浮盈${totals.pnl}(${totals.pnl_pct}%)${totals.data_status === "degraded" ? "（部分行情取数失败，总额仅含可用持仓）" : ""}`
    : "我的持仓：暂无记录。";

  return (
    <div>
      <PageHeader
        title="投资管理"
        subtitle="持仓出场 · 风险 · 健康 · 估值 四维 cockpit"
        actions={
          <div className="flex items-center gap-2">
            {activeTab === "holdings" && holdings.length > 0 && (
              <AskAiButton
                context={aiContext}
                label="让 AI 看我的持仓"
                suggestions={["我的持仓集中在哪些方向", "结构上有什么风险", "帮我梳理一下"]}
              />
            )}
            <button
              onClick={manualRefresh}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新持仓
            </button>
          </div>
        }
      />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-success/25 bg-success/5 p-3 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
        <span>
          持仓<b className="text-foreground">只存在你本地</b>，不上传、不进仓库。行情每半小时自动刷新，也可手动刷新。本产品不提供标的、不给建议，只帮你把自己的账理清楚。
        </span>
      </div>

      {/* L2 页内 Tab */}
      <div className="mb-4">
        <TabBar tabs={TABS} activeKey={activeTab} onChange={setActiveTab} />
      </div>

      {/* Tab 内容 */}
      {activeTab === "holdings" && (
        <div className="space-y-4">
          {/* 汇总 */}
          {totals && holdings.length > 0 && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { k: "总市值", v: fmt(totals.market_value), c: "text-foreground" },
                { k: "总成本", v: fmt(totals.cost), c: "text-foreground" },
                { k: "浮动盈亏", v: (totals.pnl > 0 ? "+" : "") + fmt(totals.pnl), c: pnlColor(totals.pnl) },
                {
                  k: "盈亏比例",
                  v: (totals.pnl_pct > 0 ? "+" : "") + totals.pnl_pct + "%",
                  c: pnlColor(totals.pnl),
                },
              ].map((m) => (
                <MetricCard
                  key={m.k}
                  label={m.k}
                  value={m.v}
                  valueClassName={cn("font-mono text-lg font-bold", m.c)}
                />
              ))}
            </div>
          )}
          {totals?.data_status === "degraded" && holdings.length > 0 && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-muted-foreground">
              <AlertCircle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
              <span>部分持仓行情取数失败，总额仅含可用持仓（degraded 行已标"数据缺失"）。</span>
            </div>
          )}

          {/* 录入 */}
          <GlassCard>
            <SectionHeader title="添加持仓" />
            <div className="flex flex-wrap items-end gap-2">
              <Input
                label="股票代码"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="6 位代码"
                className="w-28"
              />
              <Input
                label="数量（股）"
                value={shares}
                onChange={(e) => setShares(e.target.value.replace(/[^\d.]/g, ""))}
                placeholder="如 100"
                className="w-28"
              />
              <Input
                label="成本价"
                value={cost}
                onChange={(e) => setCost(e.target.value.replace(/[^\d.-]/g, "").replace(/(?!^)-/g, ""))}
                placeholder="如 12.5，可负"
                className="w-28"
              />
              <Button onClick={add} disabled={adding}>
                {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} 添加
              </Button>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground/60">
              同一代码再次添加会按加权平均成本合并（加仓）。
            </p>
          </GlassCard>

          {errMsg && (
            <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" /> {errMsg}
            </div>
          )}

          {/* 持仓表 */}
          <GlassCard glow>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="font-semibold">持仓明细</h3>
              {data?.updated && (
                <span className="text-xs text-muted-foreground/60">更新于 {data.updated}</span>
              )}
            </div>
            {holdings.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground/60">
                {isLoading ? "加载中…" : "还没有持仓记录，用上面的表单添加一笔。"}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["名称", "现价", "数量", "成本", "市值", "浮动盈亏", "盈亏%", ""].map((h) => (
                        <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.map((h) => (
                      <tr key={h.code} className="border-b border-border/30">
                        <td className="px-2 py-2.5">
                          <span className="font-medium">{h.name}</span>
                          <span className="ml-1.5 font-mono text-xs text-muted-foreground/60">{h.code}</span>
                        </td>
                        <td className="px-2 py-2.5 font-mono">{fmtPx(h.price)}</td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{fmt(h.shares)}</td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{fmtPx(h.cost)}</td>
                        <td className="px-2 py-2.5 font-mono">{fmt(h.market_value)}</td>
                        <td className={cn("px-2 py-2.5 font-mono", pnlColor(h.pnl))}>
                          {h.pnl == null ? "数据缺失" : (h.pnl > 0 ? "+" : "") + fmt(h.pnl)}
                        </td>
                        <td className={cn("px-2 py-2.5 font-mono", pnlColor(h.pnl))}>
                          {fmtPnlPct(h.pnl_pct)}
                        </td>
                        <td className="px-2 py-2.5">
                          <button
                            onClick={() => remove(h.code)}
                            className="text-muted-foreground/50 hover:text-destructive"
                            title="删除"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassCard>

          {/* 清仓录入 */}
          <GlassCard>
            <SectionHeader title="添加清仓记录" />
            <div className="flex flex-wrap items-end gap-2">
              <Input
                label="股票代码"
                value={cCode}
                onChange={(e) => setCCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="6 位代码"
                className="w-24"
              />
              <Input
                label="清仓日期"
                type="date"
                value={cDate}
                onChange={(e) => setCDate(e.target.value)}
                className="w-auto"
              />
              <Input
                label="清仓价"
                value={cPrice}
                onChange={(e) => setCPrice(e.target.value.replace(/[^\d.]/g, ""))}
                placeholder="卖出价"
                className="w-24"
              />
              <Input
                label="股数"
                value={cShares}
                onChange={(e) => setCShares(e.target.value.replace(/[^\d.]/g, ""))}
                placeholder="如 100"
                className="w-24"
              />
              <Input
                label="买入成本"
                value={cCost}
                onChange={(e) => setCCost(e.target.value.replace(/[^\d.-]/g, "").replace(/(?!^)-/g, ""))}
                placeholder="成本价，可负"
                className="w-24"
              />
              <Button onClick={addClose} disabled={closing}>
                {closing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} 记录
              </Button>
            </div>
          </GlassCard>

          {/* 已清仓列表 */}
          <div className="flex items-center justify-between">
            <SectionHeader title="已清仓" className="mb-0" />
            {closed.length > 0 && data && (
              <span className="text-sm">
                已实现盈亏合计{" "}
                <b className={cn("font-mono", pnlColor(data.realized_pnl))}>
                  {data.realized_pnl > 0 ? "+" : ""}
                  {fmt(data.realized_pnl)}
                </b>
              </span>
            )}
          </div>
          <GlassCard>
            {closed.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground/60">
                还没有清仓记录。卖出后在上面记一笔，作为已实现盈亏的历史。
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["名称", "清仓日期", "清仓价", "股数", "成本", "已实现盈亏", "盈亏%", ""].map((h) => (
                        <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {closed.map((c, i) => (
                      <tr key={i} className="border-b border-border/30">
                        <td className="px-2 py-2.5">
                          <span className="font-medium">{c.name}</span>
                          <span className="ml-1.5 font-mono text-xs text-muted-foreground/60">{c.code}</span>
                        </td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{c.date}</td>
                        <td className="px-2 py-2.5 font-mono">{fmtPx(c.price)}</td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{fmt(c.shares)}</td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{fmtPx(c.cost)}</td>
                        <td className={cn("px-2 py-2.5 font-mono", pnlColor(c.pnl))}>
                          {c.pnl > 0 ? "+" : ""}
                          {fmt(c.pnl)}
                        </td>
                        <td className={cn("px-2 py-2.5 font-mono", pnlColor(c.pnl))}>
                          {c.pnl_pct > 0 ? "+" : ""}
                          {c.pnl_pct}%
                        </td>
                        <td className="px-2 py-2.5">
                          <button
                            onClick={() => removeClosed(i)}
                            className="text-muted-foreground/50 hover:text-destructive"
                            title="删除"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassCard>
        </div>
      )}

      {activeTab === "risk" && <RiskDashboardTab />}
      {activeTab === "health" && <HealthScoreTab />}
      {activeTab === "pb-roe" && <PbRoeScatterTab />}

      <Disclaimer />
    </div>
  );
}
