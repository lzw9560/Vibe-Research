import { useState, useEffect } from "react";
import { KeyRound, Sparkles, ShieldCheck, Check, Trash2, Terminal, Flame } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { toast } from "sonner";
import { loadLlm, saveLlm, clearLlm } from "@/lib/llm";
import { loadAccessKey, saveAccessKey, getLimitUpScreenerParams, saveLimitUpScreenerParams, getAuctionParams, saveAuctionParams, getReviewParams, saveReviewParams, getLlmEnvStatus, type LimitUpParams, type AuctionParams, type ReviewParams, type LlmEnvStatus } from "@/lib/api";
import { subscriptionModels, apiModels, PROVIDER_BASE, isCliProvider, aiModels, type ProviderId } from "@/lib/ai-models";

export function Settings() {
  const existing = loadLlm();
  const existingIsCli = existing ? isCliProvider(existing.provider) : false;

  const [mode, setMode] = useState<"api" | "subscription">(existing && existingIsCli ? "subscription" : "api");
  // 订阅：选中的 CLI model id
  const [cliId, setCliId] = useState(existing && existingIsCli ? existing.model : "");
  // API：选中的模型 id + 可编辑的 baseURL / model / key
  const firstApi = apiModels[0];
  const [apiId, setApiId] = useState(existing && !existingIsCli ? existing.model : firstApi.id);
  const [baseURL, setBaseURL] = useState(existing && !existingIsCli ? existing.baseURL : (PROVIDER_BASE[firstApi.provider] || ""));
  const [modelName, setModelName] = useState(existing && !existingIsCli ? existing.model : firstApi.id);
  const [apiKey, setApiKey] = useState(existing && !existingIsCli ? existing.apiKey : "");
  // 后端访问密钥（对应部署时的 VR_API_KEY）；本机自用不设鉴权时留空
  const [accessKey, setAccessKey] = useState(loadAccessKey());

  // 打板策略参数
  const [limitUpParams, setLimitUpParams] = useState<LimitUpParams>({
    gene_qualify_threshold: 60,
    gene_high_threshold: 75,
    lookback_days: 60,
  });
  const [paramsLoading, setParamsLoading] = useState(false);

  // 竞价选股参数
  const [auctionParams, setAuctionParams] = useState<AuctionParams>({
    min_gene_score: 50,
    min_zt_count: 2,
    top_n: 50,
  });
  const [auctionLoading, setAuctionLoading] = useState(false);

  // 复盘报告参数
  const [reviewParams, setReviewParams] = useState<ReviewParams>({
    max_zt_stocks: 100,
    auction_top_n: 20,
  });
  const [reviewLoading, setReviewLoading] = useState(false);

  useEffect(() => {
    getLimitUpScreenerParams().then(setLimitUpParams).catch(console.error);
    getAuctionParams().then(setAuctionParams).catch(console.error);
    getReviewParams().then(setReviewParams).catch(console.error);
  }, []);

  const [llmEnvStatus, setLlmEnvStatus] = useState<LlmEnvStatus | null>(null);
  const [llmEnvLoading, setLlmEnvLoading] = useState(false);

  useEffect(() => {
    setLlmEnvLoading(true);
    getLlmEnvStatus()
      .then(setLlmEnvStatus)
      .catch(() => setLlmEnvStatus(null))
      .finally(() => setLlmEnvLoading(false));
  }, []);

  const handleSaveParams = async () => {
    setParamsLoading(true);
    try {
      await saveLimitUpScreenerParams(limitUpParams);
      toast.success("打板策略参数已保存");
    } catch {
      toast.error("保存失败");
    } finally {
      setParamsLoading(false);
    }
  };

  const handleSaveAuctionParams = async () => {
    setAuctionLoading(true);
    try {
      await saveAuctionParams(auctionParams);
      toast.success("竞价选股参数已保存");
    } catch {
      toast.error("保存失败");
    } finally {
      setAuctionLoading(false);
    }
  };

  const handleSaveReviewParams = async () => {
    setReviewLoading(true);
    try {
      await saveReviewParams(reviewParams);
      toast.success("复盘报告参数已保存");
    } catch {
      toast.error("保存失败");
    } finally {
      setReviewLoading(false);
    }
  };

  const providerOf = (id: string): ProviderId => aiModels.find((m) => m.id === id)?.provider ?? "openai-compatible";

  const pickApiModel = (id: string) => {
    const m = apiModels.find((x) => x.id === id);
    if (!m) return;
    setApiId(id);
    setModelName(id);
    setBaseURL(PROVIDER_BASE[m.provider] || "");
  };

  const saveApi = () => {
    if (!baseURL.trim() || !apiKey.trim() || !modelName.trim()) {
      toast.error("请填完 Base URL、API Key、Model");
      return;
    }
    saveLlm({ provider: providerOf(apiId), baseURL: baseURL.trim(), apiKey: apiKey.trim(), model: modelName.trim() });
    toast.success("已保存到本地，全站「问 AI / 复盘」现在可用");
  };

  const saveSubscription = () => {
    const m = subscriptionModels.find((x) => x.id === cliId);
    if (!m || m.comingSoon) {
      toast.error("请选择一个可用的订阅（暂不支持标「即将支持」的）");
      return;
    }
    saveLlm({ provider: m.provider, baseURL: "", apiKey: "", model: m.id });
    toast.success(`已选「${m.name}」订阅，全站「问 AI / 复盘」将调用本机 ${m.name}`);
  };

  const forget = () => {
    clearLlm();
    setApiKey("");
    setCliId("");
    toast.success("已清除本地配置");
  };

  const saveAccess = () => {
    const k = accessKey.trim();
    saveAccessKey(k);
    setAccessKey(k);
    toast.success(k ? "已保存后端访问密钥（存本地）" : "已清除后端访问密钥");
  };

  return (
    <div>
      <PageHeader title="接入 AI" subtitle="配置一次，全站的「问 AI」「复盘」都能用你自己的模型" />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-success/25 bg-success/5 p-3 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
        <span>API key <b className="text-foreground">只存在你本地浏览器</b>，仅在你提问时发给你自己的后端去调模型，不上传、不进仓库。所有分析由你的模型给出，本产品不校准。</span>
      </div>

      {/* 两种接入方式 */}
      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <GlassCard glow={mode === "subscription"} onClick={() => setMode("subscription")}
          className={mode === "subscription" ? "ring-1 ring-primary/40" : "opacity-80"}>
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            <h3 className="font-semibold">订阅接入</h3>
            {mode === "subscription" && <Check className="ml-auto h-4 w-4 text-primary" />}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">调本机已登录的 AI CLI（Claude Code / Qwen / DeepSeek / Codex…），用订阅额度，<b className="text-foreground">免 API key</b>。需后端在本机跑。</p>
        </GlassCard>

        <GlassCard glow={mode === "api"} onClick={() => setMode("api")}
          className={mode === "api" ? "ring-1 ring-primary/40" : "opacity-80"}>
          <div className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-primary" />
            <h3 className="font-semibold">API 接入</h3>
            {mode === "api" && <Check className="ml-auto h-4 w-4 text-primary" />}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">粘贴 API key，支持 DeepSeek / 豆包 / MiniMax / OpenAI / OpenRouter / 任意兼容端点。<b className="text-foreground">现已可用。</b></p>
        </GlassCard>
      </div>

      <GlassCard>
        {mode === "subscription" ? (
          <div className="space-y-3 text-sm">
            <p className="text-xs text-muted-foreground">
              选一个你本机已安装并登录的 CLI。Vibe-Research 后端会用它以你的订阅额度作答，<b className="text-foreground">不用填 key</b>。
              <span className="text-muted-foreground/60">（仅当后端跑在你本机时可用；复盘 / 今日要点 / 个股问 AI 等场景。）</span>
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {subscriptionModels.map((m) => {
                const on = cliId === m.id;
                return (
                  <button key={m.id} disabled={m.comingSoon} onClick={() => setCliId(m.id)}
                    className={`flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                      m.comingSoon
                        ? "cursor-not-allowed border-border/50 opacity-40"
                        : on
                        ? "border-primary/50 bg-primary/10"
                        : "border-border hover:bg-muted/40"
                    }`}>
                    <Terminal className={`h-4 w-4 shrink-0 ${on ? "text-primary" : "text-muted-foreground"}`} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 font-medium">
                        {m.name}
                        {m.comingSoon && <span className="rounded bg-muted/60 px-1 py-0.5 text-[9px] text-muted-foreground">即将支持</span>}
                        {on && <Check className="h-3.5 w-3.5 text-primary" />}
                      </div>
                      <div className="truncate text-[11px] text-muted-foreground">{m.description}</div>
                    </div>
                  </button>
                );
              })}
            </div>
            <div className="flex items-center gap-2 pt-1">
              <Button onClick={saveSubscription}>保存</Button>
              {existing && (
                <Button variant="ghost" onClick={forget}>
                  <Trash2 className="h-4 w-4" /> 清除
                </Button>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-4 text-sm">
            <div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">选择模型</label>
                <select value={apiId} onChange={(e) => pickApiModel(e.target.value)}
                  className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50">
                  {apiModels.map((m) => (
                    <option key={m.id} value={m.id}>{m.name} —— {m.description}</option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <Input label="Base URL" value={baseURL} onChange={(e) => setBaseURL(e.target.value)} placeholder="https://api.deepseek.com" />
            </div>
            <div>
              <Input label="Model" value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="模型名称（豆包填 ep-… 接入点 ID）" />
            </div>
            <div>
              <Input label="API Key" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-…" />
            </div>

            <div className="flex items-center gap-2">
              <Button onClick={saveApi}>保存（存本地）</Button>
              {existing && (
                <Button variant="ghost" onClick={forget}>
                  <Trash2 className="h-4 w-4" /> 清除
                </Button>
              )}
            </div>
          </div>
        )}
      </GlassCard>

      {/* OmniRoute 托底通道 */}
      <GlassCard className="mt-4">
        <SectionHeader title="OmniRoute 托底通道（可选）" icon={<Flame className="h-4 w-4 text-accent" />} />
        <p className="mb-3 text-xs text-muted-foreground">
          启用后，AI 对话会先走 OmniRoute 本地网关，自动切换最便宜的可用模型。
          需要先在本地安装并运行 OmniRoute（<code className="rounded bg-muted/50 px-1">npm i -g omniroute</code>）。
        </p>
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" defaultChecked={false} className="rounded border-border" />
            启用 OmniRoute 托底
          </label>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">模型选择</label>
            <select className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-accent/50">
              <option value="auto">auto（智能路由）</option>
              <option value="auto/coding">auto/coding（质量优先）</option>
              <option value="auto/fast">auto/fast（低延迟）</option>
              <option value="auto/cheap">auto/cheap（最便宜）</option>
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">OmniRoute 地址</label>
            <input defaultValue="http://localhost:20128" placeholder="http://localhost:20128"
              className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-accent/50" />
          </div>
          <div className="rounded-lg bg-accent/5 border border-accent/20 p-3 text-xs text-muted-foreground">
            ℹ OmniRoute 聚合 271 个 AI 提供商的免费/低价额度，自动故障转移。
            你的 API key 只存在本地，不上传。
          </div>
        </div>
      </GlassCard>

      {/* 后端 LLM 环境变量状态（只读） */}
      <GlassCard className="mt-4">
        <SectionHeader title="后端 LLM 环境变量（只读）" icon={<ShieldCheck className="h-4 w-4 text-primary" />} />
        <p className="mb-3 text-xs text-muted-foreground">
          后端可通过环境变量提供 LLM 兜底配置，无需在前端填写。此处仅显示配置状态，不暴露敏感值。
        </p>
        {llmEnvLoading ? (
          <p className="text-xs text-muted-foreground">加载中…</p>
        ) : llmEnvStatus ? (
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-border/60 bg-muted/20 p-2.5 text-center">
              <p className="text-[11px] text-muted-foreground">Base URL</p>
              <p className={`mt-1 text-xs font-medium ${llmEnvStatus.has_env_base_url ? "text-success" : "text-muted-foreground/50"}`}>
                {llmEnvStatus.has_env_base_url ? "已配置" : "未配置"}
              </p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-2.5 text-center">
              <p className="text-[11px] text-muted-foreground">API Key</p>
              <p className={`mt-1 text-xs font-medium ${llmEnvStatus.has_env_api_key ? "text-success" : "text-muted-foreground/50"}`}>
                {llmEnvStatus.has_env_api_key ? "已配置" : "未配置"}
              </p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-2.5 text-center">
              <p className="text-[11px] text-muted-foreground">Model</p>
              <p className={`mt-1 text-xs font-medium ${llmEnvStatus.has_env_model ? "text-success" : "text-muted-foreground/50"}`}>
                {llmEnvStatus.has_env_model ? "已配置" : "未配置"}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">无法读取后端配置状态</p>
        )}
        <div className="mt-3 rounded-lg bg-muted/10 border border-border/40 p-2.5 text-[11px] text-muted-foreground">
          对应环境变量：<code className="rounded bg-muted/50 px-1">VR_LLM_BASE_URL</code> / <code className="rounded bg-muted/50 px-1">VR_LLM_API_KEY</code> / <code className="rounded bg-muted/50 px-1">VR_LLM_MODEL</code>
        </div>
      </GlassCard>

      {/* 后端访问密钥：仅当后端部署时设置了 VR_API_KEY（公网防蹭用）才需要填 */}
      <GlassCard className="mt-4">
        <SectionHeader title="后端访问密钥（可选）" icon={<KeyRound className="h-4 w-4 text-primary" />} />
        <p className="mb-3 text-xs text-muted-foreground">
          仅当后端部署时设置了 <code className="rounded bg-muted/50 px-1">VR_API_KEY</code>（公网部署防蹭用）才需要填，填后端同一个值；
          本机自用没设鉴权就留空。同样只存本地浏览器。
        </p>
        <div className="flex items-center gap-2">
          <Input type="password" value={accessKey} onChange={(e) => setAccessKey(e.target.value)} placeholder="与后端 VR_API_KEY 保持一致" className="flex-1" />
          <Button onClick={saveAccess}>保存</Button>
        </div>
      </GlassCard>

      {/* 打板策略参数 */}
      <GlassCard className="mt-4">
        <SectionHeader title="打板策略参数" icon={<Flame className="h-4 w-4 text-primary" />} />
        <p className="mb-4 text-xs text-muted-foreground">
          调整打板策略的筛选阈值，影响选股结果的宽松/严格程度。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium">基因合格阈值</label>
            <Input
              type="number"
              value={limitUpParams.gene_qualify_threshold}
              onChange={(e) => setLimitUpParams({ ...limitUpParams, gene_qualify_threshold: Number(e.target.value) })}
            />
            <p className="mt-1 text-[11px] text-muted-foreground">≥ 此分数视为合格（默认60）</p>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium">高基因阈值</label>
            <Input
              type="number"
              value={limitUpParams.gene_high_threshold}
              onChange={(e) => setLimitUpParams({ ...limitUpParams, gene_high_threshold: Number(e.target.value) })}
            />
            <p className="mt-1 text-[11px] text-muted-foreground">≥ 此分数视为高基因（默认75）</p>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium">回溯天数</label>
            <Input
              type="number"
              value={limitUpParams.lookback_days}
              onChange={(e) => setLimitUpParams({ ...limitUpParams, lookback_days: Number(e.target.value) })}
            />
            <p className="mt-1 text-[11px] text-muted-foreground">统计最近N个交易日（默认60）</p>
          </div>
        </div>
        <Button onClick={handleSaveParams} disabled={paramsLoading}>
          {paramsLoading ? "保存中..." : "保存参数"}
        </Button>
      </GlassCard>

      {/* 竞价选股参数 */}
      <GlassCard className="mt-4">
        <SectionHeader title="竞价选股参数" icon={<Flame className="h-4 w-4 text-primary" />} />
        <p className="mb-4 text-xs text-muted-foreground">
          调整竞价选股模块的筛选阈值，影响竞价预案候选股的严格程度。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <Input label="最小基因得分" type="number" value={auctionParams.min_gene_score} onChange={(e) => setAuctionParams({ ...auctionParams, min_gene_score: Number(e.target.value) })} />
            <p className="mt-1 text-[11px] text-muted-foreground">候选股最低基因得分（默认50）</p>
          </div>
          <div>
            <Input label="最小涨停次数" type="number" value={auctionParams.min_zt_count} onChange={(e) => setAuctionParams({ ...auctionParams, min_zt_count: Number(e.target.value) })} />
            <p className="mt-1 text-[11px] text-muted-foreground">近30日最少涨停次数（默认2）</p>
          </div>
          <div>
            <Input label="返回候选股数量" type="number" value={auctionParams.top_n} onChange={(e) => setAuctionParams({ ...auctionParams, top_n: Number(e.target.value) })} />
            <p className="mt-1 text-[11px] text-muted-foreground">竞价预案 TOP N（默认50）</p>
          </div>
        </div>
        <Button onClick={handleSaveAuctionParams} disabled={auctionLoading}>
          {auctionLoading ? "保存中..." : "保存参数"}
        </Button>
      </GlassCard>

      {/* 复盘报告参数 */}
      <GlassCard className="mt-4">
        <SectionHeader title="复盘报告参数" icon={<Flame className="h-4 w-4 text-primary" />} />
        <p className="mb-4 text-xs text-muted-foreground">
          调整复盘报告中展示的涨停股和竞价回顾数量。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <Input label="涨停股展示上限" type="number" value={reviewParams.max_zt_stocks} onChange={(e) => setReviewParams({ ...reviewParams, max_zt_stocks: Number(e.target.value) })} />
            <p className="mt-1 text-[11px] text-muted-foreground">涨停股明细展示上限（默认100）</p>
          </div>
          <div>
            <Input label="竞价回顾数量" type="number" value={reviewParams.auction_top_n} onChange={(e) => setReviewParams({ ...reviewParams, auction_top_n: Number(e.target.value) })} />
            <p className="mt-1 text-[11px] text-muted-foreground">复盘报告中竞价回顾 TOP N（默认20）</p>
          </div>
        </div>
        <Button onClick={handleSaveReviewParams} disabled={reviewLoading}>
          {reviewLoading ? "保存中..." : "保存参数"}
        </Button>
      </GlassCard>
    </div>
  );
}
