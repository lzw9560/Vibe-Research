# S206 盘中打磨 spec

> 状态：**abandoned**（2026-09-19，milestone-2026-09-18-pivot freeze 决议：冻结新 spec/基建 + 做减法）。盘中打磨在 freeze 前未实现；freeze 后不推进，移至 `specs/_abandoned/`（reversible git mv）。
> 原草案（2026-09-15，审查 workflow `w3qjmina3` + 专家/grill/计划 workflow `wn7jczlj6` 产出）。SDD §0。
> 关联：[[./plan.md]]、[[./tasks.md]]、CLAUDE.md §0 规范驱动、§44v2 应用规约。
> 时间线：现在（盘前/非交易时段）深度分析+制定计划，**开盘后按 tasks P0_FIRST 执行**。

## 问题陈述

盘中层存在"厚架构 vs 薄地基"的结构性矛盾：5 executor / 5 DB / 6 endpoint 的多层架构跑在 22+ 天永久丢失的数据上（8/18-8/31 后端宕机 10 交易日 + 9/1-9/3 未启动），seal_intraday 仅 10/32 天(31%)、微结构 6/32 天(19%)、OFI 仅 2/32 天(3%) 覆盖——全在 §44v2 <60 天 underpowered 线下。

在此薄地基上叠加了三重功能假象：
1. **dual_pressure 双重压力告警恒 False**（`intraday_sentiment.py:415` `_judge_seal_status` 永不返"炸板未回封"，代码注释 `:457` 自承降级需分时数据）→ Layer 2 持仓×情绪联动整层无信息量
2. **4 层情绪端点全活但 IntradayCockpit 主路由不渲染**（只在 router redirect 后不可达的 `IntradayMonitor.tsx` 孤儿页）→ 用户看不到走势/持仓联动/场景/T+1 可视化
3. **T+1 +5 投影是拍脑袋猜测非信号**（`intraday_sentiment.py:632` `scenario_rebound` 用 `current_score+5` 无数据依据）+ `:641-642` snap 原地变异污染 ring buffer

运行时地基也不稳：Python 3.14 Homebrew venv 复现过 worker 崩+慢响应（PID 56400 正跑 3.14.7），sync 网络调用在 async 任务路径下不可被超时打断是 9 个 stale-reap 簇（0915 09:28-10:44）的直接根因。

**核心矛盾不是"哪个指标有 alpha"而是"数据覆盖太薄无法判断哪个有 alpha"**——此刻上重方法论必证否（OFI cockpit 已正确定位 read-only 是对的）。正确优先序：先稳运行时 → 诚实移除死代码和伪精度 → 恢复可回补数据（baostock 5min 是唯一路径）→ 数据可信后再接线。

## 目标

1. 恢复运行时稳定：Python 3.11.8 venv 重建（pyenv 3.11.8 已装）+ per-call 网络超时（requests timeout=10s 根除线程池饿死）
2. 诚实移除死代码与伪精度：dual_pressure 标 `unavailable` 非 `False`（恒 False 是诚实反映分时数据源结构性不存在）+ T+1 +5 拍脑袋投影砍掉或改数据驱动
3. 恢复可回补数据覆盖：baostock 5min 多日回补脚本（唯一可回补盘中价格序列源，零件全有只差组装）+ 炸板池(getTopicZBPool)同步回补
4. 盘中情绪速览接线：IntradayCockpit 顶部加 score/zone/涨停率/炸板率/涨跌比紧凑数字条（数据已 fetch 仅缺渲染，零成本高收益）
5. 4 层按时段门控接线：Layer 1 速览常驻 / Layer 2 持仓联动右栏（dual_pressure 修后接） / Layer 3 场景折叠 / Layer 4 T+1 时段门控（14:30 后弹入）——避免重蹈 IntradayMonitor 等权堆叠覆辙
6. 不可回补信号标探索性：OFI 2天/auction 7天/seal 11天/micro 7天全在 §44v2 <60天 underpowered 线下，标 exploratory 不上重方法论不判劣于随机
7. 防回归：intraday_sentiment 680 行 0 专项单元测试补齐（_judge_seal_status/dual_pressure/T+1 各路径）

## 诚实标注（honest_caveats，必读）

