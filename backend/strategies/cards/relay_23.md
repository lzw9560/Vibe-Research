# 接力二三板（relay_23）

## 适用天气
晴天（连板接力情绪偏暖，量比健康区）

## 核心逻辑
当下连板接力——当日涨停池连板数 lbc≥2（区别 consecutive_relay 的 250 日历史频次）+ T 日量比落在 [1.5, 2.5] 健康区（放量接力但不爆量：缩量<1.5 无人接力，爆量>2.5 抛压过重）+ Dragon Score 综合维度（占位，dimension_registry 接线待）。

## 入场条件
- 当下连板：涨停池 raw lbc≥2（接力二三板定义，非历史频次）
- 量比健康区：T/T-1 volume 量比 ∈ [1.5, 2.5]（放量不爆量）
- Dragon Score：dimension_registry 综合维度（占位待接线，当前不阻塞 fire）

## 退出参数
- 止损：跌破前日收盘价 -5%
- 止盈：涨至 +12%（入场价基准）触发减仓锁利
- 最大持有：2 日

## 风险点
- 当下 lbc 由涨停池 raw 取（_get_lbc_for_code，per-date 缓存），拉取失败→data_unavailable 降级
- 量比由 baostock cache 尾部 2 根 bars 算，cache 缺该 code→data_unavailable
- 社区阈值（lbc≥2 / 量比 [1.5,2.5]）标 overfit 风险，须 sensitivity sweep
- C3 Dragon Score 为占位（dimension_registry 结构已建，composite compute 接线待），当前 fire=C1+C2

## 历史统计特征，市场有风险，研究参考。
