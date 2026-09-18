# S215 — 通用技术指标评分（按 stock-analysis 6 维）

## 问题
Vibe-Research 现有 14 维 scoring 是**打板专用**（封单/板块/连板/涨停频次），缺**通用技术面**评分（MA/MACD/RSI/量能/乖离/支撑）。非打板场景（趋势/反转/通用选股/前端单股展示/AI chat 工具）缺技术评分。

stock-analysis skill（liusai0820，ModelScope）有 6 维 100 分制通用技术评分 + 信号映射，可借鉴。

## 目标
新建**独立通用技术评分模块**（strategies/tech_score.py）——MA/MACD/RSI/量能/乖离/支撑 6 维，100 分→信号映射（≥75 强买/≥60 买/≥45 持有/≥30 观望/<30 强卖）。按 stock-analysis 方法论。

**独立模块，不碰打板 scoring.py**（打板专用 14 维保持）+ **不碰 §44v2 / lift_for_arm / first_board_market_env**（regime 守护区）。

## 6 维（按 stock-analysis）
1. **MA 均线系统**（MA5/10/20/60 多空排列）：多头排列（MA5>MA10>MA20>MA60）高分，空头低分
2. **MACD**（DIF/DEA/柱状 趋势动能）：金叉（DIF>DEA）+ 柱状放大高分，死叉低分
3. **RSI**（6/12/24 超买超卖）：40-60 中性高分，>70 超买低分（追高风险），<30 超卖高分（反弹机会）
4. **量能分析**（量比）：量比 1-2 健康放量高分，>5 异常低分，<0.5 缩量低分
5. **乖离率**（股价 vs MA20 偏离）：BIAS 在 ±5% 内高分（无追高风险），>5% 追高低分，<-5% 超卖高分
6. **支撑/压力位**（关键位）：股价近支撑（+5% 内）高分，近压力（-5% 内）低分

## 100 分 → 信号映射
- ≥75 强烈买入
- ≥60 买入
- ≥45 持有
- ≥30 观望
- <30 强烈卖出

## 受影响文件
- strategies/tech_score.py（新）：6 维计算 + 100 分合成 + 信号映射
- chat.TOOLS（注册 AI 工具，API+MCP 同步）：query_tech_score(code) → 6 维分 + 信号
- routers/stock_data.py（endpoint /api/stock/tech-score?code=）
- tests/test_s215_tech_score.py：6 维计算 + 信号映射 + 边界（空 bars/单 bar）

## 数据源
- baostock bars（K 线 OHLCV，不封 IP，已集成 bars_provider）——优先
- astock（A 股实时，em_get 限流）——实时补充

## 验收
- 6 维计算正确（MA/MACD/RSI/量比/乖离/支撑 各自阈值映射）
- 100 分合成 + 信号映射
- test green（含边界：空 bars/单 bar/不足周期）
- chat.TOOLS 注册（API + MCP 自动同步）
- 不碰打板 scoring.py / §44v2 / lift_for_arm / first_board_market_env

## 合规自查（弱合规）
- 不臆造：6 维从 bars 复算（MA/MACD/RSI 公式可复算），缺数据标 missing 不编
- 私有数据隔离：bars 从 .vibe-research/ cache（不进 git）
- 防封：baostock 不封 IP，astock 走 em_get 限流
- 交易信号：通用技术评分是参考层（非 sizing 杠杆），不接 lift_for_arm，不削打板因子权重

## 范围
- 做：tech_score.py 6 维 + 100 分 + 信号 + chat.TOOLS + router + test
- 不做：接 §44v2 / lift_for_arm（独立参考层，非 sizing）；前端展示（defer）；替代打板 scoring.py（打板专用保持）

## 状态
- 草案（2026-09-17，多轮闭环宏观接入 + skill 评估后）
