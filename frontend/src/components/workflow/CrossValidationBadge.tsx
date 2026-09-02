// S093 T13 + S146：交叉验证徽章组件（spec R4④ + AC9）。
// breakout 降级研究后 CV 重定向涨停叉内（final∩scored）：
// 双重确认（漏斗终选∩战法命中）→ 绿色徽章
// 仅漏斗终选 → 灰色徽章
// 仅战法命中 → 灰色徽章
// 用项目既有 Badge 组件（对齐 components/workflow/ 现有 badge 风格）。

import { Badge } from "@/components/ui/Badge";
import type { CrossValidationGroup } from "@/lib/query/useCrossValidation";

interface CrossValidationBadgeProps {
  group: CrossValidationGroup;
}

const GROUP_CONFIG: Record<
  CrossValidationGroup,
  { variant: "success" | "default"; label: string }
> = {
  dual: { variant: "success", label: "双重确认" },
  funnelOnly: { variant: "default", label: "仅漏斗终选" },
  strategyOnly: { variant: "default", label: "仅战法命中" },
};

export function CrossValidationBadge({ group }: CrossValidationBadgeProps) {
  const config = GROUP_CONFIG[group];
  return <Badge variant={config.variant}>{config.label}</Badge>;
}
