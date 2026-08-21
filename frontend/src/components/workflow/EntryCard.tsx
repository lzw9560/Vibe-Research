// S092：可复用链接卡片——从 S087 Workflow.tsx 抽出，供前瞻+复盘 Tab 内嵌使用。
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { GlassCard } from "../ui/GlassCard";

interface Props {
  to: string;
  title: string;
  subtitle: string;
  icon?: React.ComponentType<{ className?: string }>;
  date?: string;
}

export function EntryCard({ to, title, subtitle, icon: Icon, date }: Props) {
  return (
    <Link to={date ? `${to}?date=${date}` : to} className="block">
      <GlassCard className="p-4 transition-all hover:ring-2 hover:ring-primary/30">
        <div className="flex items-center gap-3">
          {Icon && (
            <div className="rounded-xl border border-primary/30 bg-primary/10 p-2.5">
              <Icon className="h-5 w-5 text-primary" />
            </div>
          )}
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold">{title}</h3>
              <ChevronRight className="h-4 w-4 text-muted-foreground/50" />
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground/70">{subtitle}</p>
          </div>
        </div>
      </GlassCard>
    </Link>
  );
}
