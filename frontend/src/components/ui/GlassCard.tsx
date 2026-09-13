import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  onClick?: () => void;
  tier?: "primary" | "sub";  // 视觉层次: primary=主卡(大字+glow+每页仅1,承主问题答案) | sub=辅信息(无卡边,内联) | 默认=次卡(≤3)
}

// 玻璃卡：半透明填充 + 发丝边框 + 柔投影 + 顶部内高光（科技玻璃暖橙风的基础容器）。
// tier 三档治信息过重(每页1 primary+≤3 次卡+辅 sub,非全平铺):primary=glass-glow+ring 主卡 / 默认=次卡 / sub=glass-sub 辅信息。
export function GlassCard({ children, className, glow, onClick, tier }: Props) {
  return (
    <div
      onClick={onClick}
      className={cn(
        tier === "sub" ? "glass-sub px-4 py-3" : "glass p-5",
        (tier === "primary" || glow) && "glass-glow",
        tier === "primary" && "ring-1 ring-primary/20",
        onClick && "cursor-pointer transition-transform hover:-translate-y-0.5",
        className,
      )}
    >
      {children}
    </div>
  );
}
