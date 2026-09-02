// S071 盘前选股 — breakout 弱信号（§44 naive lift=1.36x <2x 最弱方向特征）。
// R:R 1:2 只设盈亏平衡门槛不创造 edge；honest 标签前置。breakout 已降级 2 级导航研究（本页为独立入口）。
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { usePremarketSelection } from "@/lib/query/premarket";

export function PremarketSelection() {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [topN, setTopN] = useState(20);
  const [minScore, setMinScore] = useState(0.9);

  const { data, isLoading, error, refetch, isFetching } = usePremarketSelection(date, topN, minScore);

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4">
      <PageHeader
        title="盘前选股（breakout 弱信号）"
        subtitle="breakout_20d 排序 → top-N + 风控具体价。§44 naive lift=1.36x <2x，非 validated edge（4 方向特征里最弱）。"
      />
      <Disclaimer />

      {/* 参数 */}
      <GlassCard>
        <div className="flex flex-wrap items-end gap-4 p-4">
          <label className="text-sm text-gray-300">
            目标交易日 T
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="ml-2 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-gray-100"
            />
          </label>
          <label className="text-sm text-gray-300">
            top_n
            <input
              type="number"
              min={1}
              max={50}
              value={topN}
              onChange={(e) => setTopN(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
              className="ml-2 w-20 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-gray-100"
            />
          </label>
          <label className="text-sm text-gray-300">
            min_score
            <input
              type="number"
              step={0.01}
              min={0}
              max={1}
              value={minScore}
              onChange={(e) => setMinScore(Math.min(1, Math.max(0, Number(e.target.value) || 0)))}
              className="ml-2 w-20 rounded border border-gray-600 bg-gray-800 px-2 py-1 text-gray-100"
            />
          </label>
          <button
            onClick={() => refetch()}
            disabled={isFetching || !date}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {isFetching ? "查询中…" : "刷新"}
          </button>
        </div>
      </GlassCard>

      {/* honest 弱信号标注 */}
      {data && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
          <span className="font-semibold">⚠ 弱信号诚实标注：</span> {data.honest_label}
        </div>
      )}

      {isLoading && <div className="text-sm text-gray-500">加载中…</div>}
      {error && <div className="text-sm text-red-400">查询失败：{(error as Error).message}</div>}

      {data && (
        <>
          {/* 风控参数 */}
          <GlassCard>
            <div className="p-4">
              <h3 className="mb-3 text-sm font-semibold text-gray-200">风控参数（edge 主来自风控非对称）</h3>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                <Param label="单票仓位" value={`${data.risk_params.position_pct}%`} />
                <Param label="最大持仓数" value={`${data.risk_params.max_positions}`} />
                <Param label="止损" value={`${data.risk_params.stop_loss_pct}%`} />
                <Param label="止盈" value={`${data.risk_params.take_profit_pct}%`} />
                <Param label="最大持有" value={`${data.risk_params.max_hold_days} 日`} />
                <Param label="日历因子" value={`×${data.calendar_multiplier}（${data.calendar_reason || "常规"}）`} />
              </div>
              <p className="mt-3 text-xs text-gray-400">{data.market_note}</p>
            </div>
          </GlassCard>

          {/* 候选表 */}
          <GlassCard>
            <div className="overflow-x-auto p-4">
              <h3 className="mb-3 text-sm font-semibold text-gray-200">
                候选（{data.count}）— breakout 分数降序
              </h3>
              <table className="w-full text-left text-sm">
                <thead className="text-gray-400">
                  <tr>
                    <th className="px-2 py-1">代码</th>
                    <th className="px-2 py-1">名称</th>
                    <th className="px-2 py-1">breakout</th>
                    <th className="px-2 py-1">T-1 收盘</th>
                    <th className="px-2 py-1">入场参考</th>
                    <th className="px-2 py-1">止损</th>
                    <th className="px-2 py-1">止盈</th>
                    <th className="px-2 py-1">仓位</th>
                  </tr>
                </thead>
                <tbody>
                  {data.candidates.map((c) => (
                    <tr key={c.code} className="border-t border-gray-700/50 hover:bg-gray-800/40">
                      <td className="px-2 py-1.5">
                        <Link to={`/stock/${c.code}`} className="text-blue-400 hover:underline">
                          {c.code}
                        </Link>
                      </td>
                      <td className="px-2 py-1.5 text-gray-300">{c.name || "—"}</td>
                      <td className="px-2 py-1.5">
                        <span className={c.breakout_binary ? "text-emerald-400" : "text-gray-400"}>
                          {c.breakout_score.toFixed(3)}
                          {c.breakout_binary ? " ●" : ""}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-gray-300">
                        {c.t1_close} <span className="text-xs text-gray-500">({c.t1_date})</span>
                      </td>
                      <td className="px-2 py-1.5 text-gray-300">{c.entry_ref}</td>
                      <td className="px-2 py-1.5 text-red-400">{c.stop_loss}</td>
                      <td className="px-2 py-1.5 text-emerald-400">{c.take_profit}</td>
                      <td className="px-2 py-1.5 text-gray-300">{c.position_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.candidates.length === 0 && (
                <p className="py-4 text-center text-sm text-gray-500">
                  无满足条件的候选（调高 min_score 或换日）
                </p>
              )}
            </div>
          </GlassCard>
        </>
      )}
    </div>
  );
}

function Param({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-gray-400">{label}</span>
      <span className="ml-2 font-medium text-gray-100">{value}</span>
    </div>
  );
}
