import { createContext, useContext } from "react";

interface BreadcrumbItem {
  label: string;
  to?: string;
}

interface BreadcrumbContextValue {
  items: BreadcrumbItem[];
  setItems: (items: BreadcrumbItem[]) => void;
}

export const BreadcrumbContext = createContext<BreadcrumbContextValue>({
  items: [],
  setItems: () => {},
});

export function useBreadcrumbs() {
  return useContext(BreadcrumbContext);
}
