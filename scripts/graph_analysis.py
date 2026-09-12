#!/usr/bin/env python3
"""知识图谱图算法分析——社区发现/中心性/路径分析。

从 vault markdown 的 [[]] 链接建图，纯标准库实现：
  - find_hubs: 入度中心性（hub 节点）
  - find_communities: 标签传播社区发现
  - find_bridges: 桥节点（跨社区连接者）
  - shortest_path: BFS 最短路径

输出 JSON 供报告生成，亦可直接跑生成 markdown 报告。
"""
import re
import sys
import json
from pathlib import Path
from collections import defaultdict, Counter, deque

VAULT = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing")
REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "graph-analysis-report.md"
JSON_PATH = REPO_ROOT / "docs" / "graph-analysis.json"

# 跳过模板与 index
SKIP_NAMES = {"index.md"}
SKIP_SUBSTR = ("templates",)

LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)


def _skip_file(f: Path) -> bool:
    if f.name in SKIP_NAMES:
        return True
    if any(s in str(f) for s in SKIP_SUBSTR):
        return True
    return False


def build_graph():
    """从 vault markdown 的 [[]] 链接建图。

    Returns:
        (nodes, edges): nodes=set[str], edges=list[(source, target)]
    """
    nodes = set()
    edges = []

    for f in VAULT.rglob("*.md"):
        if _skip_file(f):
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue
        # 剥 frontmatter
        content = FRONTMATTER_RE.sub("", content, count=1)

        source = str(f.relative_to(VAULT)).replace(".md", "")
        nodes.add(source)

        for m in LINK_RE.finditer(content):
            target = m.group(1).split("|")[0].strip()
            # 跳过外链/锚点/空
            if not target or target.startswith("http") or target.startswith("#"):
                continue
            # 跳过文件夹链接（如 stocks/）—— 保留，但通常这类无对应文件
            edges.append((source, target))
            nodes.add(target)

    return nodes, edges


def graph_stats(nodes, edges):
    """图谱基础统计。"""
    n = len(nodes)
    m = len(edges)
    # 无向去重后边数
    undirected = set()
    for s, t in edges:
        if s == t:
            continue
        undirected.add(tuple(sorted((s, t))))
    m_undirected = len(undirected)
    # 密度 = 2E / (V*(V-1))
    density = (2 * m_undirected) / (n * (n - 1)) if n > 1 else 0.0
    return {
        "nodes": n,
        "edges_directed": m,
        "edges_undirected": m_undirected,
        "density": round(density, 6),
    }


def find_hubs(edges, top_n=20):
    """找 hub 节点（入边最多的实体，PageRank 的简化代理）。"""
    in_degree = Counter()
    for _, target in edges:
        in_degree[target] += 1
    return in_degree.most_common(top_n)


def _build_adj_undirected(edges):
    adj = defaultdict(set)
    for s, t in edges:
        if s == t:
            continue
        adj[s].add(t)
        adj[t].add(s)
    return adj


def find_communities(nodes, edges, iterations=15):
    """标签传播社区发现（LPA）。

    每轮按固定顺序（sorted）更新每个节点标签为邻居中出现最多的标签。
    """
    adj = _build_adj_undirected(edges)
    # 只对有邻居的节点跑
    active_nodes = sorted(n for n in nodes if adj.get(n))
    labels = {n: i for i, n in enumerate(active_nodes)}
    # 孤立节点保留自身标签（已在 nodes 里但不在 active_nodes）

    for _ in range(iterations):
        changed = False
        for node in active_nodes:
            neighbor_labels = Counter(labels[nb] for nb in adj[node] if nb in labels)
            if neighbor_labels:
                # most_common 平局取第一个，按 Counter 内部顺序（插入序）
                top_label, _ = neighbor_labels.most_common(1)[0]
                if labels[node] != top_label:
                    labels[node] = top_label
                    changed = True
        if not changed:
            break

    communities = defaultdict(list)
    for node, label in labels.items():
        communities[label].append(node)
    return dict(communities)


def find_bridges(nodes, edges, min_communities=3):
    """找桥节点——邻居分布在 >= min_communities 个社区的节点。"""
    communities = find_communities(nodes, edges)
    node_community = {}
    for label, members in communities.items():
        for m in members:
            node_community[m] = label

    adj = _build_adj_undirected(edges)
    bridges = []
    for node in nodes:
        neighbor_communities = set()
        for neighbor in adj.get(node, []):
            if neighbor in node_community:
                neighbor_communities.add(node_community[neighbor])
        if len(neighbor_communities) >= min_communities:
            bridges.append((node, len(neighbor_communities), len(adj.get(node, []))))

    return sorted(bridges, key=lambda x: (-x[1], -x[2]))


