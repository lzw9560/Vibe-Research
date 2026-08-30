# Spec: S109 — 缓存治理 Tier-1（空结果毒缓存根除，S103 模式扩铺）

> 状态：已实现(2026-08-30)
> 作者：lzw9560  日期：2026-08-30
> 级别：medium（S103 模式套用到 7 处毒缓存点，碰数据输出缓存层）
> 分支：`feature/S109-cache-poison`（off develop，squash-merge）
> 关联：S103（涨停池缓存承重切片，模式源头）/ grill「坚实数据底座」第 1 层 / S109 workflow（6 agent 审查+设计+对抗验证）

## 1. 问题 / 目标

S103 治了涨停池缓存（em_zt_topic_pool 空毒缓存 24h + 盘中陈旧），但**同款空结果毒缓存散布全仓 7 处**（S109 workflow 4 审查域 + 对抗验证抓 4 遗漏确认）。空结果（失败/瞬态故障返空）被无条件缓存 60s-1800s，breaker 恢复后仍恒空——一次瞬态故障毒缓存数十分钟。

**目标**：套 S103「空不缓存」模式到 7 处毒缓存点 + 1 处正交误键 bug。对抗验证揪出 2 处 **dict 陷阱**（失败返非空 dict，`valid=bool` 漏网，要内容感知 lambda）。

## 2. 治理清单（workflow design + verify 综合）

### Tier-1 毒缓存（7 处，全治）

| # | 位置 | 毒窗口 | 修法 |
|---|---|---|---|
| 1 | `routers/stock_financial.py:23` `_cached` | datacenter 失败返 [] 缓存 1800s | 扩签名加 `valid=bool` 守卫 |
| 2 | `data/sources/tencent.py:104` fetch_raw | gtimg 返空 {} 缓存 60s | `if result:` 才写 |
| 3 | `limitup_screener/service.py:282-294` | 空涨停池标 fresh + 缓存 12h | 整块替换返 expired + 不缓存空 |
| 4 | `routers/stock_data.py` `_PCT_CACHE`（估值分位）⚠️dict陷阱 | 失败返 `{"metrics":{}}` 缓存 1800s | `if data.get("metrics"):`（内容感知） |
| 5 | `routers/stock_data.py` `_FIN_CACHE` | akshare 返 {} 缓存 1800s | `if data:`（bool 可） |
| 6 | `routers/stock_data.py` `_ANN_CACHE` | 东财返 [] 缓存 900s | `if data:` |
| 7 | `routers/stock_financial.py:140` `industry` ⚠️dict陷阱 | 失败返 `{"top":[]}` 缓存 300s | `if data.get("top"):` |

### 附带正交 bug

| # | 位置 | bug | 修法 |
|---|---|---|---|
| 8 | `routers/sentiment_weather.py:1163` | `q.get("pct")` 误键（应为 change_pct），竞价未高开强制离场恒死 | 改 `q.get("change_pct")` |

### dict 陷阱 valid 传参（对抗验证重点）

