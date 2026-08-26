# 龙头战法（dragon_head）

## 适用天气
晴天（软标注，S086 R3 后任意天气可触发）

## 核心逻辑
板块轮动中识别龙头股。板块内个股排名 ≤ 3（龙头地位）时命中。非追高，属强势识别/追踪型。无 market_scan_ctx（涨停 pipeline 路径）时不评估（数据降级，非逻辑过滤）。

## 入场条件
- 板块内个股排名 ≤ 3（sector_rank，龙头地位）

## 执行规则
- 板块启动期确认后介入（非追高）
- 严格止损，跌破 5 日线减仓，跌破 10 日线清仓

## 退出参数
- 止损：跌破 5 日均线（-5% 复核线，入场价基准）
- 止盈：涨至 +15%（入场价基准）触发减仓锁利
- 最大持有：5 日

> dragon_head 为非涨停 pipeline，无自动结算 runtime，退出参数为设计值（人工执行）。

## 风险点
- 板块退潮时龙头补跌风险
- 数据延迟可能导致入场偏晚
- 退潮期须空仓或轻仓

## 来源与样本期
- 参数来源：
  - [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) `strategies/dragon_head.yaml`（识别标准含板块领涨、换手 > 5%、量比 > 1.5、相对强度、新闻催化）
  - [attrib2004/a-share-dragon-strategy](https://github.com/attrib2004/a-share-dragon-strategy)（龙头等级划分、综合评分模型）
- 样本时效声明：卡片入场条件以 S097 match 为准（sector_rank ≤ 3），来源的换手/量比/相对强度等为参考，未接入 match 门控。
- 历史统计特征，市场有风险，研究参考。
