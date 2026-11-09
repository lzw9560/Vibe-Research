# S245 · 打新 Regime 监控（破发率/首日涨幅/IPO 节奏 转弱 alert）

> 状态：**已实现**（2026-11-09）
> 编号：S245 | 类型：feat | 分级：medium（涉及交易信号，不可跳过 spec）

## 1. 问题 / 目标

6专家panel(wb8nifjg8)synthesis 第三步:打新是当前系统最大 surviving edge(14.72% > 512890 的 13.47%),且与底仓 stack(底仓市值同时是打新配售市值,边际成本零)。BUT S243 只筛个股 PE 红线,**完全没盯 regime**(等于最大引擎没仪表盘)。

explore_ipo_underpricing.py 已验证 4 段断代 regime 依赖:S4 当前(2024+)破发 0.57% + 首日 median +199.8%(异常 favorable),BUT S3 破发潮(2021-2023)破发 22% + median +39%——yield 腰斩只需 regime 一转(IPO 加速/定价放开/询价放开)。

本 spec 落地打新 regime 监控:weekly 算 rolling 90 天破发率+首日 median+IPO 数/周,2/3 触发转弱 alert,保护最大 surviving edge。

## 2. 需求清单

| # | 需求 | Phase |
|---|---|---|
| R1 | `ipo_regime_monitor` executor(weekly,算 rolling 90 天 regime health) | 1 |
| R2 | regime 转弱阈值:破发率>10% OR 首日 median<50% OR IPO>5/周,2/3 触发 alert | 1 |
| R3 | 飞书提醒(regime 转弱时 alert,正常时 skip 不打扰) | 1 |
| R4 | weekly cron(每周日 18:00) | 1 |
| R5 | 不自动交易(PaperPortfolio 提醒辅助手动) | 全局 |

## 3. 受影响文件

**新增**
- `backend/scheduler/executors/ipo_regime.py`——`ipo_regime_monitor`(rolling regime health + 转弱 alert)
- `backend/tests/test_ipo_regime.py`——regime 转弱/正常/边界触发逻辑

**修改**
- `backend/scheduler/executors/__init__.py`——`_executors` 注册 1 + wrapper
- `backend/scheduler/seed.py`——1 cron(weekly 周日 18:00)
- `backend/tests/test_task_executor.py` + `test_regression_bugs.py`——`_EXPECTED_TASK_TYPES` 两处同步

## 4. 验收标准

- **AC1** `ipo_regime_monitor`:拉 stock_xgsglb_em 近 90 天已上市新股,算破发率+首日 median+IPO 数/周 ✅
- **AC2** regime 转弱阈值:破发>10% OR median<50% OR IPO>5/周,2/3 触发 → 飞书 alert ✅
- **AC3** regime 正常(0-1 个触发)→ skip 不打扰 ✅
- **AC4** weekly cron(周日 18:00)✅
- **AC5** 不自动交易(PaperPortfolio 提醒辅助手动)✅

## 5. regime 转弱阈值(基于 explore_ipo_underpricing.py 4 段断代)

- **破发率 >10%**:S4 当前 0.57%,S3 破发潮 22%。>10% = regime 转弱信号
- **首日 median <50%**:S4 当前 +199.8%,S3 破发潮 +39%。<50% = 转弱
- **IPO 数 >5/周**:S4 当前 ~100/年≈2/周,S3 ~290/年≈6/周。>5/周 = IPO 加速(regime 转弱先兆)
- **2/3 触发**:避免单指标噪声(如破发率小样本波动)

## 6. 合规自查（§1 弱合规）

- ✅ 工程底线——不臆造:数据走 akshare stock_xgsglb_em(已验证 4036 行),数字从数据算
- ✅ 工程底线——私有数据隔离:无持仓/API key 涉入
- ✅ 工程底线——防封:stock_xgsglb_em 走 circuit_breaker(复用 akshare_yield.py 封装)
- ✅ 弱合规:regime 监控是客观指标,非个股推荐,非选股 alpha;提醒辅助手动

## 7. 非自动交易说明

PaperPortfolio 无 broker——提醒辅助用户手动执行。飞书推送(weekly 1 次,仅转弱时 alert,正常 skip 不轰炸)。

## 8. 测试

- `test_ipo_regime.py`:regime 转弱(2/3 触发)→ sent / 正常(0-1 触发)→ skip / 边界(1 个触发)→ skip
- `_EXPECTED_TASK_TYPES` 两处同步
- TDD：先写测试（RED）→ 实现（GREEN）