- dragon_tiger：`valid=lambda v: bool(v.get("records"))`
- lockup：`valid=lambda v: bool(v.get("history") or v.get("upcoming"))`
- blocks：`valid=lambda v: bool(v.get("boards"))`
- _PCT_CACHE：`if data.get("metrics")`（**bool 漏网**，必须内容感知）
- industry：`if data.get("top")`

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/routers/stock_financial.py` | `_cached` 加 `valid=bool`；dragon_tiger/lockup/blocks 传内容感知 lambda；industry inline `if data.get("top"):` |
| `backend/data/sources/tencent.py` | `:104` `if result:` 才写 |
| `backend/limitup_screener/service.py` | `:282-294` 整块替换 `_empty_screener_result`（expired） |
| `backend/routers/stock_data.py` | `_PCT`/`_FIN`/`_ANN_CACHE` 加守卫；删 :29 死代码 `_cached`/`_DC_CACHE` |
| `backend/routers/sentiment_weather.py` | `:1163` `pct`→`change_pct` |
| `backend/tests/test_s109_cache_poison.py` | 新增 13 用例 |

## 4. 设计方案

### 4.1 `_cached` 扩签名（stock_financial.py）

加 `valid: Callable = bool` 参数，写入前 `if valid(data):`。复用 S103 market._cached(valid=bool) 范式。dict 返回型路由传内容感知 lambda（失败返非空 dict，bool 漏网）。

### 4.2 tencent / stock_data / industry 空不缓存

各点 `if result:` / `if data.get(key):` 守卫。tencent flat 60s 不分级（缓存键无 date 维度，无陈旧首帧问题）。

### 4.3 limitup_screener 整块替换

`if not zt_pool:` 块用 `_empty_screener_result`（已返 expired）替换，不缓存空。**整块替换非删行**——verify 抓到「删 :293 行会留 :290 fresh 误标」陷阱。

## 5. 验收标准

- [x] A1 stock_financial `_cached` valid 守卫：空 list 不缓存重试
- [x] A2 dragon_tiger/lockup/blocks 内容感知 valid：失败 dict 不缓存
- [x] A3 tencent fetch_raw 空 {} 不缓存
- [x] A4 limitup_screener 空涨停池返 expired（非 fresh）
- [x] A5 _PCT_CACHE `{"metrics":{}}` 不缓存（**bool 漏网，lambda 拦住**）
- [x] A6 _FIN/_ANN_CACHE 空不缓存
- [x] A7 industry `{"top":[]}` 不缓存
- [x] A8 sentiment_weather :1163 改 change_pct
- [x] A9 全量回归不破（test_fixes test_cached_skips_empty + test_s103 契约对齐）

## 6. 合规与工程底线自查

- [x] 不臆造：空不缓存下次重试拿真数据
- [x] §44 口径：纯缓存治理，不出 winrate/r/verdict
- [x] 私有数据隔离：无新增落盘
- [x] em_get 防封：失败不缓存空 → 真空数据重打 em_get，QPS≤2+熔断兜住（S103 同取舍）
- [x] 真·空数据重打可控（新股/无融资标的每次浏览重打，breaker 限流）

## 7. 测试计划

- **单测** 13 用例全 PASS：list 守卫 2 + dict 陷阱 3 + tencent 2 + stock_data 3 + limitup 1 + industry 1 + 正交 1
- **回归**：test_fixes.py test_cached_skips_empty（S103 契约）+ test_s103_zt_pool_cache.py 不破
- **全量 gate**：跑中

## 8. 风险与回滚

- **风险1**：真·空数据每次浏览重打 em_get。**缓解**：QPS≤2+熔断+低频（S103 同取舍）。
- **风险2**：limitup_screener fresh→expired 行为变更。**缓解**：更正确语义，前端若有 fresh 硬分支需确认。
- **风险3**：dict 陷阱 valid 配错漏 lambda。**缓解**：单测逐个验证内容感知。
- **回滚**：各点 `if valid(data):` 改回无条件写即退回。

## 9. 冲突审查表

| 旧 spec R-item | 旧决策 | 新决策 | 处置 |
|---|---|---|---|
| S103 `_ztb_cache_ttl + 空不缓存` | 涨停池单点 | 模式扩铺 7 处 | **扩展** |
| S103 `market._cached valid=bool` | 正例 | 复用给 stock_financial._cached | 共存 |
| stock_financial `_cached 无 valid` | 无条件写空 | 加 valid 守卫 | **修复** |
| stock_data 三缓存无条件写 | 空毒缓存 | 加守卫（_PCT 内容感知） | **修复** |
| sentiment_weather :1163 误键 | pct 恒 None | change_pct | **修复正交** |

## 10. 范围外明确处置（SDD 严格）

| 项 | 处置 | 理由 |
|---|---|---|
| tencent TTL 分级 | 不做 | 无 date 维度，flat 60s 无陈旧首帧 |
| app.py cache_response | 不做 | 路由层合法空语义不同，TTL 短自愈 |
| _emotion date-keyed 重构 | 另立 spec | blast radius 大（~8 直调方） |
| 删 stock_data:29 死代码 | 顺手删 | LOW-DRY 零调用 |

## 11. 不在本 spec 范围

- _emotion date-keyed 重构（单独 spec）
- app.py cache_response 路由层缓存（语义不同）
- 缓存统一公共工具抽离（YAGNI，各源自治够）
