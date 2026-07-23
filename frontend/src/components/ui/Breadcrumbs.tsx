import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { ChevronRight } from "lucide-react";

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

interface BreadcrumbsProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumbs({ items, className }: BreadcrumbsProps) {
  return (
    <nav className={cn("flex items-center gap-1 text-xs text-muted-foreground", className)}>
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        return (
          <span key={index} className="flex items-center gap-1">
            {index > 0 && <ChevronRight className="h-3 w-3" />}
            {item.to && !isLast ? (
              <Link to={item.to} className="hover:text-foreground transition-colors">
                {item.label}
              </Link>
            ) : (
              <span className={cn(isLast ? "text-foreground font-medium" : "")}>{item.label}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
