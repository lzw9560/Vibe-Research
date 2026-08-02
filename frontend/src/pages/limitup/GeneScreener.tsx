import { useState, useEffect, useCallback } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GeneFilterForm } from "./components/GeneFilterForm";
import { GeneResultTable } from "./components/GeneResultTable";
import { Disclaimer } from "@/components/ui/Disclaimer";

export function GeneScreener() {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  const loadData = useCallback(() => {
    setLoading(true);
    setTimeout(() => {
      setData([]);
      setLoading(false);
    }, 500);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleToggle = (code: string) => {
    setExpandedCode((prev) => prev === code ? null : code);
  };

  return (
    <div>
      <PageHeader title="基因筛选" subtitle="Gene Screener" />
      
      <GeneFilterForm onSearch={loadData} />
      
      <GeneResultTable 
        data={data} 
        loading={loading}
        expandedCode={expandedCode}
        onToggle={handleToggle}
      />
      
      <Disclaimer />
    </div>
  );
}

export default GeneScreener;
