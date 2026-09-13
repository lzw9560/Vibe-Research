// 项目架构图页（iframe embed archify standalone HTML）
export function ArchitecturePage() {
  return (
    <div style={{ width: "100%", height: "calc(100vh - 120px)", padding: 0 }}>
      <iframe
        src="/vibe-architecture.html"
        style={{
          width: "100%",
          height: "100%",
          border: "1px solid var(--border-color, #e5e7eb)",
          borderRadius: 8,
        }}
        title="Vibe-Research 项目架构图（architecture）"
      />
    </div>
  );
}
