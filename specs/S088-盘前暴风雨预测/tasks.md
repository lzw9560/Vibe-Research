# 任务拆分 · S088 盘前暴风雨预测模型

| ID | 任务 | 文件 |
|---|---|---|
| A1 | storm_predictor.py：因子采集（外围/内部/新闻）+ 加权 + 概率分 + 仓位映射 | strategies/storm_predictor.py |
| A2 | 外围因子读 get_global_indices（美股/A50/港股） | 同上 |
| A3 | 内部因子读 gene_scores T-1 + sti_timeline（连板/炸板率/溢价） | 同上 |
| A4 | 新闻因子读 newsradar（利空密度） | 同上 |
| B1 | 端点 GET /api/sentiment/storm-predict | routers/sentiment_weather.py |
| C1 | ContextTab 接入概率分+仓位+因子明细 | components/workflow/ContextTab.tsx |
| D1 | 单测（mock 因子，0819 回测验证概率分高） | tests/test_s088_storm_predictor.py |
| D2 | 既有 STI/sentiment_weather 0 回归 | — |
