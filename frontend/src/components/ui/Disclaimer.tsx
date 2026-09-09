import { Info } from "lucide-react";

// S175 R7（弱合规，CLAUDE.md §1.1）：谋士 posture 提醒——系统模拟盘跟踪+可给方向性研判，
// 真盘由用户决策。保留"历史统计特征，市场有风险"轻量提醒，删旧"不推荐/不给买卖时机"硬免责墙。
export function Disclaimer({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <p className="text-[11px] leading-relaxed text-muted-foreground/70">
        模拟盘跟踪·真盘你定。历史统计特征，市场有风险。
      </p>
    );
  }
  return (
    <div className="mt-8 flex items-start gap-2 rounded-lg border border-border/60 bg-muted/20 p-3 text-xs leading-relaxed text-muted-foreground">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>
        Vibe-Research 是私人投研助理：系统跑<b className="text-foreground">模拟盘跟踪</b>（纸面 PnL 含成本/滑点，不碰用户真钱）+ 给方向性研判与买卖时机建议，榜单（连板股/成交额等）均为<b className="text-foreground">客观公开数据</b>。
        <b className="text-foreground">真盘交易由你自己决策执行</b>。历史统计特征，市场有风险，请自行核实并独立决策。
      </span>
    </div>
  );
}
