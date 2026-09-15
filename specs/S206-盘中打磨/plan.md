# S206 盘中打磨 plan

> 技术方案——怎么做。取舍/备选为何不选/模块拆分/依赖序/数据流。SDD §0 plan→tasks 不跳。
> 关联：[[./spec.md]]、[[./tasks.md]]。

## ordering 理由（grill 共识）

盘中数据 blocker 先于一切功能打磨，原因不是"谁更重要"而是"沙子上建楼"。Python 3.14 venv 是运行时阻断——后端不稳（10s 超时失败 30s 才成，worker 崩复现 2 次），任何 dual_pressure 修复 / 4 层接线 / baostock 回补都跑不动验证。per-call 网络超时是 stale-reap 9 簇的直接根因（sync I/O 在 async 任务路径不可被超时打断 → ThreadPoolExecutor max_workers=2 池饿死 → 级联 hang），不修根因调 reaper 阈值（800s→1300s）是迟到的绷带。

诚实移除死代码（dual_pressure 删非修）先于数据回补，因为 grill 判定"修=在 7-10 天 5min 数据上建 seal-detection = 过拟合土壤"——分时数据源结构性不存在（baostock T+1 lag 不可用于实时、hithink 快照无分时粒度、_judge_seal_status 现价近似自承降级），恒 False 是诚实反映，删比假装能修更诚实。等 30-60 天回补后才用 5min bar 序列重建（触及涨停价→打开→是否回封）。

baostock 5min 回补是唯一可恢复路径（其他 4 executor 依赖实时 only 源不可回补），且零件全有只差组装脚本（`freeze_baostock_5min` 写 + `load_5min_freeze` 读 + `baostock_src.fetch_5min_bars` 历史取数 + `baostock_5min_freeze` 表 INSERT OR REPLACE 幂等）。回补后 5min 覆盖从 ~10 天→~32 天接近 §44v2 30 天门槛，且 5min bar 序列恰是 dual_pressure 重建所需的数据源。

4 层情绪接线在数据可信后做，按时段门控排布（常驻/折叠/14:30 弹入）非等权堆叠——避免重蹈 IntradayMonitor 孤儿页"4 组件等权堆叠"覆辙，让注意力跟决策紧迫度走。情绪速览条是唯一例外——零成本（数据已 fetch 仅缺渲染）高收益（全天最高频扫的信息），与底盘修复并列 P0。

## phases（依赖序）

### P0 底盘稳定 + 诚实移除（开盘后立即执行，见 tasks.md P0_FIRST）

底盘不稳则一切盘中工作跑在随时崩的进程上。
- Python 3.14 Homebrew → 3.11.8 pyenv 重建 venv（pyenv 3.11.8 已装 `~/.pyenv/versions/3.11.8`）
- per-call 网络超时（hithink/tencent/baostock requests timeout=10s + baostock query 超时）根除线程池饿死，**不改 reaper 阈值**（1300s 是兜底非根因），**max_workers 保持 2 不升 4**（子进程已绕过串行门，升 4 反增并发 em_get 致 IP 风险）
- subprocess 超时隔离保持只给 seal_intraday_collect（唯一走 em_get 的盘中 executor，已有 `_SEAL_COLLECT_SUBPROCESS_TIMEOUT=110s`），不扩展到非东财调用
- dual_pressure 诚实降级：`intraday_sentiment.py:415` 改 dual_pressure 从恒 False 为标 `unavailable`（区分"没压力"vs"判不了"），seal_status_degraded per-row 按 stock-type 条件触发非全局 flag；保留持仓↔情绪告警 hook 不删字段结构（留接口待 P2 5min 重建）
- 情绪速览条：IntradayCockpit.tsx PageHeader 下方加一行紧凑数字条（非图表），渲染 useIntradayLatest 的 score+zone 色带+涨停/封板率/炸板率/涨跌比，SplitLayout 上方常驻
- stale-reap 注释修正：cron_runner.py:49/89/134 三处 `>800s` 改 `>1300s`（对齐 db.py:372 `_REAPER_STALE_SECONDS=1300`），低成本防误导
- 0914 failed 任务重跑：实测 19 failed+1 degraded（比声称的 10 更多），确认 per-call timeout 修复后不再产生新 stale-reap 簇

### P1 数据积累 + 根因深挖

