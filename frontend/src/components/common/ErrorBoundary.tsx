import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";

interface Props { children: ReactNode; fallback?: ReactNode; }
interface State { hasError: boolean; error?: Error; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div className="m-4 flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{this.state.error?.message || "页面加载出错（可能是懒加载分块 404 或网络中断）"}</span>
          </div>
          <div className="flex gap-3">
            <button onClick={() => window.location.reload()} className="rounded border border-border px-3 py-1 text-xs hover:bg-muted/40">重试</button>
            <Link to="/today" className="rounded border border-border px-3 py-1 text-xs hover:bg-muted/40">回首页</Link>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
