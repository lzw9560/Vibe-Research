// 尾盘错杀偏离度面板：个股 vs 全市场实时偏离度时间序列（read-only 看板）。
// fetch 轮询 5s，偏离度>=3% 行高亮绿色。
import { useEffect, useRef, useState } from "react";

const api = "http://127.0.0.1:8900";

interface DeviationPoint {
  ts: string;
  stock_change: number;
  sector_median: number;
  sector_mean: number;
  deviation_from_median: number;
  deviation_from_mean: number;
  is_anomalous: boolean;
  sample_size: number;
}

interface DeviationResponse {
  code: string;
  date: string;
  data_points: DeviationPoint[];
  max_deviation: number;
  anomalous_count: number;
}

function fmtPct(v: number): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

export default function TailDipDeviationPanel({ code }: { code: string }) {
  const [data, setData] = useState<DeviationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;
    const codeTrim = code.trim();

    async function poll() {
      if (!codeTrim) {
        setLoading(false);
        setData(null);
        return;
      }
      try {
        const res = await fetch(
          `${api}/api/strategy/tail-dip/deviation?code=${encodeURIComponent(codeTrim)}`,
        );
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const json: DeviationResponse = await res.json();
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "请求失败");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    setLoading(true);
    poll();
    timerRef.current = setInterval(poll, 5000);

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [code]);

  return (
    <div className="rounded-lg bg-slate-900 p-4 text-slate-100">
      {/* 标题 + 统计概览 */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-100">
          尾盘错杀偏离度 · <span className="font-mono text-slate-400">{code}</span>
        </h3>
        {data && (
          <div className="flex items-center gap-4 text-xs">
            <span className="text-slate-400">
              最大偏离度 <span className="font-mono text-emerald-400">{data.max_deviation.toFixed(2)}%</span>
            </span>
            <span className="text-slate-400">
              错杀次数 <span className="font-mono text-amber-400">{data.anomalous_count}</span>
            </span>
          </div>
        )}
      </div>

      {/* honest banner */}
      <div className="mb-3 rounded-md bg-slate-800/60 px-3 py-1.5 text-[11px] text-slate-400">
        偏离度 = 个股涨跌 − 板块中位涨跌 · 绿色高亮 ≥3% · 5s 轮询 · 非交易信号（read-only）
      </div>

      {error ? (
        <div className="rounded bg-red-500/10 px-3 py-2 text-[13px] text-red-400">
          偏离度数据加载失败：{error}
        </div>
      ) : loading && !data ? (
        <div className="py-6 text-center text-sm text-slate-400">加载中…</div>
      ) : !data || data.data_points.length === 0 ? (
        <div className="py-6 text-center text-sm text-slate-400">无偏离度数据</div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-slate-700 text-left text-slate-400">
                  <th className="py-1 pr-2">时间</th>
                  <th className="py-1 pr-2">个股涨跌%</th>
                  <th className="py-1 pr-2">板块中位%</th>
                  <th className="py-1 pr-2">偏离度</th>
                  <th className="py-1 pr-2">是否错杀</th>
                </tr>
              </thead>
              <tbody>
                {data.data_points.map((p: DeviationPoint, i: number) => {
                  const highlight = Math.abs(p.deviation_from_median) >= 3;
                  return (
                    <tr
                      key={`${p.ts}-${i}`}
                      className={`border-b border-slate-800/50 ${
                        highlight ? "bg-emerald-500/15" : ""
                      }`}
                    >
                      <td className="py-1 pr-2 font-mono text-slate-300">{p.ts}</td>
                      <td
                        className={`py-1 pr-2 font-mono ${
                          p.stock_change >= 0 ? "text-red-400" : "text-green-400"
                        }`}
                      >
                        {fmtPct(p.stock_change)}
                      </td>
                      <td
                        className={`py-1 pr-2 font-mono ${
                          p.sector_median >= 0 ? "text-red-400/80" : "text-green-400/80"
                        }`}
                      >
                        {fmtPct(p.sector_median)}
                      </td>
                      <td
                        className={`py-1 pr-2 font-mono ${
                          highlight ? "font-bold text-emerald-300" : "text-slate-300"
                        }`}
                      >
                        {fmtPct(p.deviation_from_median)}
                      </td>
                      <td className="py-1 pr-2">
                        {p.is_anomalous ? (
                          <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[11px] text-amber-300">
                            错杀
                          </span>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-xs text-slate-500">
            共 {data.data_points.length} 条 · {data.date}
          </div>
        </>
      )}
    </div>
  );
}
