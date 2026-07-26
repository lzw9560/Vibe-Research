import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Loader2, AlertCircle } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { EmptyState } from "@/components/ui/EmptyState";
import { Disclaimer } from "@/components/ui/Disclaimer";

export function StockData() {
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = () => {
    const c = code.trim().toUpperCase();
    if (!c) { setErr("请输入股票代码"); return; }
    // Validate: must be 6 digits (A-share) or alphanumeric (US/HK)
    if (!/^[a-zA-Z0-9.]+$/.test(c)) { setErr("代码格式不正确"); return; }
    setLoading(true);
    setErr(null);
    // Navigate to unified stock page — it handles all stock types
    navigate(`/stock/${c}`);
  };

  return (
    <div className="max-w-2xl mx-auto">
      <PageHeader
        title="个股数据"
        subtitle="输入股票代码，一键查看行情 · 估值 · K线 · 资金面 —— A股/美股/港股统一分析"
      />

      {/* 查询框 */}
      <div className="mb-5 flex gap-2">
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/[^a-zA-Z0-9.]/g, "").toUpperCase().slice(0, 12))}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="A 股 6 位代码，或美股/港股/韩股（AAPL / 00700 / 005930.KS）"
          className="w-80"
        />
        <Button onClick={run} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          查询
        </Button>
      </div>

      {err && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {!code && !err && !loading && (
        <EmptyState
          icon={<Search className="h-8 w-8 text-muted-foreground/40" />}
          title="输入股票代码开始查询"
          description="输入 A 股 6 位代码，或美股/港股/韩股代码，查看行情、估值、研报与新闻。"
        />
      )}

      <Disclaimer />
    </div>
  );
}
