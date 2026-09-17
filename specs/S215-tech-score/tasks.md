# S215 tasks — 通用技术指标评分（按 stock-analysis）

## T1 tech_score.py 6 维
- [x] T1.1 strategies/tech_score.py（新）：6 维计算（MA5/10/20/60 多空 + MACD DIF/DEA/柱状 + RSI 6/12/24 + 量比 + 乖离 BIAS vs MA20 + 支撑压力 20 日 min/max）
- [x] T1.2 100 分等权合成 + 信号映射（≥75 强买/≥60 买/≥45 持有/≥30 观望/<30 强卖）
- [x] T1.3 纯 Python 算（不依赖 numpy/pandas），数据走 baostock bars
- [x] T1.4 不碰打板 scoring.py（14 维保持）+ 不碰 §44v2/lift_for_arm（regime 守护区）

## T2 chat.TOOLS 注册
- [x] T2.1 ai/tools/ta_tools.py 加 @register_tool query_tech_score（调 compute_tech_score + KlineCacheBarsProvider 取 bars）
- [x] T2.2 registry 自动注册（get_openai_tools 19 工具含 query_tech_score）
- [x] T2.3 MCP 自动同步（mcp_server 复用 chat.TOOLS）
- [x] T2.4 与 query_gap_regime/query_macd_divergence/query_rsi 互补（综合评分 vs regime 信号）

## T3 router endpoint
- [x] T3.1 routers/stock_data.py 加 /api/stock/tech-score endpoint（async + asyncio.to_thread）

## T4 test
- [x] T4.1 tests/test_s215_tech_score.py：26 test（6 维计算 + 信号映射 + 边界：空/单/<60 bars）
- [x] T4.2 test_registry 更新（删 worldmonitor_query + 加 query_tech_score）
- [x] T4.3 600519 真 bars 调通（total=61.7 买入，n_bars=177，ma=35/macd=20/rsi=75/volume=80/bias=80/support=80）

## 状态
- 已实现（2026-09-17，commit 未单独标含 S215 spec + tech_score + ta_tools + router + test）。
- 通用技术指标评分可用：chat.TOOLS query_tech_score（AI 问股）+ /api/stock/tech-score（前端）。
