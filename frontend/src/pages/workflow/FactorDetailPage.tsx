// S066 §11.5 因子详情子页——定义/公式/分布/相关性/分位胜率 + 面包屑导航。
// spec §11.5：每个因子有独立子页：定义+计算公式+当前值+历史分布+相关性 r+分位胜率。
// 面包屑：首页 > 盘前 > 策略组 > 因子名。
import { Link, useParams } from "react-router-dom";
import { ChevronRight, ArrowLeft, Info } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Badge } from "@/components/ui/Badge";

// 因子全景表（来自 factor-catalog.md，74 条因子精选 P0/P1）
interface FactorEntry {
  id: number;
  name: string;
  direction: string;     // 利好/利空/中性
  evidence: string;      // 已验证/理论充分/经验共识/传说待验
  data_source: string;
  system_status: string;
  priority: string;       // P0/P1/P2/不做
}

const FACTOR_CATALOG: FactorEntry[] = [
  // 一、量价类
  { id: 1, name: "封板时间早（≤10:30）", direction: "利好", evidence: "已验证 r=+0.18", data_source: "ZTPoolItem.seal_time", system_status: "已接入 seal_rate 因子", priority: "P0" },
  { id: 2, name: "缩量涨停（量比<1）", direction: "利好", evidence: "已验证 78.6%>68.8%", data_source: "kline vol_ratio", system_status: "已验证不过滤", priority: "P0" },
  { id: 3, name: "换手 5-20%", direction: "中性", evidence: "理论充分", data_source: "tencent_quote turnover_pct", system_status: "已接入诊断卡", priority: "P0" },
  { id: 4, name: "换手 >20%", direction: "利空", evidence: "经验共识", data_source: "同上", system_status: "已接入 fail", priority: "P0" },
  { id: 6, name: "成交额小（<5亿）", direction: "利好", evidence: "已验证（小盘更易封板）", data_source: "kline amount", system_status: "已验证不过滤", priority: "P0" },
  { id: 7, name: "量比≥1.5", direction: "利空", evidence: "已验证（降低胜率）", data_source: "kline vol_ratio", system_status: "已验证不过滤", priority: "P0" },
  { id: 9, name: "封单量>流通市值1%", direction: "利好", evidence: "理论充分", data_source: "ZTPoolItem seal_amount", system_status: "已接入八项标准⑥", priority: "P0" },
  { id: 10, name: "开板次数≤1", direction: "利好", evidence: "理论充分", data_source: "ZTPoolItem broken_count", system_status: "已接入八项标准⑤", priority: "P0" },
  // 二、资金面
  { id: 11, name: "主力净流入", direction: "利好", evidence: "理论充分", data_source: "fund_flow main_net_inflow", system_status: "已接入", priority: "P0" },
  { id: 13, name: "游资接力型席位在场", direction: "利好", evidence: "理论充分", data_source: "龙虎榜 OPERATEDEPT_NAME", system_status: "S066§9 席位画像", priority: "P1" },
  { id: 14, name: "游资一日游席位在场", direction: "利空", evidence: "理论充分", data_source: "同上", system_status: "S066§9 席位画像", priority: "P1" },
  { id: 15, name: "机构净买入", direction: "利好", evidence: "理论充分", data_source: "dragon_tiger_inst_net", system_status: "已接入", priority: "P0" },
  { id: 18, name: "板块资金净流入", direction: "利好", evidence: "理论充分", data_source: "sector_flow", system_status: "已接入当日快照", priority: "P0" },
  // 三、形态类
  { id: 21, name: "均线多头排列（MA5>MA10>MA20）", direction: "利好", evidence: "理论充分", data_source: "kline close 计算", system_status: "已接入但常 None", priority: "P1" },
  { id: 24, name: "横盘突破", direction: "利好", evidence: "理论充分", data_source: "kline N 日振幅", system_status: "platform_breakout 战法", priority: "P1" },
  { id: 25, name: "回调至 MA5", direction: "利好", evidence: "理论充分", data_source: "price vs MA5", system_status: "low_absorption 战法", priority: "P1" },
  // 四、日历类
  { id: 29, name: "周四逆势涨停", direction: "利好", evidence: "已验证 88.9%", data_source: "交易日 + 大盘涨跌", system_status: "S066§6 calendar_factor", priority: "P0" },
  { id: 30, name: "周五信号日", direction: "利空", evidence: "已验证 63.6%", data_source: "交易日 weekday", system_status: "S066§6 ×0.7", priority: "P0" },
  { id: 31, name: "节前最后交易日", direction: "利空", evidence: "已验证 60%", data_source: "holidays.json", system_status: "S066§6 ×0.3", priority: "P0" },
];

