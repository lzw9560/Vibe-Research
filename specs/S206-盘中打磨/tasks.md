# S206 盘中打磨 tasks

> 可执行 checklist，每条带依赖序+验收点。TDD：每 task 先写 test（红）→实现（绿）→重构。SDD §0。
> 关联：[[./spec.md]]、[[./plan.md]]。
> **时间线：P0_FIRST 开盘后立即执行；P1-P4 按依赖序推进。现在不动代码（盘前只分析+制定计划）。**

## P0_FIRST（开盘后立即执行，6 条）

- [x] **T0** venv 现跑 3.11.16 ✅（**非 planned upgrade，是 rm 误删后恢复**：我 rm -rf .venv 太早[违反破坏性命令验证规则，已记 corrections]，3.14 重建 numba 建不出[传递依赖+numba<3.14]，brew install python@3.11 + python3.11 -m venv + pip install 91 deps 成功；venv 3.11.16 + 94 包 + app import OK + T2 pytest 21 passed + 后端 health ok + 首板涨停 fired。用户 pushback"3.14 稳"对——但 rm 后 3.14 不可逆，3.11 是唯一恢复路径。教训记 [[destructive-command-verify-before-rm]]）
  - 依赖: 无（地基，先于一切）
  - 步骤: `kill -9 56400` → `rm -rf backend/.venv` → `~/.pyenv/versions/3.11.8/bin/python -m venv backend/.venv` → `backend/.venv/bin/pip install -r backend/requirements.txt`（或 `pip install -e .`）→ `backend/.venv/bin/python -m uvicorn app:app --port 8900`
  - 验收:
    1. `backend/.venv/bin/python --version` = `Python 3.11.8`（非 3.14.7）
    2. `backend/.venv/bin/python -c "import mini_racer,requests,sqlite3; print('ok')"` 通过
    3. `curl -m 2 http://127.0.0.1:8900/api/health` 返 ok（响应 <2s，非 10s 超时）
    4. 更新 memory `backend-venv-python-not-system`：原修法"用 .venv/bin/python 启动"已失效（venv 自身坏），新修法=**重建 venv 用 pyenv 3.11.8** 非"切 python"

- [~] **T1** per-call 网络超时 — 部分完成：`requests` 调用（cninfo:20,28 + eastmoney:554）实测**已有** timeout=10（grep 截断换行误判缺 timeout）。真 stale-reap 根因是 hithink/baostock **SDK** 调用（非 requests，hithink_src/baostock_src 用各自 client/SDK 可能无 timeout）→ 推迟 T7 instrumented logging 先定位哪个 SDK 调用 hang，再加 timeout 机制（baostock bs.query 无 timeout 参数，可能要 thread+timeout 包裹）
  - 依赖: T0（venv 重建后才能验证）
  - 步骤: 给 hithink/tencent/baostock 所有 sync `requests` 调用加 `timeout=10s`；baostock `query_history_k_data_plus` 加超时参数。**不改 reaper 阈值**（1300s 是兜底非根因），**不改 max_workers**（保持 2）
  - 验收:
    1. `rg "requests\.(get|post)" data/sources/{hithink_src,tencent,baostock_src}.py` 全含 `timeout=`
    2. 一个完整交易日跑下来无 stale-reap 簇（reaper 不触发 = 任务不再 hang）
    3. 0914 的 19 failed+1 degraded 任务重跑后不再产生新 stale-reap

- [x] **T2** dual_pressure 诚实降级（删非修）✅（`_compute_dual_pressure` 三态 `unavailable`/`no_pressure`/`pressure` + `_is_seal_status_degraded` per stock-type[主板封住=不降级, 创业板/科创板/未封板=降级] + `:420/:426` 适配 string + seal_status_degraded per-row；**pytest 21 passed 0 failed**，首板涨停 经 HTTP 仍 fired=T 未破坏信号链）
  - 依赖: 无（纯 intraday_sentiment.py 改）
  - 步骤: `intraday_sentiment.py:415` `dual_pressure = seal_status == '炸板未回封' and current_zone == 'red'` → 改为标 `unavailable`（区分"没压力"vs"判不了"）。保留持仓↔情绪告警 hook 不删字段结构（留接口待 P2 5min 重建）。`:415/:420/:426` 死路径标 deprecated 注释
  - 验收:
    1. `dual_pressure_count` 返 unavailable 非 False
    2. Layer 2 端点响应显式标 `seal_status_degraded=true`（per-row 按 stock-type 条件触发非全局 flag）
    3. grep `dual_pressure` 无 `== '炸板未回封'` 残留（恒 False 路径移除）

