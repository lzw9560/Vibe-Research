import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface BadgeProps {
  children: ReactNode;
  variant?: "default" | "primary" | "success" | "danger" | "warning" | "info";
  className?: string;
}

export function Badge({ children, variant = "default", className }: BadgeProps) {
  const variants = {
    default: "rounded-full bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground",
    primary: "rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary",
    success: "rounded-full bg-success/10 px-2 py-0.5 text-xs text-success",
    danger: "rounded-full bg-destructive/10 px-2 py-0.5 text-xs text-destructive",
    warning: "rounded-full bg-yellow-400/10 px-2 py-0.5 text-xs text-yellow-400",
    info: "rounded-full bg-blue-400/10 px-2 py-0.5 text-xs text-blue-400",
  };

  return (
    <span className={cn("inline-flex items-center", variants[variant], className)}>
      {children}
    </span>
  );
}
