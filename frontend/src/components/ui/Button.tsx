import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "ghost" | "icon" | "danger";
  size?: "sm" | "md" | "lg";
  children: ReactNode;
}

export function Button({
  variant = "primary",
  size = "md",
  children,
  className,
  ...props
}: ButtonProps) {
  const base = "inline-flex items-center justify-center gap-1.5 font-medium transition-all focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-2 focus:ring-offset-background disabled:opacity-50 disabled:pointer-events-none";

  const variants = {
    primary: "rounded-lg bg-primary/15 text-primary shadow-glow hover:bg-primary/25",
    ghost: "rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/20",
    icon: "rounded-lg p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted/20",
    danger: "rounded-lg bg-destructive/15 text-destructive hover:bg-destructive/25",
  };

  const sizes = {
    sm: "px-3 py-1.5 text-xs",
    md: "px-4 py-2 text-sm",
    lg: "px-5 py-2.5 text-base",
  };

  return (
    <button
      className={cn(base, variants[variant], sizes[size], className)}
      {...props}
    >
      {children}
    </button>
  );
}
