# Spec: S091 — gstock.global_indices 限流容错优化

> 状态：✅已实现（2026-08-22）
> 作者：lzw9560　日期：2026-08-21
> 关联：S088（global_indices 加 KOSPI/SOX）、eastmoney-push2-ut-token 记忆（push2 间歇限流）、daily-review 异常诊断

## 1. 问题 / 目标

daily-review 页面加载异常（用户报"未知异常"），根因 `/api/global/indices` 慢 **9.75s**（gstock.global_indices 串行 8 指数 push2 stock/get，每 timeout=10，东财限流时累积卡）。DailyReview 的 useGlobalIndices 慢致页面异常。push2 stock/get 间歇限流（记忆 eastmoney-push2-ut-token），daily-review 每次访问打 8 次易触发/维持限流。

目标：gstock.global_indices 限流时 fast-fail 不卡（返部分 + 标 missing），daily-review 加载快（<5s）。

## 2. 背景

- gstock.global_indices：串行 8 指数 `_push2_stock_get`（每 timeout=10），限流时累积慢
- `_push2_stock_get`：push2 优先失败降级 push2delay（`_gs_host` latch），timeout=10
- em_get 走 data.transport.eastmoney_get（限流/熔断/代理），circuit_breaker("eastmoney") 5失败 OPEN/60s 恢复
- global_indices 已 `if not d: continue` 跳过空返（部分指数 missing 透明）
- **不并发**：8 并发 push2 stock/get 会加重东财限流（记忆 push2 间歇限流，并发触发更严）

## 3. 需求

- [ ] R1：`_push2_stock_get` timeout 10→5（限流 fast-fail 更快，正常时 push2delay 降级兜底）
- [ ] R2：global_indices 限流时返部分（已有跳空，加日志标 missing 数，前端 useGlobalIndices 拿到部分不卡）
- [ ] R3：不并发（避免 8 并发加重 push2 限流）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/gstock.py` | `_push2_stock_get` timeout 10→5 + global_indices 加 missing 计数日志 |

## 5. 验收

- [ ] A1：global/indices 限流时 <5s 返（部分指数 + missing），不卡 9.75s
- [ ] A2：daily-review 加载正常（useGlobalIndices <5s）
- [ ] A3：正常时（push2 通）仍返 8 指数完整

## 6. 合规与工程底线

- push2 走 em_get 防封（§1.2，不裸调）
- 不并发避免加重限流
- 部分缺失标 missing 不臆造

## 7. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| timeout 缩 5 致正常时偶发超时（push2 慢非限流） | 部分指数 missing | push2delay 降级 + circuit_breaker |
| 限流仍偶发（东财间歇） | daily-review 偶慢 | 长期接 yahoo/stooq backup（S088 A7 裂缝登记） |

回滚：timeout 5→10。
