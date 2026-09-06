#!/bin/bash
# 微信企业应用回调穿透配置
# 把本地 8900 端口穿透到公网，供企业微信回调
#
# 用法: bash scripts/setup-wechat-tunnel.sh [本地端口]
# 示例: bash scripts/setup-wechat-tunnel.sh 8900

set -e

LOCAL_PORT=${1:-8900}

echo "=== 微信回调穿透配置 ==="
echo "本地端口: $LOCAL_PORT"
echo ""

# 方案 1: Cloudflare Tunnel（推荐，免费无注册）
if command -v cloudflared &> /dev/null; then
    echo "✅ cloudflared 已安装"
    echo "启动隧道..."
    cloudflared tunnel --url http://localhost:$LOCAL_PORT &
    TUNNEL_PID=$!
    sleep 3
    # 从输出里提取公网 URL
    TUNNEL_URL=$(curl -s http://localhost:37123/metrics 2>/dev/null | grep -o 'https://[^ ]*trycloudflare.com' | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        echo ""
        echo "✅ 隧道启动成功"
        echo "公网 URL: $TUNNEL_URL"
        echo ""
        echo "企业微信配置："
        echo "  1. 企业微信管理后台 → 应用 → 自建应用"
        echo "  2. 接收消息 → 设置 API 接收"
        echo "  3. URL 填: $TUNNEL_URL/api/wechat/bot"
        echo "  4. Token 和 EncodingAESKey 从脚本生成"
        echo "     （python3 scripts/generate-wechat-credentials.py）"
        echo ""
        echo "  按 Ctrl+C 关闭隧道"
        wait $TUNNEL_PID
    else
        echo "⚠️  未能从 metrics 接口提取公网 URL"
        echo "    请查看 cloudflared 日志手动获取 https://xxx.trycloudflare.com"
        echo "    或直接访问 https://twitter.com 不对，是看 cloudflared 启动输出"
        wait $TUNNEL_PID
    fi
else
    echo "❌ cloudflared 未安装"
    echo ""
    echo "安装方式："
    echo "  macOS: brew install cloudflared"
    echo "  或直接下载: https://github.com/cloudflare/cloudflared/releases/latest"
    echo ""
    echo "替代方案：用 ngrok"
    if command -v ngrok &> /dev/null; then
        echo "✅ ngrok 已安装，启动..."
        ngrok http $LOCAL_PORT
    else
        echo "❌ ngrok 也未安装"
        echo "  macOS: brew install ngrok"
        echo ""
        echo "请先安装任一穿透工具后重试。"
        exit 1
    fi
fi