- ⚠ **22+ 天永久丢失不可逆**：8月18-31 后端宕机 10 交易日 + 9月1-3 没启动，seal_intraday/hithink三榜/腾讯OFI 全实时 only 无历史 API，baostock 5min 回补只能恢复价格序列，不可恢复 OFI/竞价/封单事件
- ⚠ **baostock 5min 回补链式依赖未实测**：`hithink_src.py:286 limit_up_pool(date_str)` 注释称"按历史日期盘后可查"但 8/18 远期日期实际支持范围未验证——回补脚本写完前不能保证补回全部 22 天，须先 3 天小批验证
- ⚠ **baostock 5min 回补须同时查炸板池**：`getTopicZBPool`（走 em_get 非独立 breaker）否则结构性丢失炸板未回封事件，使 dual_pressure 5min 重建不完整
- ⚠ **§44v2 距统计显著性门槛远**：当前 forward_test_records 337行/21天，§44v2 需 60天门槛；baostock 回补最多恢复价格序列到 ~32天，距 60天仍差 ~28天，R3 写回未触发是正确行为非 bug
- ⚠ **过拟合风险**：在仅 7-10 天 5min 数据上重建 seal-detection = 过拟合土壤；grill 明确判删比修安全（修=在薄数据上建判别逻辑），须等 30-60 天回补后才重建
- ⚠ **T+1 +5 投影砍掉移除了一个功能**：当前给用户"反弹场景 score+5"虽是拍脑袋猜测，但砍掉后 14:30 后 T+1 面板将显示"数据不足"空态，须接受此功能收缩
- ⚠ **Python 3.11.8 非 3.12**：pyenv 装的是 3.11.8 不是 3.12，3.11.8 足够稳定且项目依赖已验证兼容，无需额外安装 3.12
- ⚠ **max_workers 保持 2 不升 4**：grill 判定子进程已绕过串行门，升 4 反增并发 em_get 调用致 IP 风险——这是约束非缺陷
- ⚠ **情绪速览条数据覆盖本身也薄**：Layer 1 score/zone 由 sti_intraday 采样器实时计算，但 22 天丢失意味着历史参照"首日为零"场景仍频繁，空态文案须区分"端点挂了"vs"真没采到"
- ⚠ **lift_to_multiplier 接线后短期无实际效果**：R3 写回须 days_robust≥60 才触发，当前 21 天即使接线也不会改变 fusion 分数——接线是为数据到门槛后自动生效做准备

## 验收（verification gates，逐 phase 见 plan.md）

1. uvicorn 启动 :8900 响应 <2s 且 mini_racer/requests/sqlite3 全通；一个完整交易日无 stale-reap 簇
2. dual_pressure_count 标 unavailable 非 False；cockpit 顶部可见 score/zone/率数字条
3. baostock 5min 回补 3 天小批：freeze_baostock_5min 每日 row_count>0 且 hithink limit_up_pool 返回非空
4. HoldingsEmotionTable 在 cockpit 渲染（非孤儿页）；OFI 端点响应含 is_underpowered=true
5. pytest -m 'not live' 全绿；intraday_sentiment 行覆盖率 >80%
6. MarketTreemap borderColor 用 CSS 变量非硬编码 hex；3 组件 error vs no-data 分流

## 受影响文件（P0_FIRST 即触及）

- `backend/.venv/`（venv 重建）
- `backend/intraday_sentiment.py`（dual_pressure 降级 + T+1 投影砍/改）
- `backend/scheduler/cron_runner.py`（stale-reap 注释修正）
- `backend/data/sources/{hithink_src,baostock_src,tencent}.py`（per-call timeout）
- `backend/routers/intraday_sentiment.py`（seal_status_degraded 标注）
- `frontend/src/pages/intraday/IntradayCockpit.tsx`（情绪速览条 + 4 层接线）
- `frontend/src/components/intraday/{HoldingsEmotionTable,ScenarioCards,T1ProjectionPanel,EmotionTrendChart}.tsx`（迁移接线）

## 合规自查（§1.2 工程底线）

- 不臆造数据：dual_pressure 标 unavailable 而非假装计算；OFI 标 underpowered 而非判劣于随机；空态分 error vs no-data
- 私有数据隔离：`.vibe-research/` 不进 git（0 字节空 DB 清理时确认无数据丢失）
- `em_get` 防封：baostock 回补走 baostock（无 IP 限）非 em_get；max_workers 保持 2 不升 4 防并发 em_get 致 IP 风险
- §44v2 规约：OFI/auction/seal/micro 全 <60 天标 underpowered 不上重方法论；R3 写回须 days_robust≥60 才触发