- baostock 5min 多日回补脚本：loop（历史交易日 × `hithink limit_up_pool(date)` 取涨停股 codes × `baostock fetch_5min_bars(code,date,date)` × `freeze_baostock_5min`），同步查 `em_get getTopicZBPool(date)` 取炸板事件（dual_pressure 重建须用）。先 3 天小批验证 hithink 远期日期支持再全量 22 天。per-query throttle + baostock 登录复用
- stale-reap 根因深挖：加 per-call instrumented logging（记每个外部调用的 enter/exit/duration+task_type），定位 09:28-10:44 簇具体卡在哪个 sync call（em_get vs hithink vs 腾讯 OFI）
- em_get 实测量测限流：盘中高峰跑 instrumented log，看 0.3s 串行门（transport.py:28 `_EM_MIN_INTERVAL`）是否致排队超时。若确认排队→按 task_type 分桶限流（seal/OFI/micro 各独立 _em_last_call 不互相堵）。不可调太快致 IP 风险——先测再调
- _em_mode auto 探测加定期回探测：当前一次直连瞬态失败→永久固定 proxy 全进程。加定期回探（≥5min 间隔，只在 breaker CLOSED 时试一次直连）
- lift_to_multiplier 接线 trade_journal：替代直接读冻结 weight_multiplier，让 backtest.py:163 已落地的 R3 自动写回（dimension_lift_overrides）真正影响 fusion 分数。配 trade_journal 集成测试防回归。注意：R3 写回须 days_robust≥60 才触发，当前 21 天不会触发是正确行为非 bug
- worldmonitor 从活跃调用路径摘除：标 @deprecated + 从 seed.py 任务注册和 market.py:456/newsradar.py:105 调用中注释掉（已优雅降级"不可达→返空不抛"，deprecate 优先级可降）。不投入修 MCP 握手+SSE 解析——ROI 太低
- T+1 +5 拍脑袋投影砍掉或改数据驱动：`intraday_sentiment.py:631-637` "尾盘 30 分钟情绪回升 +5 分"是猜测非信号。路径(a)砍掉 T1ProjectionPanel 不展示假精度；路径(b)用 14:30-15:00 最后 6 根 5min bar 动量替代 +5（须 baostock 5min 回补后才有数据）。近 0 样本 scenarios 参照一并砍

### P2 模块接线 + 信号标注（数据可信后）

- 4 层按时段门控排布接线到 IntradayCockpit：Layer 1 速览条常驻顶（P0 已做）；Layer 2 持仓联动放右栏 StockPreview 下方（有持仓时显示，dual_pressure 行置顶即告警，须 dual_pressure 重建后接）；Layer 3 场景推演折叠（点击展开非每分钟扫）；Layer 4 T+1 时段门控（14:30 前隐藏，14:30 后自动弹入视野）
- dual_pressure 5min 重建（须 baostock 回补到 30-60 天后）：废弃 `_judge_seal_status` 现价近似（intraday_sentiment.py:441-464），改用 5min bar 序列检测炸板回封（触及涨停价→打开→是否回封），用 per-stock limit_pct 替代 9.8% 硬编码。须同时查 getTopicZBPool 确认炸板事件否则一字板破裂与从未封板不可区分
- IntradayMonitor 孤儿页迁移+删页：4 组件迁入 cockpit（按门控优先级摆位）后，buildIntradayContext 合并进 cockpit askAiContext，IntradayMonitor.tsx 标 deprecated 或删（router.tsx:135 redirect /workflow/intraday→/intraday 兜底）
- OFI/竞价/微结构标 exploratory/underpowered：端点响应加 metadata 标 days_covered + is_underpowered（<60天=true），不判劣于随机不上重方法论。统一口径：OFI 2天/auction 7天/seal 11天/micro 7天 全标探索性
- naive datetime.now() → ZoneInfo('Asia/Shanghai')：intraday_sentiment.py + seal_intraday_collector.py + scheduler/db.py 的 datetime.now() 统一换 aware。stale-reap cutoff 比较两边一致即可但 market hour 门控必须 aware 防跨部署失效
- seal_status_degraded 诚实降级标注（per-row 按 stock-type 条件触发）：短期在 Layer 2 端点响应里显式标 seal_status_degraded=true 告知用户判定不可靠，dual_pressure 字段标 unavailable 非 False

