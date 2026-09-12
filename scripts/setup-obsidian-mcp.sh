#!/bin/bash
# Obsidian MCP 连接配置脚本
# 前置：Obsidian 已安装 + Local REST API 插件已启用

set -e

VAULT="/Users/lizhiwei/Documents/Obsidian Vault"
API_KEY_FILE="$VAULT/.obsidian/plugins/obsidian-local-rest-api/data.json"

echo "=== Obsidian MCP 配置 ==="

# 1. 检查 Obsidian 是否在运行
if ! pgrep -x "Obsidian" > /dev/null 2>&1 && ! pgrep -f "Obsidian" > /dev/null 2>&1; then
    echo "❌ Obsidian 未运行，请先打开 Obsidian"
    exit 1
fi

# 2. 检查 Local REST API 插件
if [ ! -d "$VAULT/.obsidian/plugins/obsidian-local-rest-api" ]; then
    echo "❌ Local REST API 插件未安装"
    echo "请在 Obsidian → 设置 → 社区插件 → 浏览 → 搜 'Local REST API' → 安装 → 启用"
    exit 1
fi

# 3. 读 API key
if [ -f "$API_KEY_FILE" ]; then
    API_KEY=$(python3 -c "import json; d=json.load(open('$API_KEY_FILE')); print(d.get('apiKey',''))" 2>/dev/null)
fi
if [ -z "$API_KEY" ]; then
    echo "⚠️ 未找到 API key，请手动从插件设置页复制"
    echo "  Obsidian → 设置 → Local REST API → 复制 API key"
    read -p "粘贴 API key: " API_KEY
fi

# 4. 测试连接
echo "=== 测试连接 ==="
RESPONSE=$(curl -sk --max-time 5 \
    -H "Authorization: Bearer $API_KEY" \
    "https://127.0.0.1:27124/" 2>&1)

if echo "$RESPONSE" | grep -q "200 OK\|authentication"; then
    echo "✅ Local REST API 连接成功"
else
    echo "❌ 连接失败：$RESPONSE"
    echo "检查：Obsidian 是否运行 + 插件是否启用 + API key 是否正确"
    exit 1
fi

# 5. 配置 opencode MCP
OPOCODE_CONFIG="$HOME/.config/opencode/opencode.json"
echo "=== 配置 opencode MCP ==="

python3 -c "
import json
path = '$OPOCODE_CONFIG'
with open(path) as f:
    d = json.load(f)
mcp = d.setdefault('mcp', {})
mcp['obsidian'] = {
    'command': ['npx', '-y', '@yanxue06/obsidian-mcp'],
    'enabled': True,
    'type': 'local',
    'environment': {
        'OBSIDIAN_API_KEY': '$API_KEY',
        'NO_PROXY': '127.0.0.1,localhost'
    }
}
with open(path, 'w') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
print('✅ opencode MCP 已配置 obsidian server')
"

echo ""
echo "=== 配置完成 ==="
echo "重启 opencode 后，/mcp 应显示 obsidian: ✓ Connected"
echo "测试：在 opencode 里说 '查 vault 里所有股票' → MCP 调 query_dataview"
