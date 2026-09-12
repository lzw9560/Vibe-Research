#!/usr/bin/env python3
"""测试 Obsidian MCP 连接 + 关键工具。

不通过 MCP 协议，直接调 Local REST API 测试。
"""
import json
import requests
import urllib3
import os
from pathlib import Path

urllib3.disable_warnings()

VAULT = Path("/Users/lizhiwei/Documents/Obsidian Vault")
API_KEY = ""

# 读 API key
data_file = VAULT / ".obsidian/plugins/obsidian-local-rest-api/data.json"
if data_file.exists():
    with open(data_file) as f:
        API_KEY = json.load(f).get("apiKey", "")

if not API_KEY:
    print("❌ 未找到 Local REST API key")
    exit(1)

BASE = "https://127.0.0.1:27124"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

print("=== Obsidian MCP 连接测试 ===")
print(f"API Key: {API_KEY[:10]}...")
print()

# 1. 连接测试
print("--- 1. 连接测试 ---")
try:
    r = requests.get(f"{BASE}/", headers=HEADERS, verify=False, timeout=5)
    print(f"HTTP {r.status_code}")
    if r.status_code == 200:
        print("✅ Local REST API 连接成功")
    else:
        print(f"❌ 连接失败: {r.text[:200]}")
        exit(1)
except Exception as e:
    print(f"❌ 连接异常: {e}")
    exit(1)

# 2. 列出 vault 文件
print()
print("--- 2. 列出 vault 文件（list_vault 等价）---")
try:
    r = requests.get(f"{BASE}/vault/", headers=HEADERS, verify=False, timeout=5)
    print(f"HTTP {r.status_code}")
    if r.status_code == 200:
        files = r.json() if r.headers.get("content-type", "").startswith("application/json") else []
        print(f"文件数: {len(files) if isinstance(files, list) else 'N/A'}")
except Exception as e:
    print(f"⚠️ 列文件失败: {e}")

# 3. 读 MOC
print()
print("--- 3. 读 MOC（get_note 等价）---")
try:
    r = requests.get(f"{BASE}/vault/10_Reference/investing/MOC.md", headers=HEADERS, verify=False, timeout=5)
    print(f"HTTP {r.status_code}")
    if r.status_code == 200:
        content = r.text[:200]
        print(f"MOC 前 200 字: {content}")
        print("✅ get_note 可用")
except Exception as e:
    print(f"⚠️ 读 MOC 失败: {e}")

# 4. 搜索
print()
print("--- 4. 搜索（search_vault 等价）---")
try:
    r = requests.get(f"{BASE}/search/simple/",
        params={"query": "600519", "scope": ""},
        headers=HEADERS, verify=False, timeout=5)
    print(f"HTTP {r.status_code}")
    if r.status_code == 200:
        print("✅ search_vault 可用")
except Exception as e:
    print(f"⚠️ 搜索失败: {e}")

print()
print("=== 测试完成 ===")
print("如全部 ✅，重启 opencode 后 /mcp 应显示 obsidian: ✓ Connected")
print("然后可在 opencode 里用自然语言查 vault：")
print("  - '查 vault 里所有股票'")
print("  - '找 600519 的反向链接'")
print("  - 'vault 里有几个孤立笔记'")
