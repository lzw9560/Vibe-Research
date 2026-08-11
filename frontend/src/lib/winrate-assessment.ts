// S054 R8：行为研判派生纯函数——三页共用（BehaviorLoop / PreMarketBriefing / PostMarketReview）。
// 从 BehaviorLoop._deriveAssessmentTips 原样抽取，单一事实源，避免三处各自派生导致建议不一致。
// 弱合规定位：方向建议数据驱动非臆造，任一桶 n<5 明示样本不足。
import type { ShadowComparison } from "@/lib/api/types";

export function deriveAssessmentTips(data: ShadowComparison): string[] {
  const tips: string[] = [];
  const { follow, feeling, missed, independence, sufficient } = data;

  // follow vs feeling 胜率对比（核心研判）
  if (follow.n > 0 && feeling.n > 0 && follow.win_rate != null && feeling.win_rate != null) {
    const diff = follow.win_rate - feeling.win_rate;
    if (diff > 0.15) {
      tips.push(
        `跟系统单胜率 ${(follow.win_rate * 100).toFixed(1)}% 显著高于感觉单 ${(feeling.win_rate * 100).toFixed(1)}%，` +
        `可考虑多跟系统候选/战法信号。`,
      );
    } else if (diff < -0.15) {
      tips.push(
        `感觉单胜率 ${(feeling.win_rate * 100).toFixed(1)}% 反而高于跟系统单 ${(follow.win_rate * 100).toFixed(1)}%，` +
        `当前系统信号质量待校准（W2 校准轨），暂可倾向自主判断。`,
      );
    } else {
      tips.push(
        `跟系统单与感觉单胜率接近（差 ${(Math.abs(diff) * 100).toFixed(1)}pp），` +
        `两者表现相当，独立判断能力稳健。`,
      );
    }
  }

  // 一致率研判
  if (independence.agreement_rate != null) {
    const ar = independence.agreement_rate;
    if (ar >= 0.7) {
      tips.push(`一致率 ${(ar * 100).toFixed(1)}% 偏高，对系统信号依赖较大，注意保留独立判断空间。`);
    } else if (ar <= 0.3 && (follow.n + feeling.n) > 0) {
      tips.push(`一致率 ${(ar * 100).toFixed(1)}% 偏低，自主决策占比大，可关注 missed 桶看漏掉的候选。`);
    }
  }

  // missed 影子收益研判
  if (missed.n > 0 && missed.win_rate != null) {
    if (missed.win_rate > 0.5 && missed.avg_return != null && missed.avg_return > 0) {
      tips.push(
        `漏掉的候选影子胜率 ${(missed.win_rate * 100).toFixed(1)}%、均收益 ${missed.avg_return.toFixed(2)}%，` +
        `系统建议质量不错，可考虑多采纳候选池标的。`,
      );
    } else if (missed.win_rate < 0.3 && missed.n >= 5) {
      tips.push(
        `漏掉的候选影子胜率仅 ${(missed.win_rate * 100).toFixed(1)}%，不跟可能是对的——` +
        `说明你对候选的自主筛选有超额判断力。`,
      );
    }
  }

  // 样本不足时压低研判权重
  if (!sufficient) {
    tips.push("当前样本不足（三桶任一 <5），以上研判仅供参考，建议积累到 ≥4 周再做强决策。");
  }

  // 全空兜底
  if (follow.n === 0 && feeling.n === 0 && missed.n === 0) {
    tips.push("窗口内无已结算交易也无候选快照，暂无行为数据可研判。结算一笔交易或等待盘前采集后查看。");
  }

  return tips;
}
