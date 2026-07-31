// 阈值配置面板：auto/suggest/manual 切换 + 调参（S002 F4，AC2）。
import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Button } from "@/components/ui/Button";
import { candidatesApi, type FunnelConfigResponse, type ThresholdConfig } from "@/lib/candidates";

const MODES: ThresholdConfig["mode"][] = ["auto", "suggest", "manual"];

export function ThresholdPanel() {
  const [cfg, setCfg] = useState<FunnelConfigResponse | null>(null);
  const [mode, setMode] = useState<ThresholdConfig["mode"]>("suggest");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    candidatesApi.getConfig().then((c) => { setCfg(c); setMode(c.config.mode); }).catch((e) => setErr(String(e)));
  }, []);

  const save = async () => {
    setSaving(true); setErr(null);
    try { const r = await candidatesApi.putConfig({ mode }); setCfg(r); }
    catch (e: any) { setErr(e?.message || String(e)); }
    finally { setSaving(false); }
  };

  return (
    <GlassCard className="p-4 space-y-3">
      <SectionHeader title="阈值配置" subtitle="auto/suggest/manual 三模式，默认建议" />
      {err && <div className="text-sm text-danger">{err}</div>}
      <div className="flex gap-2">
        {MODES.map((m) => (
          <Button key={m} variant={mode === m ? "primary" : "ghost"} onClick={() => setMode(m)}>
            {m === "auto" ? "自动" : m === "suggest" ? "建议" : "手动"}
          </Button>
        ))}
      </div>
      {cfg && (
        <div className="text-sm text-muted-foreground">
          当日情绪档：<span className="text-foreground">{cfg.config.sentiment_phase || "未取得（降级基数）"}</span>
          {cfg.config.adjustment?.依据
            ? <div className="mt-1">依据：{String(cfg.config.adjustment.依据)}</div>
            : null}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button onClick={save} disabled={saving}>{saving ? "保存中…" : "保存模式"}</Button>
        {cfg && <span className="text-xs text-muted-foreground">来源开关：{Object.entries(cfg.sources).filter(([, v]) => v).map(([k]) => k).join("、")}</span>}
      </div>
    </GlassCard>
  );
}
