import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Loader2 } from "lucide-react";
import { Disclaimer } from "@/components/ui/Disclaimer";

interface StockDetail {
  code: string;
  name: string;
  [key: string]: any;
}

export function StockDeep() {
  const { code } = useParams<{ code: string }>();
  const [stock, setStock] = useState<StockDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setTimeout(() => {
      setStock({ code: code ?? "", name: "示例股票" });
      setLoading(false);
    }, 500);
  }, [code]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="个股深度" subtitle={`${code} ${stock?.name ?? ""}`} />
      
      <div className="grid gap-4">
        <GlassCard className="p-4">
          <h3 className="mb-3 text-sm font-semibold">基本信息</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <p className="text-xs text-muted-foreground">代码</p>
              <p className="font-mono">{stock?.code}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">名称</p>
              <p className="font-medium">{stock?.name}</p>
            </div>
          </div>
        </GlassCard>
      </div>
      
      <Disclaimer />
    </div>
  );
}

export default StockDeep;
