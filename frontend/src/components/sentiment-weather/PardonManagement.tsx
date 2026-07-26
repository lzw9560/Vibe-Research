import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { api } from "@/lib/api";
import type { FusePardonRecord } from "@/lib/api";

interface PardonManagementProps {
  isAdmin: boolean;
  onUpdate: () => void;
}

export function PardonManagement({ isAdmin, onUpdate }: PardonManagementProps) {
  const [records, setRecords] = useState<FusePardonRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);

  const loadRecords = async () => {
    setLoading(true);
    try {
      const data = await api.sentimentWeatherPardon();
      setRecords((data as any).pardon_records ?? []);
    } catch (e) {
      console.error("Failed to load pardon records:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (strategyCode: string) => {
    setToggling(strategyCode);
    try {
      await api.sentimentWeatherPardonToggle({
        strategy_code: strategyCode,
        reason: "管理员赦免",
        max_position_pct: 0.35,
      });
      onUpdate();
    } catch (e) {
      console.error("Failed to toggle pardon:", e);
    } finally {
      setToggling(null);
    }
  };

  const handleRevoke = async (pardonId: string) => {
    try {
      await api.sentimentWeatherPardonRevoke(pardonId);
      onUpdate();
    } catch (e) {
      console.error("Failed to revoke pardon:", e);
    }
  };

  if (!isAdmin) {
    return (
      <GlassCard glow className="p-6">
        <h3 className="text-lg font-semibold mb-4">赦免管理</h3>
        <p className="text-sm text-white/60">仅管理员可见此模块</p>
      </GlassCard>
    );
  }

  return (
    <GlassCard glow className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">赦免管理</h3>
        <Button variant="ghost" size="sm" onClick={loadRecords} disabled={loading}>
          {loading ? "加载中..." : "刷新"}
        </Button>
      </div>

      <div className="space-y-4">
        {records.map((record) => (
          <div key={record.id} className="p-4 rounded-lg bg-white/5 border border-white/10">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="font-medium">{record.strategy_name}</span>
                <Badge variant={record.is_active ? "success" : "default"}>
                  {record.is_active ? "生效中" : "已撤销"}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                {record.is_active ? (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => handleRevoke(record.id)}
                  >
                    撤销
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => handleToggle(record.strategy_code)}
                    disabled={toggling === record.strategy_code}
                  >
                    {toggling === record.strategy_code ? "处理中..." : "重新赦免"}
                  </Button>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <p className="text-white/60">开启人</p>
                <p className="tabular-nums">{record.enabled_by}</p>
              </div>
              <div>
                <p className="text-white/60">审批人</p>
                <p className="tabular-nums">{record.approved_by}</p>
              </div>
              <div>
                <p className="text-white/60">创建时间</p>
                <p className="tabular-nums">{record.created_at}</p>
              </div>
              <div>
                <p className="text-white/60">有效期至</p>
                <p className="tabular-nums">{record.expires_at}</p>
              </div>
              <div>
                <p className="text-white/60">最大仓位</p>
                <p className="tabular-nums">{(record.max_position_pct * 100).toFixed(0)}%</p>
              </div>
              <div>
                <p className="text-white/60">原因</p>
                <p className="truncate">{record.reason}</p>
              </div>
            </div>

            {record.outcome && (
              <div className="mt-3 p-2 rounded bg-black/20">
                <p className="text-xs text-white/70">
                  <span className="text-white/50">交易结果:</span>{" "}
                  {record.outcome.was_successful ? "✅ 成功" : "❌ 失败"} (
                  {(record.outcome.return_pct * 100).toFixed(2)}%)
                </p>
                {record.outcome.lessons_learned && (
                  <p className="text-xs text-white/50 mt-1">{record.outcome.lessons_learned}</p>
                )}
              </div>
            )}
          </div>
        ))}

        {records.length === 0 && (
          <p className="text-sm text-white/60 text-center py-4">暂无赦免记录</p>
        )}
      </div>
    </GlassCard>
  );
}
