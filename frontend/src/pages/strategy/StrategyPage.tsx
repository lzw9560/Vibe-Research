// S093 T19：战法独立路由页——/strategy。
// 承接 S3 从 Workflow.tsx 前瞻 Tab 删的战法战绩折叠区（原 323-374 行）。
// 内容：战法战绩表（registry+backtest）+ 前向测试入口 + 阈值配置入口。
// 工程底线：不臆造——query 无数据返空数组；缺字段标"—"。
// 历史统计特征标注：参考值，非执行指令；市场有风险。
// 修复原 bug：原 Workflow.tsx 用 request<{ data: Array<...> }> 但 request 已 unwrap .data，
//   导致 registry?.data 恒 undefined（表格恒空）。改用 request<StrategyRegistryItem[]> 直接返数组。
import { Link } from "react-router-dom";
import { ArrowLeft, Activity, Layers } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EntryCard } from "@/components/workflow/EntryCard";
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { useStrategyBacktest } from "@/lib/query/strategy";

/** 战法库注册表条目（对应后端 get_strategy_registry 返回字段）。 */
interface StrategyRegistryItem {
  code: string;
  name: string;
  entry_type: string;
  entry_condition: string;
  stop_loss_condition: string;
  take_profit_condition: string;
  exit_condition: string;
  max_hold_days: number;
  weather_regimes: string[];
  aliases: string[];
}

export default function StrategyPage() {
  // 战法注册表——12 战法定义（code/name/entry_condition/max_hold_days 等）
  const { data: registry, isLoading: registryLoading } = useQuery({
    queryKey: ["strategy-registry"] as const,
    queryFn: () => request<StrategyRegistryItem[]>(`/strategy/registry`),
    staleTime: 5 * 60_000,
  });

  // 战法回测——60 日窗口各战法胜率/均收益/样本（useStrategyBacktest 已 unwrap .data）
  const { data: backtest, isLoading: backtestLoading } = useStrategyBacktest(60);

  const registryItems = registry ?? [];
  const backtestItems = backtest ?? [];

  return (
    <div className="space-y-3 p-4">
      {/* 返回工作流 */}
      <Link
        to="/workflow"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 返回工作流
      </Link>

      <PageHeader
        title="战法管理"
        subtitle="战法战绩 · 前向测试 · 阈值配置"
      />

      {/* 战法战绩表 */}
      <GlassCard className="p-2">
        <h3 className="mb-2 px-2 font-semibold">战法战绩 + 参数</h3>
        {registryLoading || backtestLoading ? (
          <p className="px-2 py-4 text-sm text-muted-foreground">加载中…</p>
        ) : registryItems.length === 0 ? (
          <p className="px-2 py-4 text-sm text-muted-foreground">暂无战法数据</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/40 text-muted-foreground/70">
                  <th className="px-2 py-1 text-left">战法</th>
                  <th className="px-2 py-1 text-right">胜率</th>
                  <th className="px-2 py-1 text-right">均收益%</th>
                  <th className="px-2 py-1 text-right">样本</th>
                  <th className="px-2 py-1 text-right">持有日</th>
                  <th className="px-2 py-1 text-left">入场条件</th>
                </tr>
              </thead>
              <tbody>
                {registryItems.map((r) => {
                  const bt = backtestItems.find((b) => b.strategy_code === r.code);
                  return (
                    <tr key={r.code} className="border-b border-border/20 hover:bg-muted/10">
                      <td className="px-2 py-1">{r.name}</td>
                      <td className="px-2 py-1 text-right font-mono">
                        {bt ? (bt.sample_size > 0 ? `${(bt.win_rate * 100).toFixed(1)}%` : "数据缺失") : "—"}
                      </td>
                      <td className="px-2 py-1 text-right font-mono">
                        {bt ? bt.avg_return : "—"}
                      </td>
                      <td className="px-2 py-1 text-right">{bt?.sample_size ?? "—"}</td>
                      <td className="px-2 py-1 text-right">{r.max_hold_days}</td>
                      <td className="max-w-[16rem] truncate px-2 py-1 text-muted-foreground/70">
                        {r.entry_condition}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* 前向测试 + 阈值配置入口 */}
      <EntryCard
        to="/strategy/funnel/forward-test"
        title="前向测试 §44"
        subtitle="60 日复验 lift/winrate/validation_status"
        icon={Activity}
      />
      <EntryCard
        to="/strategy/funnel/config"
        title="战法阈值配置"
        subtitle="S081 阈值 + funnel config（可改）"
        icon={Layers}
      />

      <p className="text-[10px] text-muted-foreground/60">
        参考值，非执行指令；市场有风险
      </p>

      <Disclaimer compact />
    </div>
  );
}
