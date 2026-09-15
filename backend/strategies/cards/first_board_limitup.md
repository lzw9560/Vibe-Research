# 首板涨停（first_board_limitup）

## 适用天气
晴天（板块共振+封单精品，市场情绪偏暖）

## 核心逻辑
捕捉板块共振期的涨停首板。区别 first_plate（首板挖掘，gene-based 涨停频次≥6）：本战法是**涨停首板**——板块共振（板块当日涨停家数≥2）+ 封单精品（封单/流通市值≥0.5%）+ 龙头地位（high_gene 或板块内排名≤3）。板块共振是首板入场的必要条件，避无板块效应的秒板。

## 入场条件
- 龙头地位：high_gene=1 或 sector_rank≤3（板块内领涨）
- 板块共振：板块当日涨停家数 zt_count_today≥2
- 封单精品：封单/流通市值 seal_to_float_ratio≥0.005（0.5%）

## 退出参数
- 止损：跌破 5 日均线 -5%
- 止盈：涨至 +10%（入场价基准）触发减仓锁利
- 最大持有：3 日

## 风险点
- 社区阈值（zt_count_today≥2 / seal≥0.5%）标 overfit 风险，须 sensitivity sweep
- 板块共振为当日快照，次日板块退潮则共振失效
- 高封单比可能被大资金对倒制造，需结合盘口
- 涨停 pipeline 的 market_scan_ctx 由 _build_limitup_msc 构造（seal/zt_count/high_gene）

## 历史统计特征，市场有风险，研究参考。