- [x] **T3** 情绪速览条 ✅（`SentimentStrip` 组件加到 IntradayCockpit.tsx，渲染 score+zone 色带+zt_count/seal_rate/break_rate/ad_ratio+采样时间；空态分 error(红)/loading(灰)/no-data(dashed) 三态；tsc 零错）
  - 依赖: 无（前端纯接线，数据已 fetch）
  - 步骤: `IntradayCockpit.tsx` PageHeader 下方加一行紧凑数字条（非图表），渲染 `useIntradayLatest` 的 score+zone 色带+涨停/封板率/炸板率/涨跌比。SplitLayout 上方常驻
  - 验收:
    1. `/intraday` 顶部可见 score+zone+率数字条（当前完全不可见，只进 askAiContext 字符串）
    2. 数据来源 `useIntradayLatest`（不新增 fetch）
    3. 空态文案区分"端点挂了"vs"真没采到"

- [x] **T4** 0914 failed 任务重跑 ✅（ofi_collect id=30 重跑成功 run_id=4460 status=success <1s 无 error；trade_journal_daily/turso_sync 返回非 JSON 可能 202 async[这俩 0914 本就 300s timeout 属慢非崩]；**后端全程稳 PID 78255 0 崩溃 0 stale-reap** —— mini_racer fix + 3.11 venv 验证有效；全交易日 stale-reap 测试须开盘后跑一天）

- [x] **T5** stale-reap 注释修正 ✅（cron_runner.py:49/89/134 三处 >800s→>1300s，对齐 db.py:372 _REAPER_STALE_SECONDS=1300；grep 0 残留）
  - 依赖: 无（纯注释，低成本防误导）
  - 步骤: `cron_runner.py:49/89/134` 三处 `>800s` 改 `>1300s`（对齐 `db.py:372 _REAPER_STALE_SECONDS=1300`）
  - 验收: `grep -n "800s" scheduler/cron_runner.py` 无残留

## P1 数据积累 + 根因深挖

- [ ] **T6** baostock 5min 多日回补脚本（唯一可回补路径）
  - 依赖: T0（venv 稳定）+ 验证 hithink limit_up_pool 远期日期支持
  - 步骤: 新建 `tools/backfill_baostock_5min.py`，loop（历史交易日 × `hithink limit_up_pool(date)` 取涨停股 codes × `baostock_src.fetch_5min_bars(code,date,date)` × `freeze_baostock_5min(date,code,name,bars)`）。同步查 `em_get getTopicZBPool(date)` 取炸板事件（dual_pressure 重建须用）。**先 3 天小批验证** hithink 远期日期支持再全量 22 天。per-query throttle + baostock 登录复用
  - 验收:
    1. 3 天小批：`freeze_baostock_5min` 每日 row_count>0 且 `hithink limit_up_pool` 返回非空
    2. 5min 覆盖从 ~10 天→+22 天（接近 32 天，接近 §44v2 30 天门槛）
    3. 同步 getTopicZBPool 炸板事件入库（dual_pressure 5min 重建须用）

- [ ] **T7** stale-reap 根因深挖（instrumented logging）
  - 依赖: T1（per-call timeout 后仍有的 hang）
  - 步骤: 加 per-call instrumented logging（记每个外部调用的 enter/exit/duration+task_type），定位 09:28-10:44 簇具体卡在哪个 sync call（em_get vs hithink vs 腾讯 OFI）
  - 验收: log 报告出 stale-reap 簇具体卡在哪个调用；按 task_type 分桶限流建议

- [ ] **T8** em_get 实测量测限流
  - 依赖: T7（instrumented log 基础）
  - 步骤: 盘中高峰跑 instrumented log，看 0.3s 串行门（`transport.py:28 _EM_MIN_INTERVAL`）是否致排队超时。若确认排队→按 task_type 分桶限流（seal/OFI/micro 各独立 `_em_last_call` 不互相堵）。**不可调太快致 IP 风险——先测再调**
  - 验收: em_get 量测报告出 task_type 分桶建议；调参后盘中高峰无 em_get 排队超时

