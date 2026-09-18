# S211 tasks · consecutive_relay arm 接线 checklist

> TDD：test 先（RED）→ 实现（GREEN）→ 验收

## T1 evaluation: regime-stratified cap
- [ ] T1.1 test: DIMENSION_LIFT_REGISTRY 有 consecutive_relay entry（regime_caps）
- [ ] T1.2 test: lift_for_arm("consecutive_relay", regime="bull") 返 1.0
- [ ] T1.3 test: lift_for_arm("consecutive_relay", regime="bear") 返 0.5
- [ ] T1.4 test: lift_for_arm("consecutive_relay", regime=None) 返 0.5（保守）
- [ ] T1.5 实现: DIMENSION_LIFT_REGISTRY + lift_for_arm regime 参数

## T2 paper_portfolio: final_size regime
- [ ] T2.1 test: final_size("consecutive_relay", base, regime="bull") 用 ×1.0
- [ ] T2.2 test: final_size regime=None 用保守 ×0.5
- [ ] T2.3 实现: final_size 加 regime 参数（透传 lift_for_arm）

## T3 journal_recorder: _process + settle
- [ ] T3.1 test: _process_consecutive_relay overnight gap return 对（D 收→D+1 开）
- [ ] T3.2 test: D 日一字板 filter（不买）
- [ ] T3.3 test: settle_pending_consecutive_relay D+1 open 平仓
- [ ] T3.4 test: _arm_size("consecutive_relay", regime="bull") bite ×1.0
- [ ] T3.5 实现: _process_consecutive_relay + settle_pending + DEFAULT_ARMS + _arm_size regime

## T4 验收
- [x] T4.1 DEFAULT_ARMS 含 consecutive_relay
- [x] T4.2 全 test 回归 0 break
- [x] T4.3 memory 更新（consecutive_relay arm 接线 + verdict→sizing 闭环）

## T5 生产通电收尾（2026-09-17 commit 1b9a4c2，深度审查后半闭环修复）

深度审查（10-agent workflow wc419jans）发现 S211 arm 接线完成但生产 cron 不跑——半闭环：
code/test 接线全真（18 test 绿）但 scheduler/executors/journal.py:42 硬编码 arms=["floor","breakout","trend"]
不含 consecutive_relay → 唯一已证 edge arm 从 dormant。4 专家共识 + 用户定（仓位 0.5 / ST 新规 10%）后收尾：

- [x] T5.1 bars_provider 生产接 enrich_pctchg（堵一字板假交易，守不臆造底线——风险专家承重断言 grep 核实）
- [x] T5.2 is_unbuyable ST 新规：去掉 5% ST 特殊阈值 + isST 字段读取，ST 股按 board（10/20/30%）——根除 baostock isST 91% 缺失误判（lbc>=2 实测 0 ST，新规对 consecutive_relay no-op 但根除其他战法 139 板 ST 残留）
- [x] T5.3 scan_consecutive_relay 加 lbc<=3 上界（砍 lbc>=4 死 edge -0.02%，过滤 193 个高位连板；lbc=3 是甜点 +2.05%）
- [x] T5.4 consecutive_relay bull cap 1.0→0.5 provisional（综合 refuted 4真3假保守，待 60 天 forward OOS 升 ×1.0）——**T2.1/T3.4 变更：bull ×1.0 → ×0.5**
- [x] T5.5 overnight_gap_decomposition 接 enrich（补第 7 bypass——7e75465 接 6 harness 漏此；reframe 隔夜 gap 核心数干净，只有被否掉的 path 窗口受污染，不翻案）
- [x] T5.6 journal.py:42 arms 加 consecutive_relay（开关打开，arm 从 dormant 转活）
- [x] T5.7 smoke test 真链路通（tmp db，真 bars_provider + 真 zt_history）：8 picks → 7 realized + 1 unbuyable（一字板 filter 拦）+ regime cap bite 50 股（position 482=9.64×50 非 100）
- [x] T5.8 146 相关 test green（test_s211 18 + engine + bars_provider + s203 + s205 + s144 + scheduled_tasks + data_honesty + s209）

**待办**（不阻塞通电，fork agent 并行处理中）：
- [ ] T5.9 regime cache 滞后（index_ma20_regime.json 到 09-04）→ regime-cache agent 刷新中；升 ×1.0 前必须修（否则 bull 被当 None 误保守）
- [ ] T5.10 K 线 cache 滞后（baostock_kline_cache.json 到 09-11）→ kline-refresh agent 增量补中
- [ ] T5.11 lbc=3 积累 60 天 forward OOS（现 ~33 天，每日 +1，~27 天到 60）→ 转 verdict 升 ×1.0
- [ ] T5.12 知识图谱同步（S203-S212 spec 实体缺）→ kg-sync agent 写中

**consecutive_relay arm 现状**：从"装好没通电"→"通电跑起来"。唯一已证 edge arm 生产 active，bull ×0.5 provisional 保守部署。
