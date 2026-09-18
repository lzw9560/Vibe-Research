# Spec: S110 — fund_flow_120d 测试断言对齐 bc197ca 新行为

> 状态：已实现(2026-08-30)
> 作者：lzw9560  日期：2026-08-30
> 级别：small（测试断言对齐，无代码改动）
> 分支：直接 develop（small 级免 feature 分支）
> 关联：bc197ca（资金流新浪 MoneyFlow 降级，引入行为变更未更测试）/ S103-S109 全量回归常驻 7 failed

## 1. 问题 / 目标

`bc197ca feat: 资金流数据源新浪 MoneyFlow 降级` 改了 `stock_fund_flow_120d` 行为：
- 旧：push2delay 返 1 条也当成功返（测试断言 `len==1`）
- 新：push2delay 返 <5 条视为数据不足，降级新浪 `_sina_fund_flow_fallback`（返 120 条）

**行为改进正确**（push2delay 延时镜像不完整，1 条非有效历史），但 7 个测试断言没跟着改，跨 S105-S109 四个 spec 全量回归常驻 7 failed，干扰判断。

**目标**：测试断言对齐 bc197ca 新行为——东财路径给 ≥5 条 klines（不触发新浪降级），新浪 fallback mock 返 []（不联网 + 保"东财失败→空"断言）。

## 2. 改动（纯测试，无产品代码）

| 文件 | 改动 |
|---|---|
| `tests/test_s008_sources_eastmoney.py` | autouse fixture mock `_sina_fund_flow_fallback` 返 []；5 个 fund_flow 测试 payload 给 ≥5 条 klines（shape/first_host/fallback_to_push2delay/empty_klines/both_fail）断言对齐 |
| `tests/test_s085_topology_fflow_date.py` | 2 个测试 mock 新浪返 [] + rows 补 ≥5 条（filters_by_date/no_date_returns_all） |

## 3. 验收

- [x] 7 个原 failed 测试全 PASS
- [x] 全量回归 fund_flow 零 failed（S103-S109 常驻债清）
- [x] 无产品代码改动（纯断言对齐）

## 4. 合规

- [x] 不臆造：测试 mock 新浪返 [] 模拟"东财失败+新浪也失败"，对齐真实降级语义
- [x] 测试隔离：mock 新浪不联网

## 5. 范围外

- bc197ca 的新浪 fallback 本身不在本 spec 评估（它是别会话的 commit，本 spec 只对齐测试）
- _sina_fund_flow_fallback 的限流/熔断（YAGNI，待失败率数据）