### P3 测试补（防回归底线）

intraday_sentiment.py 680 行 0 专项单元测试——_judge_seal_status/dual_pressure/T+1 各路径无覆盖。microstructure/auction executor 同理缺测试。
- intraday_sentiment 单元测试：_judge_seal_status 各分支（封住/未封板/数据未取得/炸板回封/炸板未回封）、dual_pressure 逻辑（unavailable 状态/置顶排序/count）、_score_to_weather 阈值、_pnl_pct 边界（None entry/current）
- T+1 投影测试（若保留数据驱动版本）：14:30 前返 not_ready、数据不足返 insufficient_data、6 根 5min bar 动量计算正确性
- microstructure/auction executor 测试：覆盖缺口/降级路径/空态诚实返回
- lift_to_multiplier 集成测试：trade_journal 权重读取走 lift_to_multiplier 路径（替代直接读冻结 weight_multiplier），防 R3 写回脱节回归

### P4 UX 打磨

- MarketTreemap 边框/分割色改主题令牌：borderColor '#1a1a2e'→hsl(var(--border))；涨跌热力色(红/绿)保持硬编码（页面约定确认）但可考虑 hsl(var(--danger))/hsl(var(--success)) 族令牌统一步调
- 3 个 intraday 组件空态分 error vs no-data：HoldingsEmotionTable/ScenarioCards/T1ProjectionPanel 当前只分 loading vs empty 不区分 error，补 error 分支
- BombAlertBanner 不静默吞错：`.catch(()=>{})`（line 22/83）静默吞错，error 路径应 surface 非 return null

## 备选为何不选（grill refuted）

- ❌ max_workers 升 2→4：grill 判子进程已绕过串行门，升 4 反增并发 em_get 调用致 IP 风险。约束非缺陷
- ❌ 全扩展 subprocess 隔离到所有 executor：只给 seal_intraday_collect（唯一走 em_get）足够，hithink/tencent 走 per-call timeout 即可，全扩展是过度隔离
- ❌ 修 worldmonitor MCP 握手+SSE：endpoint 不可达（跳过 initialize+SSE），11 fetcher 全 None，修成本高且源价值存疑（AGPL 风险+只作宏观输入之一）。deprecate 优先
- ❌ 在薄数据上立即重建 dual_pressure（用 5min bar 序列）：grill 判 7-10 天 5min 数据上建 seal-detection = 过拟合土壤。须等 30-60 天回补后才重建，短期诚实标 unavailable 比"修"安全
- ❌ T+1 投影改数据驱动（用最后 30min 5min bar 动量替代 +5）：grill 过拟合风险 lens 判 refuted——在薄数据上拟合动量投影仍是过拟合。砍掉不展示假精度更诚实，待 30-60 天回补后再谈数据驱动
- ❌ 裁剪 4 个不可回补 executor（seal/ofi/microstructure/auction）：grill 判"22+天永久丢失后永远到不了§44v2 30-60天门槛"被驳——baostock 5min 可回补价格序列推到门槛，executor 保留继续收集是投资不是负债

## overall（盘中系统整体评估）

盘中层的核心矛盾不是"哪个指标有 alpha"而是"数据覆盖太薄无法判断哪个有 alpha"——5 executor/5 DB/6 endpoint 厚架构跑在 22+ 天永久丢失 + OFI 3%/微结构 19%/封单 31% 的薄地基上。正确优先序是 grill 共识：先稳运行时（Python 3.11.8 venv + per-call 超时根除 stale-reap）→ 诚实移除死代码（dual_pressure 恒 False + T+1 +5 拍脑袋）→ 恢复可回补数据（baostock 5min 是唯一路径，零件全有只差组装）→ 数据可信后接线（4 层按时段门控非等权堆叠）→ OFI/竞价/微结构标探索性不上重方法论。情绪速览条是唯一例外——零成本高收益，与底盘修复并列 P0。

最大未知是 baostock 5min 回补能否补回全部 22 天——hithink limit_up_pool 远期日期支持未实测，且须同步查炸板池（getTopicZBPool 走 em_get）否则结构性丢失炸板未回封事件。回补脚本须先 3 天小批验证再全量。dual_pressure 重建须等 30-60 天回补后，短期诚实标 unavailable 比"修"更安全。