def shortest_path(nodes, edges, source, target):
    """BFS 最短路径。"""
    adj = defaultdict(list)
    for s, t in edges:
        if s == t:
            continue
        adj[s].append(t)
        adj[t].append(s)

    if source not in adj or target not in adj:
        return None

    visited = {source}
    queue = deque([(source, [source])])
    while queue:
        node, path = queue.popleft()
        if node == target:
            return path
        for neighbor in adj[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    return None


def community_summary(communities):
    """社区摘要——每个社区的大小 + top 成员（按入度）。"""
    sizes = [(label, len(members)) for label, members in communities.items()]
    sizes.sort(key=lambda x: -x[1])
    return sizes


def build_report(nodes, edges, stats, hubs, communities, bridges):
    """生成 markdown 分析报告。"""
    lines = []
    lines.append("# 知识图谱图算法分析报告")
    lines.append("")
    lines.append(f"> 自动生成于 `graph_analysis.py`。数据源：`{VAULT}`")
    lines.append("")

    # 统计
    lines.append("## 1. 图谱统计")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 节点数 | {stats['nodes']} |")
    lines.append(f"| 有向边数 | {stats['edges_directed']} |")
    lines.append(f"| 无向边数（去重） | {stats['edges_undirected']} |")
    lines.append(f"| 密度 | {stats['density']} |")
    lines.append("")

    # Hub
    lines.append("## 2. Top 20 Hub 节点（入度中心性）")
    lines.append("")
    lines.append("> 入边最多 = 被引用最多 = 知识图谱的中心实体。")
    lines.append("")
    lines.append("| 排名 | 实体 | 入度 |")
    lines.append("|---|---|---|")
    for i, (node, deg) in enumerate(hubs, 1):
        lines.append(f"| {i} | `{node}` | {deg} |")
    lines.append("")

    # 社区
    lines.append("## 3. 社区发现（标签传播 LPA）")
    lines.append("")
    sizes = community_summary(communities)
    lines.append(f"共发现 **{len(communities)}** 个社区（含孤立）。Top 10 社区：")
    lines.append("")
    lines.append("| 社区 ID | 成员数 | Top 5 成员 |")
    lines.append("|---|---|---|")
    # 预算每个社区的入度 top 成员
    in_deg = Counter(t for _, t in edges)
    for i, (label, size) in enumerate(sizes[:10]):
        members = communities[label]
        top_members = sorted(members, key=lambda n: -in_deg.get(n, 0))[:5]
        top_str = " ".join(f"`{m}`" for m in top_members)
        lines.append(f"| {label} | {size} | {top_str} |")
    lines.append("")

    # 桥节点
    lines.append("## 4. 桥节点（跨社区连接者）")
    lines.append("")
    lines.append("> 邻居分布在 >=3 个社区的节点——信息在不同子图间流动的枢纽。")
    lines.append("")
    lines.append("| 实体 | 跨社区数 | 总度数 |")
    lines.append("|---|---|---|")
    for node, nc, deg in bridges[:20]:
        lines.append(f"| `{node}` | {nc} | {deg} |")
    lines.append("")

    # 示例路径
    lines.append("## 5. 示例最短路径")
    lines.append("")
    sample_pairs = [
        ("stocks/600519", "specs/S007"),
        ("stocks/000001", "industries/食品饮料"),
        ("events/2026-09-07-涨停池", "strategies/dragon_head"),
    ]
    found_any = False
    for src, tgt in sample_pairs:
        path = shortest_path(nodes, edges, src, tgt)
        if path:
            found_any = True
            lines.append(f"- `{src}` → `{tgt}`：{' → '.join(f'`{p}`' for p in path)}（{len(path)-1} 跳）")
        else:
            lines.append(f"- `{src}` → `{tgt}`：无路径（不连通）")
    if not found_any:
        lines.append("")
        lines.append("> 注：示例对均为无路径，可能因实体未在图谱中或处于不同连通分量。")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 方法说明")
    lines.append("")
    lines.append("- **建图**：扫描 vault 内所有 `.md`（排除 templates/index），解析正文 `[[]]` 双链为有向边，剥去 frontmatter 避免误解析。")
    lines.append("- **Hub（入度中心性）**：`in_degree` 最高的节点，被引用最多。")
    lines.append("- **社区发现（LPA）**：标签传播算法，15 轮迭代或收敛即停。简化版，单机标准库。")
    lines.append("- **桥节点**：邻居分布在 >=3 个社区的节点，度量跨子图连接能力。")
    lines.append("- **最短路径**：BFS。")
    lines.append("")

    return "\n".join(lines)


def main():
    if not VAULT.exists():
        print(f"ERROR: vault not found: {VAULT}", file=sys.stderr)
        sys.exit(1)

    print(f"Building graph from {VAULT} ...")
    nodes, edges = build_graph()
    print(f"  nodes={len(nodes)} edges={len(edges)}")

    stats = graph_stats(nodes, edges)
    print(f"  stats={stats}")

    print("Finding hubs ...")
    hubs = find_hubs(edges, top_n=20)

    print("Finding communities (LPA) ...")
    communities = find_communities(nodes, edges)
    print(f"  communities={len(communities)}")

    print("Finding bridges ...")
    bridges = find_bridges(nodes, edges, min_communities=3)
    print(f"  bridges={len(bridges)}")

    # JSON dump 供其他脚本消费
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "stats": stats,
            "hubs": [{"node": n, "in_degree": d} for n, d in hubs],
            "communities": [{"id": k, "size": len(v), "members": v} for k, v in communities.items()],
            "bridges": [{"node": n, "cross_communities": nc, "degree": d} for n, nc, d in bridges],
        }, f, ensure_ascii=False, indent=2)
    print(f"  JSON -> {JSON_PATH}")

    print("Building report ...")
    report = build_report(nodes, edges, stats, hubs, communities, bridges)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"  report -> {REPORT_PATH}")

    # 摘要打印
    print("\n=== Summary ===")
    print(f"nodes={stats['nodes']} edges_directed={stats['edges_directed']} density={stats['density']}")
    print("Top 5 hubs:")
    for n, d in hubs[:5]:
        print(f"  {n}: in_degree={d}")


if __name__ == "__main__":
    main()
