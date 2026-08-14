import { useState, useEffect } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api } from "@/lib/api";
import { AskAiButton } from "@/components/ui/AskAiButton";

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
  one_day_seats: Array<{ seat_name: string; one_day_rate: number; avg_return: number; type: string }>;
  multi_day_seats: Array<{ seat_name: string; one_day_rate: number; avg_return: number; type: string }>;
  disclaimer: string;
}

export default function RiskDashboard() {
  const [data, setData] = useState<RiskDashboardData | null>(null);
  const [highRiskList, setHighRiskList] = useState<HighRiskStock[]>([]);
  const [seats, setSeats] = useState<RiskSeatsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [dashboard, highRisk, seatsData] = await Promise.all([
        api.riskDashboard(),
        api.riskOnedayList(undefined, 70).catch(() => []),
        api.riskSeats().catch(() => null),
      ]);
      setData(dashboard);
      setHighRiskList(Array.isArray(highRisk) ? highRisk : []);
      setSeats(seatsData);
    } catch (e: any) {
      setError(e?.message ?? "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

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

  // S066 AskAi：注入风险分布 + 高风险股
  const askAiContext = [
    `当前页面：风险仪表盘（RiskDashboard）`,
    data ? `日期${data.date}：扫描${data.total_stocks}只/高${data.high_risk_count}/中${data.medium_risk_count}/低${data.low_risk_count}` : `风险分布：未取得`,
    highRiskList.length > 0
      ? `高风险股：${highRiskList.slice(0, 8).map((s) => `${s.code}(${s.name})分${s.risk_score}/[${s.factors.slice(0, 2).join("/")}]`).join("，")}`
      : `高风险股：无`,
  ].join("\n");

  return (
    <div className="space-y-4">
      <PageHeader
        title="风险仪表盘"
        subtitle="个股风险量化 + 板块风险分布（客观数据，非行动建议）"
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton context={askAiContext} />
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg bg-primary/90 px-3 py-2 text-sm text-primary-foreground hover:bg-primary disabled:opacity-60"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </button>
          </div>
        }
      />

      <Disclaimer compact />

      {error && (
        <GlassCard>
          <div className="p-4 text-sm text-red-600">加载失败：{error}</div>
        </GlassCard>
      )}

      {data && (
        <>
          {/* 统计卡片 */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard
              label="高风险"
              value={data.high_risk_count}
              valueClassName="text-red-600"
            />
            <MetricCard
              label="中风险"
              value={data.medium_risk_count}
              valueClassName="text-amber-600"
            />
            <MetricCard
              label="低风险"
              value={data.low_risk_count}
              valueClassName="text-emerald-600"
            />
          </div>

          {/* 风险分布列表 */}
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

          {/* 风险因素排行 */}
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

          {/* 一日游席位库 */}
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
                          一日游概率 {(seat.one_day_rate * 100).toFixed(0)}% · 平均收益 {(seat.avg_return >= 0 ? '+' : '') + seat.avg_return.toFixed(1)}%
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
                          一日游概率 {(seat.one_day_rate * 100).toFixed(0)}% · 平均收益 {(seat.avg_return >= 0 ? '+' : '') + seat.avg_return.toFixed(1)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </GlassCard>
          )}
        </>
      )}
    </div>
  );
}
