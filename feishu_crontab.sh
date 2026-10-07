#!/bin/bash
# 飞书Bot每日定时推送 — launchctl plist
# 安装: launchctl load ~/Library/LaunchAgents/com.vibe-research.feishu-push.plist
# 卸载: launchctl unload ~/Library/LaunchAgents/com.vibe-research.feishu-push.plist

PROJECT_DIR="/Users/lizhiwei/project/code/stock/Vibe-Research"
PYTHON="/usr/bin/python3"
SCRIPT="$PROJECT_DIR/feishu_daily_push.py"

# 08:30 盘前推送
08 30 * * 1-5 $PYTHON $SCRIPT --mode premarket >> /tmp/feishu_push_premarket.log 2>&1

# 14:30 尾盘扫描
30 14 * * 1-5 $PYTHON $SCRIPT --mode intraday >> /tmp/feishu_push_intraday.log 2>&1

# 15:30 盘后复盘
30 15 * * 1-5 $PYTHON $SCRIPT --mode postmarket >> /tmp/feishu_push_postmarket.log 2>&1
