import { useState, useEffect } from "react";
import { Loader2, RefreshCw, Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api } from "@/lib/api";

interface StrategySignalItem {
  code: string;
  name: string;
  strategy_name: string;
  strategy_code: string;
  score: number;
  signal_strength: number;
  confidence: number;
  entry_price: number;
  entry_condition: string;
  entry_type: string;
  stop_loss: number;
  stop_loss_condition: string;
  take_profit: number;
  take_profit_condition: string;
  max_hold_days: number;
  exit_condition: string;
  historical_win_rate: number;
  historical_avg_return: number;
  sample_size: number;
  risk_reward_ratio: number;
  reasoning: string[];
  risk_notes: string[];
}

export default function StrategySignals() {
  const [items, setItems] = useState<StrategySignalItem[]>([]);
  const [trends, setTrends] = useState<Array<{ date: string; win_rate: number; total_trades: number }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [screener, trendsData] = await Promise.all([
        api.limitupScreener(),
        api.winRateTrends(20).catch(() => []),
      ]);
      const top = screener.gene_scores.slice(0, 20);
      const results: StrategySignalItem[] = [];
      for (const g of top) {
        try {
          const signals = await api.strategySignals(g.code, screener.date);
          if (signals && signals.length > 0) {
            results.push(...signals.map((s: any) => ({ ...s, code: g.code, name: g.name })));
          }
        } catch {
          // skip
        }
      }
      setItems(results);
      setTrends(Array.isArray(trendsData) ? trendsData : []);
    } catch (e: any) {
      setError(e?.message ?? "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader
        title="战法信号"
        subtitle="八大战法匹配与风控规则知识（教育性展示，非行动建议）"
        actions={
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-primary/90 px-3 py-2 text-sm text-primary-foreground hover:bg-primary disabled:opacity-60"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </button>
        }
      />

      <Disclaimer compact />

      {error && (
        <GlassCard>
          <div className="p-4 text-sm text-red-600">加载失败：{error}</div>
        </GlassCard>
      )}

      <div className="grid gap-3">
        {items.map((item, idx) => (
          <GlassCard key={`${item.code}-${item.strategy_code}-${idx}`} className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-base font-semibold">{item.name}</div>
                <div className="text-xs text-muted-foreground">{item.code} · {item.strategy_name}</div>
              </div>
              <div className="text-right text-xs text-muted-foreground">
                置信度：<span className="font-medium text-foreground">{(item.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground md:grid-cols-4">
              <div>入场价：<span className="font-medium text-foreground">{item.entry_price.toFixed(2)}</span></div>
              <div>止损价：<span className="font-medium text-foreground">{item.stop_loss.toFixed(2)}</span></div>
              <div>止盈价：<span className="font-medium text-foreground">{item.take_profit.toFixed(2)}</span></div>
              <div>持仓上限：<span className="font-medium text-foreground">{item.max_hold_days}天</span></div>
            </div>

            <div className="text-xs text-muted-foreground">
              {item.entry_condition}
            </div>

            <div className="flex items-start gap-1 rounded-lg bg-amber-50 p-2 text-xs text-amber-700">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{item.risk_notes[0]}</span>
            </div>
          </GlassCard>
        ))}
      </div>

      {!loading && items.length === 0 && (
        <GlassCard>
          <div className="p-6 text-center text-sm text-muted-foreground">暂无战法信号数据</div>
        </GlassCard>
      )}

      {/* 胜率趋势 */}
      {trends.length > 0 && (
        <GlassCard>
          <h3 className="mb-3 text-sm font-semibold">胜率趋势（近 {trends.length} 日）</h3>
          <div className="space-y-2">
            {trends.slice(-10).map((t, idx) => (
              <div key={idx} className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{t.date}</span>
                <span className="font-medium">
                  胜率 {(t.win_rate * 100).toFixed(1)}% · {t.total_trades} 笔
                </span>
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  );
}