// Phase 0b 回归结果（n=6079，CI 排除 0 为显著）
const FACTOR_SIGNIFICANCE: Record<string, { r: number; ci: [number, number]; p: number; significant: boolean }> = {
  "封板率": { r: 0.1071, ci: [0.0667, 0.1471], p: 0.0, significant: true },
  "炸板后溢价": { r: 0.1873, ci: [0.1478, 0.2263], p: 0.0, significant: true },
  "红盘率": { r: 0.0295, ci: [0.0044, 0.0546], p: 0.021, significant: true },
  "连板率": { r: 0.0122, ci: [-0.013, 0.0373], p: 0.343, significant: false },
  "涨停频次": { r: 0.0186, ci: [-0.0065, 0.0437], p: 0.147, significant: false },
  "总分": { r: 0.0449, ci: [0.0198, 0.07], p: 0.000456, significant: true },
};

const directionBadge = (dir: string): "success" | "danger" | "info" => {
  if (dir === "利好") return "success";
  if (dir === "利空") return "danger";
  return "info";
};

const priorityBadge = (p: string): "primary" | "info" | "default" => {
  if (p === "P0") return "primary";
  if (p === "P1") return "info";
  return "default";
};

export function FactorDetailPage() {
  const { factorId } = useParams<{ factorId: string }>();
  const id = parseInt(factorId ?? "0", 10);
  const factor = FACTOR_CATALOG.find((f) => f.id === id);

  return (
    <div className="space-y-4">
      {/* 面包屑：首页 > 盘前 > 因子详情 */}
      <nav className="flex items-center gap-1 text-sm text-muted-foreground">
        <Link to="/workflow/pre-market" className="hover:text-foreground">盘前</Link>
        <ChevronRight className="h-3 w-3" />
        <Link to="/workflow/pre-market" className="hover:text-foreground">策略组</Link>
        <ChevronRight className="h-3 w-3" />
        <span className="text-foreground">{factor?.name ?? `因子 #${id}`}</span>
      </nav>

      <Link to="/workflow/pre-market" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-primary">
        <ArrowLeft className="h-4 w-4" /> 返回盘前
      </Link>

      {factor ? (
        <>
          {/* 因子定义 */}
          <GlassCard className="p-4">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-lg font-bold">{factor.name}</h2>
                <p className="mt-1 text-xs text-muted-foreground">因子 #{factor.id} · {factor.priority}</p>
              </div>
              <div className="flex gap-2">
                <Badge variant={directionBadge(factor.direction)}>{factor.direction}</Badge>
                <Badge variant={priorityBadge(factor.priority)}>{factor.priority}</Badge>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">证据等级</p>
                <p className="font-medium">{factor.evidence}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">数据源</p>
                <p className="font-mono text-xs">{factor.data_source}</p>
              </div>
              <div className="col-span-2">
                <p className="text-xs text-muted-foreground">系统状态</p>
                <p className="font-medium">{factor.system_status}</p>
              </div>
            </div>
          </GlassCard>

          {/* Phase 0b 回归结果（如有） */}
          {FACTOR_SIGNIFICANCE[factor.name.split("（")[0]] && (
            <GlassCard className="p-4">
              <SectionHeader title="Phase 0b 全样本回归（n=6079）" subtitle="Pearson r + 95% CI + p 值" />
              {(() => {
                const sig = FACTOR_SIGNIFICANCE[factor.name.split("（")[0]];
                return (
                  <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div>
                      <p className="text-xs text-muted-foreground">Pearson r</p>
                      <p className="font-mono text-lg font-bold">{sig.r > 0 ? "+" : ""}{sig.r}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">95% CI</p>
                      <p className="font-mono text-sm">[{sig.ci[0]}, {sig.ci[1]}]</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">p 值</p>
                      <p className="font-mono text-sm">{sig.p}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">显著性</p>
                      <Badge variant={sig.significant ? "success" : "warning"}>
                        {sig.significant ? "显著（CI 排除 0）" : "不显著"}
                      </Badge>
                    </div>
                  </div>
                );
              })()}
            </GlassCard>
          )}

          {/* 因子说明 */}
          <GlassCard className="p-4">
            <div className="flex items-start gap-2">
              <Info className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
              <div className="text-sm text-muted-foreground space-y-2">
                <p>
                  <span className="font-medium text-foreground">方向：</span>
                  {factor.direction === "利好" && "该因子出现时，次日收益倾向为正，进入策略分加权。"}
                  {factor.direction === "利空" && "该因子出现时，次日收益倾向为负，作为风险标注或降权。"}
                  {factor.direction === "中性" && "该因子为中性参考，不直接参与策略分计算。"}
                </p>
                <p>
                  <span className="font-medium text-foreground">证据：</span>
                  {factor.evidence}
                </p>
                {factor.priority === "P0" && (
                  <p>本因子数据已有，改动小，本 spec 已实现。</p>
                )}
                {factor.priority === "P1" && (
                  <p>本因子需少量新数据或计算，本 spec 实现中。</p>
                )}
              </div>
            </div>
          </GlassCard>
        </>
      ) : (
        <GlassCard className="p-8 text-center">
          <p className="text-muted-foreground">因子 #{id} 未找到</p>
          <Link to="/workflow/pre-market" className="mt-2 inline-block text-sm text-primary hover:underline">
            返回盘前
          </Link>
        </GlassCard>
      )}
    </div>
  );
}