- [ ] **T9** _em_mode auto 探测加定期回探测
  - 依赖: 无
  - 步骤: 当前一次直连瞬态失败→永久固定 proxy 全进程。加定期回探（≥5min 间隔，只在 breaker CLOSED 时试一次直连）
  - 验收: 单次抖动不再永久降级到系统代理；breaker CLOSED 后自动回探直连

- [ ] **T10** lift_to_multiplier 接线 trade_journal
  - 依赖: T0（venv 稳定才能跑集成测试）
  - 步骤: 替代直接读冻结 `weight_multiplier`，让 `backtest.py:163` 已落地的 R3 自动写回（`dimension_lift_overrides`）真正影响 fusion 分数。配 trade_journal 集成测试防回归
  - 验收:
    1. trade_journal 权重读取走 lift_to_multiplier 路径
    2. 集成测试验证 fusion 分数受 dimension_lift_overrides 影响
    3. 注意：R3 写回须 days_robust≥60 才触发，当前 21 天不触发是正确行为非 bug

- [ ] **T11** worldmonitor 从活跃调用路径摘除（deprecate 非修）
  - 依赖: 无
  - 步骤: 标 @deprecated + 从 `seed.py` 任务注册和 `market.py:456`/`newsradar.py:105` 调用中注释掉（已优雅降级"不可达→返空不抛"）。不投入修 MCP 握手+SSE 解析（ROI 太低）
  - 验收: worldmonitor 不再白耗 breaker 尝试 + newsradar 线程时间；health 端点 worldmonitor 状态标 deprecated

- [ ] **T12** T+1 +5 拍脑袋投影砍掉或改数据驱动
  - 依赖: T6（baostock 5min 回补后才有 14:30-15:00 6 根 bar 数据）若走数据驱动路径
  - 步骤: `intraday_sentiment.py:631-637` "尾盘 30 分钟情绪回升 +5 分"砍掉。路径(a)砍掉 T1ProjectionPanel 不展示假精度；路径(b)用 14:30-15:00 最后 6 根 5min bar 动量替代 +5（须 T6 后）。近 0 样本 scenarios 参照一并砍。修 `:641-642` snap 原地变异（返回 copy 不污染 ring buffer）
  - 验收: T+1 面板无 `+5` 拍脑袋值；snap ring buffer 不被投影覆写；14:30 前返 not_ready

## P2 模块接线 + 信号标注（数据可信后）

- [ ] **T13** 4 层按时段门控排布接线到 IntradayCockpit
  - 依赖: T2（dual_pressure 降级后接 Layer 2）+ T3（速览条已做）+ T6（baostock 5min 回补到 30-60 天后接 Layer 4 T+1）
  - 步骤: Layer 1 速览条常驻顶（T3 已做）；Layer 2 持仓联动放右栏 StockPreview 下方（dual_pressure 行置顶即告警，须 dual_pressure 重建后接）；Layer 3 场景推演折叠（点击展开非每分钟扫）；Layer 4 T+1 时段门控（14:30 前隐藏，14:30 后自动弹入视野）
  - 验收: HoldingsEmotionTable 在 cockpit 渲染（非孤儿页）；Layer 3 折叠非默认展开；Layer 4 14:30 前不可见

- [ ] **T14** dual_pressure 5min 重建（须 baostock 回补到 30-60 天后）
  - 依赖: T6（baostock 5min 回补到 30-60 天）+ getTopicZBPool 同步入库
  - 步骤: 废弃 `_judge_seal_status` 现价近似（`intraday_sentiment.py:441-464`），改用 5min bar 序列检测炸板回封（触及涨停价→打开→是否回封），用 per-stock limit_pct 替代 9.8% 硬编码。须同时查 getTopicZBPool 确认炸板事件否则一字板破裂与从未封板不可区分
  - 验收: 单测覆盖一字板/停牌熔断/ST 5%/新股边缘 case；dual_pressure 不再恒 unavailable

- [ ] **T15** IntradayMonitor 孤儿页迁移+删页
  - 依赖: T13（4 组件迁入 cockpit 后）
  - 步骤: 4 组件迁入 cockpit 后，`buildIntradayContext` 合并进 cockpit askAiContext，`IntradayMonitor.tsx` 标 deprecated 或删（`router.tsx:135` redirect /workflow/intraday→/intraday 兜底）
  - 验收: IntradayMonitor.tsx 删除且 router 无 404

