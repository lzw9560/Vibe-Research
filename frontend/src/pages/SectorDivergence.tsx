import { useState, useEffect } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Loader2 } from "lucide-react";
import { Disclaimer } from "@/components/ui/Disclaimer";

interface SectorData {
  name: string;
  divergence: number;
  rotation: number;
}

export function SectorDivergence() {
  const [data, setData] = useState<SectorData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    // TODO: 实现板块分化 API
    setTimeout(() => {
      setData([
        { name: "科技", divergence: 0.65, rotation: 0.32 },
        { name: "消费", divergence: 0.45, rotation: 0.28 },
        { name: "金融", divergence: 0.38, rotation: 0.15 },
      ]);
      setLoading(false);
    }, 500);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="板块分化" subtitle="Sector Divergence" />
      
      <div className="grid gap-4">
        <GlassCard className="p-4">
          <h3 className="mb-3 text-sm font-semibold">板块分化度</h3>
          <div className="space-y-2">
            {data.map((s) => (
              <div key={s.name} className="flex items-center gap-3">
                <span className="w-20 text-sm">{s.name}</span>
                <div className="flex-1 h-2 rounded-full bg-muted/20">
                  <div 
                    className="h-2 rounded-full bg-primary" 
                    style={{ width: `${s.divergence * 100}%` }}
                  />
                </div>
                <span className="w-12 text-right font-mono text-sm">{s.divergence.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
      
      <Disclaimer />
    </div>
  );
}

export default SectorDivergence;
