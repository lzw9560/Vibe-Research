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

# 数据根目录
DATA_DIR = Path(os.environ.get("VR_DATA_DIR", 
    str(Path(__file__).resolve().parents[2] / ".vibe-research")))

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
    """列出 SQLite DB 的表。"""
    full_path = DATA_DIR / db_path
    if not full_path.exists():
        return [f"Error: {db_path} not found"]
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{full_path}' AS db (TYPE SQLITE)")
        result = con.execute("SELECT name FROM db.sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return [r[0] for r in result]
    finally:
        con.close()


def query_sql(sql: str, db_path: str = None, limit: int = 100) -> str:
    """执行 SQL 查询。如果指定 db_path，先 ATTACH。"""
    con = duckdb.connect()
    try:
        if db_path:
            full_path = DATA_DIR / db_path
            if not full_path.exists():
                return json.dumps({"error": f"{db_path} not found"})
            con.execute(f"ATTACH '{full_path}' AS db (TYPE SQLITE)")
            # 如果 SQL 没带 schema 前缀，加 db.
            if "db." not in sql and "FROM " in sql.upper():
                sql = sql.replace("FROM ", "FROM db.", 1)  # 简单替换第一个 FROM
        
        # 加 LIMIT
        if "LIMIT" not in sql.upper():
            sql = f"{sql.rstrip(';')} LIMIT {limit}"
        
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
        
        return json.dumps({
            "columns": columns,
            "row_count": len(rows),
            "rows": [dict(zip(columns, row)) for row in rows[:limit]],
        }, ensure_ascii=False, default=str)
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


if Server is not None:
    # Full MCP SDK available
    server = Server("duckdb-mcp")
    
    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="list_databases",
                description="List all SQLite databases in .vibe-research/",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="list_tables",
                description="List tables in a specific SQLite database",
                inputSchema={
                    "type": "object",
                    "properties": {"db_path": {"type": "string", "description": "Relative path to .db file in .vibe-research/"}},
                    "required": ["db_path"],
                },
            ),
            Tool(
                name="query_sql",
                description="Execute SQL query on a SQLite database (via DuckDB ATTACH) or CSV",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL query"},
                        "db_path": {"type": "string", "description": "Optional: relative path to .db file"},
                        "limit": {"type": "integer", "description": "Max rows to return", "default": 100},
                    },
                    "required": ["sql"],
                },
            ),
            Tool(
                name="query_csv",
                description="Query a CSV file directly with DuckDB (no import needed)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "csv_path": {"type": "string", "description": "Path to CSV file"},
                        "sql": {"type": "string", "description": "Optional SQL (use {table} as placeholder)"},
                        "limit": {"type": "integer", "description": "Max rows", "default": 100},
                    },
                    "required": ["csv_path"],
                },
            ),
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == "list_databases":
            result = list_databases()
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        elif name == "list_tables":
            result = list_tables(arguments["db_path"])
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        elif name == "query_sql":
            result = query_sql(arguments["sql"], arguments.get("db_path"), arguments.get("limit", 100))
            return [TextContent(type="text", text=result)]
        elif name == "query_csv":
            result = query_csv(arguments["csv_path"], arguments.get("sql"), arguments.get("limit", 100))
            return [TextContent(type="text", text=result)]
    
    async def main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    
    import asyncio
    asyncio.run(main())
else:
    # Fallback: line-based stdio (for testing without MCP SDK)
    print("MCP SDK not available. Running in test mode.", file=sys.stderr)
    print("Available commands: list_databases, list_tables <db_path>, query <sql>, csv <path>", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if line == "list_databases":
            print(json.dumps(list_databases(), ensure_ascii=False, indent=2))
        elif line.startswith("list_tables "):
            print(json.dumps(list_tables(line[12:]), ensure_ascii=False))
        elif line.startswith("query "):
            print(query_sql(line[6:]))
        elif line.startswith("csv "):
            print(query_csv(line[4:]))
        elif line == "quit":
            break