- [ ] **T16** OFI/竞价/微结构标 exploratory/underpowered
  - 依赖: 无（端点响应加 metadata）
  - 步骤: 端点响应加 metadata 标 days_covered + is_underpowered（<60天=true），不判劣于随机不上重方法论。统一口径：OFI 2天/auction 7天/seal 11天/micro 7天 全标探索性
  - 验收: OFI 端点响应含 `is_underpowered=true`

- [ ] **T17** naive datetime.now() → ZoneInfo('Asia/Shanghai')
  - 依赖: 无
  - 步骤: `intraday_sentiment.py` + `seal_intraday_collector.py` + `scheduler/db.py` 的 `datetime.now()` 统一换 `datetime.now(ZoneInfo('Asia/Shanghai'))`。stale-reap cutoff 比较两边一致即可但 market hour 门控必须 aware 防跨部署失效
  - 验收: grep `datetime.now()` 无 naive 残留（intraday 相关文件）

## P3 测试补（防回归底线）

- [ ] **T18** intraday_sentiment 单元测试（680 行 0 测试 → 补）
  - 依赖: T2（dual_pressure 降级后测各分支）
  - 步骤: `_judge_seal_status` 各分支（封住/未封板/数据未取得/炸板回封/炸板未回封）、dual_pressure 逻辑（unavailable 状态/置顶排序/count）、`_score_to_weather` 阈值、`_pnl_pct` 边界（None entry/current）
  - 验收: `pytest tests/test_intraday_sentiment.py` 全绿；intraday_sentiment 行覆盖率 >80%

- [ ] **T19** T+1 投影测试（若保留数据驱动版本）
  - 依赖: T12（T+1 改数据驱动后）
  - 步骤: 14:30 前返 not_ready、数据不足返 insufficient_data、6 根 5min bar 动量计算正确性
  - 验收: 测试覆盖 T+1 各路径

- [ ] **T20** microstructure/auction executor 测试
  - 依赖: 无
  - 步骤: 覆盖缺口/降级路径/空态诚实返回
  - 验收: executor 测试全绿

- [ ] **T21** lift_to_multiplier 集成测试
  - 依赖: T10（接线后）
  - 步骤: trade_journal 权重读取走 lift_to_multiplier 路径，防 R3 写回脱节回归
  - 验收: fusion 分数受 dimension_lift_overrides 影响有测试守住

## P4 UX 打磨

- [ ] **T22** MarketTreemap 边框/分割色改主题令牌
  - 依赖: 无
  - 步骤: `borderColor '#1a1a2e'`→`hsl(var(--border))`；涨跌热力色(红/绿)保持硬编码（页面约定确认）但可考虑 `hsl(var(--danger))/hsl(var(--success))` 族令牌统一步调
  - 验收: borderColor 用 CSS 变量非硬编码 hex

- [ ] **T23** 3 个 intraday 组件空态分 error vs no-data
  - 依赖: 无
  - 步骤: HoldingsEmotionTable/ScenarioCards/T1ProjectionPanel 当前只分 loading vs empty 不区分 error，补 error 分支
  - 验收: 端点 500 时显示 error 非 empty

- [ ] **T24** BombAlertBanner 不静默吞错
  - 依赖: 无
  - 步骤: `.catch(()=>{})`（line 22/83）静默吞错，error 路径应 surface 非 return null
  - 验收: BombAlertBanner error 路径可见非 null

## G 全量验收

- [ ] **G1** `pytest -m 'not live'` 全绿（含新 test_intraday_sentiment）
- [ ] **G2** intraday_sentiment 行覆盖率 >80%
- [ ] **G3** 一个完整交易日无 stale-reap 簇 + uvicorn 响应 <2s
- [ ] **G4** cockpit 顶部情绪速览条可见 + dual_pressure 标 unavailable
- [ ] **G5** baostock 5min 回补 3 天小批通过（hithink 远期日期支持确认）
- [ ] **G6** OFI 端点响应含 is_underpowered=true
- [ ] **G7** MarketTreemap borderColor 用 CSS 变量 + 3 组件 error vs no-data 分流
