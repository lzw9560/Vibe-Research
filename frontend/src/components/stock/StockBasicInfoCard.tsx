// S215 收尾：个股基本面卡（akshare 源）——调 /api/info?code= 展示行业/股本/上市时间。
// 接入孤儿 /api/info（前后端闭环，不孤儿 API）。改名 StockBasicInfoCard 避免跟
// StockCockpit 本地 BasicInfoCard（quote 源）冲突——两者共存：本地用 quote 实时字段，
// 本卡用 akshare 全基本面（行业/股本/上市时间）。
import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api } from "@/lib/api";

interface BasicInfoResponse {
  data?: Record<string, string | number | null>;
  error?: string;
}

interface Props {
  code: string;
}

export function StockBasicInfoCard({ code }: Props) {
  const [data, setData] = useState<BasicInfoResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api
      .basicInfo(code)
      .then((r) => {
        if (!cancelled) setData(r as BasicInfoResponse);
      })
      .catch((e: unknown) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (loading) {
    return <div className="p-4 text-sm text-muted-foreground">加载基本面…</div>;
  }
  if (err) {
    return <div className="p-4 text-sm text-red-600">加载失败: {err}</div>;
  }
  if (!data) return null;
  const info = data.data ?? {};
  const entries = Object.entries(info).filter(([, v]) => v != null && v !== "");

  if (entries.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        基本面不可用（akshare 数据缺失）
      </div>
    );
  }

  return (
    <GlassCard className="space-y-2 p-4">
      <h3 className="text-sm font-semibold">基本面（akshare）</h3>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-foreground">{String(v)}</dd>
          </div>
        ))}
      </dl>
    </GlassCard>
  );
}

export default StockBasicInfoCard;
