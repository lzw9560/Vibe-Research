import { type ReactNode } from "react";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { GlassCard } from "./GlassCard";
import {
  Skeleton,
  SkeletonCard,
  SkeletonTable,
  SkeletonMetrics,
} from "./Skeleton";

/**
 * S014 安全地基件：统一三态契约（Loading / Empty / Error）。
 *
 * 现状分裂（grep Skeleton/Loader2/pending 共 190 处 / 37 文件）：
 *   - Skeleton 组件已存在（components/ui/Skeleton.tsx），但只覆盖表格/卡片级
 *   - Loader2 散落 17+ 处作 ad-hoc spinner（按钮内 loading、全屏 loading）
 *   - EmptyState 已存在（24 行），简单 icon+title+desc+action
 *   - ErrorState / PageSkeleton 缺失——本文件补齐
 *
 * 本组件只新建、不迁移现有用法（零回归风险）。后续 R5 迁移各页时统一从
 *   `import { LoadingState, EmptyState, ErrorState, PageSkeleton } from "@/components/ui/State"`
 * 引入。
 *
 * 设计契约见 specs/S014-前端UI重设计/plan.md §4。
 */

// ─── EmptyState ──────────────────────────────────────────────────────────────
// 复用已有 EmptyState 契约（components/ui/EmptyState.tsx），在此 re-export
// 作为三态统一入口，避免后续迁移时改两条 import 路径。
export { EmptyState } from "./EmptyState";

// ─── LoadingState ─────────────────────────────────────────────────────────────
interface LoadingStateProps {
  /** 区块形状；默认 "card" 走 SkeletonCard 节奏。 */
  variant?: "card" | "table" | "metrics" | "inline";
  /** variant=table 时的行数；variant=metrics 时忽略（固定 4 卡）。 */
  rows?: number;
  /** variant=table 时的列数。 */
  columns?: number;
  /** variant=metrics 时的卡片数。 */
  count?: number;
  /** inline 模式：一个紧凑的行内 spinner（替代散落的 Loader2 文字 spinner）。 */
  label?: string;
  className?: string;
  children?: ReactNode;
}

/**
 * 页面/区块级加载态。统一替代各页手写的 `<Loader2 className="h-5 w-5 animate-spin" />`
 * 全屏 loading（如 StockDeep:527、GeneScreener:219、LimitUpStrategy:205）。
 *
 * - variant="card" → SkeletonCard（GlassCard 内多行 shimmer）
 * - variant="table" → SkeletonTable
 * - variant="metrics" → SkeletonMetrics
 * - variant="inline" → 行内 spinner + label（按钮/小区域 loading 专用）
 */
export function LoadingState({
  variant = "card",
  rows = 5,
  columns = 4,
  count = 4,
  label,
  className,
  children,
}: LoadingStateProps) {
  if (variant === "inline") {
    return (
      <span className={cn("inline-flex items-center gap-2 text-xs text-muted-foreground", className)}>
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        {label && <span>{label}</span>}
        {children}
      </span>
    );
  }

  // 复用已有 Skeleton 复合组件，保证视觉一致、不引入第二套 shimmer 样式。
  // 此处延迟 require 避免循环依赖——实际三个复合组件已在 Skeleton.tsx 顶层导出。
  if (variant === "table") {
    return <SkeletonTable rows={rows} columns={columns} />;
  }
  if (variant === "metrics") {
    return <SkeletonMetrics count={count} />;
  }
  // default: card
  return <SkeletonCard />;
}

// ─── ErrorState ─────────────────────────────────────────────────────────────
interface ErrorStateProps {
  /** 错误信息（字符串或节点）。必填，防止「静默吞错」。 */
  message: ReactNode;
  /** 自定义错误图标；默认 AlertCircle。 */
  icon?: ReactNode;
  /** 重试回调；提供则渲染「重试」按钮。 */
  onRetry?: () => void;
  /** 重试按钮文案；默认「重试」。 */
  retryLabel?: string;
  /** 是否用 GlassCard 包裹（页面级）；默认 true。行内错误可传 false。 */
  card?: boolean;
  className?: string;
}

/**
 * 统一错误态：AlertCircle + 错误信息 + 可选重试按钮。
 *
 * 现状：各页错误态散落手写（StockDeep/Backtest/AskAiButton 各自 div + AlertCircle），
 * 样式不一。本组件统一 destructive 色调 + aria-live="assertive"（无障碍）。
 *
 * 不强制迁移现有用法——留待 R5 各页迁移时统一替换。
 */
export function ErrorState({
  message,
  icon,
  onRetry,
  retryLabel = "重试",
  card = true,
  className,
}: ErrorStateProps) {
  const inner = (
    <div
      role="alert"
      aria-live="assertive"
      className={cn(
        "flex flex-col items-center justify-center gap-3 py-10 text-center",
        className,
      )}
    >
      <div className="text-destructive/70">
        {icon ?? <AlertCircle className="h-7 w-7" aria-hidden="true" />}
      </div>
      <p className="max-w-md text-sm text-destructive">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-lg bg-destructive/15 px-3 py-1.5 text-sm font-medium text-destructive transition-colors hover:bg-destructive/25"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          {retryLabel}
        </button>
      )}
    </div>
  );

  if (card) return <GlassCard className="mb-6">{inner}</GlassCard>;
  return inner;
}

// ─── PageSkeleton ─────────────────────────────────────────────────────────────
interface PageSkeletonProps {
  /** 页面标题占位；默认显示一个 1/3 宽 shimmer 行模拟 PageHeader。 */
  header?: boolean;
  /** 主体区块数；默认 3。 */
  blocks?: number;
  className?: string;
}

/**
 * 整页加载骨架：模拟 PageHeader + 多个 GlassCard 区块的形状。
 * 用于路由级 Suspense fallback 或 TanStack Query 初始加载全屏态。
 *
 * 替代各页手写的 `<Loader2 className="h-8 w-8 animate-spin text-primary" />`
 * 全屏 spinner（StockDeep:527、LimitUpStrategy:205/418 等）。
 */
export function PageSkeleton({ header = true, blocks = 3, className }: PageSkeletonProps) {
  return (
    <div className={cn("space-y-6", className)}>
      {header && (
        <div className="space-y-2">
          <Skeleton variant="text" className="w-1/3 h-7" />
          <Skeleton variant="text" className="w-1/2" />
        </div>
      )}
      {Array.from({ length: blocks }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}
