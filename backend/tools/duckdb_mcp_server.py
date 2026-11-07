#!/usr/bin/env python3
"""DuckDB MCP Server — 查询 .vibe-research/ 下的 SQLite/CSV/Parquet 数据。

用 DuckDB 的 ATTACH 能力直接查询现有 SQLite DB，无需迁移数据。
支持 SQL 查询，返回 JSON 结果。

安装依赖：pip install duckdb mcp
启动：python3 backend/tools/duckdb_mcp_server.py
"""

import json
import sys
import os
from pathlib import Path

# 数据根目录：优先 VR_DATA_DIR env，否则项目根/.vibe-research（不导入 vr_paths 避免 backend 初始化链）
_proj_root = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("VR_DATA_DIR", str(_proj_root / ".vibe-research")))

try:
    import duckdb
except ImportError:
    print(json.dumps({"error": "duckdb not installed. Run: pip install duckdb"}), file=sys.stderr)
    sys.exit(1)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    # Fallback: simple stdio protocol without mcp SDK
    Server = None


def list_databases() -> list[dict]:
    """列出 .vibe-research/ 下的所有 SQLite DB。"""
    dbs = []
    for f in DATA_DIR.rglob("*.db"):
        if f.stat().st_size == 0:
            continue
        dbs.append({
            "path": str(f.relative_to(DATA_DIR)),
            "size_mb": round(f.stat().st_size / 1024 / 1024, 1),
        })
    return sorted(dbs, key=lambda x: -x["size_mb"])


def list_tables(db_path: str) -> list[str]:
    """列出 SQLite DB 的表（用 sqlite3 直接查，比 DuckDB ATTACH 更可靠）。"""
    full_path = DATA_DIR / db_path
    if not full_path.exists():
        return [f"Error: {db_path} not found"]
    try:
        import sqlite3
        con = sqlite3.connect(str(full_path))
        result = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        con.close()
        return [r[0] for r in result]
    except Exception as e:
        return [f"Error: {e}"]


def query_sql(sql: str, db_path: str = None, limit: int = 100) -> str:
    """执行 SQL 查询。SQLite DB 用 sqlite3 直查（可靠），CSV/parquet 用 DuckDB。"""
    if not db_path:
        return json.dumps({"error": "db_path required. Use list_databases to see available DBs."})
    full_path = DATA_DIR / db_path
    if not full_path.exists():
        return json.dumps({"error": f"{db_path} not found"})
    
    # SQLite DB → 用 sqlite3 直查（避免 DuckDB ATTACH 的 schema 前缀/ROWID 问题）
    if db_path.endswith('.db'):
        try:
            import sqlite3
            con = sqlite3.connect(str(full_path))
            con.row_factory = sqlite3.Row
            if "LIMIT" not in sql.upper():
                sql = f"{sql.rstrip(';')} LIMIT {limit}"
            cursor = con.execute(sql)
            columns = [d[0] for d in cursor.description]
            rows = [dict(row) for row in cursor.fetchall()]
            con.close()
            return json.dumps({"columns": columns, "row_count": len(rows), "rows": rows[:limit]}, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "sql": sql})
    
    # CSV/parquet → 用 DuckDB
    con = duckdb.connect()
    try:
        if "LIMIT" not in sql.upper():
            sql = f"{sql.rstrip(';')} LIMIT {limit}"
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
        return json.dumps({"columns": columns, "row_count": len(rows), "rows": [dict(zip(columns, row)) for row in rows[:limit]]}, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "sql": sql})
    finally:
        con.close()


def query_csv(csv_path: str, sql: str = None, limit: int = 100) -> str:
    """用 DuckDB 直接查询 CSV 文件（无需导入）。"""
    full_path = DATA_DIR / csv_path
    if not full_path.exists():
        # 也尝试绝对路径
        full_path = Path(csv_path)
        if not full_path.exists():
            return json.dumps({"error": f"{csv_path} not found"})
    
    con = duckdb.connect()
    try:
        if sql:
            # 替换表名占位符
            sql = sql.replace("{table}", f"read_csv_auto('{full_path}')")
        else:
            sql = f"SELECT * FROM read_csv_auto('{full_path}') LIMIT {limit}"
        
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
        
        return json.dumps({
            "columns": columns,
            "row_count": len(rows),
            "rows": [dict(zip(columns, row)) for row in rows[:limit]],
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
    finally:
        con.close()




def _run_mcp_server():
    """启动 MCP stdio server（仅 __main__ 时调用）。"""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool as ToolType, TextContent as TextContentType, ListToolsResult, CallToolResult
    import mcp.types as mt
    import asyncio

    async def _on_list_tools(ctx, params=None):
        return ListToolsResult(tools=[
            ToolType(name="list_databases", description="List all SQLite databases in .vibe-research/", inputSchema={"type": "object", "properties": {}}),
            ToolType(name="list_tables", description="List tables in a SQLite database", inputSchema={"type": "object", "properties": {"db_path": {"type": "string"}}, "required": ["db_path"]}),
            ToolType(name="query_sql", description="Execute SQL on a SQLite DB via DuckDB ATTACH", inputSchema={"type": "object", "properties": {"sql": {"type": "string"}, "db_path": {"type": "string"}, "limit": {"type": "integer", "default": 100}}, "required": ["sql", "db_path"]}),
            ToolType(name="query_csv", description="Query CSV directly with DuckDB", inputSchema={"type": "object", "properties": {"csv_path": {"type": "string"}, "sql": {"type": "string"}, "limit": {"type": "integer", "default": 100}}, "required": ["csv_path"]}),
        ])

    async def _on_call_tool(ctx, params):
        name = params.name
        args = params.arguments or {}
        if name == "list_databases":
            r = list_databases()
            return CallToolResult(content=[mt.TextContent(type="text", text=json.dumps(r, ensure_ascii=False, indent=2))])
        elif name == "list_tables":
            r = list_tables(args.get("db_path", ""))
            return CallToolResult(content=[mt.TextContent(type="text", text=json.dumps(r, ensure_ascii=False))])
        elif name == "query_sql":
            r = query_sql(args.get("sql", ""), args.get("db_path"), args.get("limit", 100))
            return CallToolResult(content=[mt.TextContent(type="text", text=r)])
        elif name == "query_csv":
            r = query_csv(args.get("csv_path", ""), args.get("sql"), args.get("limit", 100))
            return CallToolResult(content=[mt.TextContent(type="text", text=r)])
        return CallToolResult(content=[mt.TextContent(type="text", text=f"Unknown: {name}")])

    server = Server("duckdb-mcp", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)

    async def main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(main())


def _run_test_mode():
    """Fallback: line-based stdio for testing without MCP SDK。"""
    print("Test mode. Commands: list_databases, list_tables <db>, query <sql> db=<path>, csv <path>", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if line == "list_databases":
            print(json.dumps(list_databases(), ensure_ascii=False, indent=2))
        elif line.startswith("list_tables "):
            print(json.dumps(list_tables(line[12:]), ensure_ascii=False))
        elif line.startswith("query "):
            rest = line[6:]
            db_path = None
            if " db=" in rest:
                parts = rest.split(" db=", 1)
                rest = parts[0]
                db_path = parts[1]
            print(query_sql(rest, db_path))
        elif line.startswith("csv "):
            rest = line[4:]
            db_path = None
            if " db=" in rest:
                parts = rest.split(" db=", 1)
                rest = parts[0]
                db_path = parts[1]
            print(query_csv(rest, db_path))
        elif line == "quit":
            break


if __name__ == "__main__":
    if '--test' in sys.argv:
        _run_test_mode()
    else:
        _run_mcp_server()
