# Tasks: S235 — 反量化短线战法集成

> 状态：Phase A 已实现（2026-10-07），Phase B 待 10/8 开盘
> 分支：`feature/S235-anti-quant-tactics`
>
> 偏离 spec 的实现决策（§0 决策框架"先搜后写—有约定就遵循"）：
> - 测试位置：spec 写 `backend/tactics/tests/`，实际放 `backend/tests/test_tactics_*.py`
>   （项目 testpaths=testpaths + --cov-fail-under=50 全局 addopts，独立子目录会 tank 覆盖门）
> - T08 fixtures：延后至 Phase B（当前测试用 inline 数据，fixture 无测试加载=死文件，YAGNI）

## Phase A：可合并（fixture数据，不依赖live）

### Wave 1：基础包+独立模块（可并行）

- [x] T01 创建`backend/tactics/__init__.py`空包
  - 完成判据：`python3 -c "import backend.tactics"`不报错
  - 依赖：无

- [x] T02 `factor_calculator.py` — 因子计算函数集
  - 完成判据：以下函数可独立调用且返回数值
    - [ ] `calc_vwap(snapshot)` → (open+high+low+2*close)/4
    - [ ] `calc_turnover_rate(snapshot)` → 成交额/流通市值
    - [ ] `calc_vol_ratio(auction_data, prev_5d_open_volumes)` → 竞价量/5日均量
    - [ ] `calc_amount_ratio(auction_data, prev_day_turnover)` → 竞价额/前日成交额
    - [ ] `calc_close_position(snapshot)` → (close-low)/(high-low)
    - [ ] `calc_prev_drop(prev_klines)` → 前日跌幅
    - [ ] `normalize_factor(name, value)` → 归一化分发表，每因子独立逻辑
  - 依赖：T01

- [x] T04 `anti_quant_gateway.py` — 反量化拦截网关
  - 完成判据：三道防线可独立调用
    - [ ] `check_auction_fake(live_1, live_2)` → bool（09:20后量比断崖）
    - [ ] `check_tail_fake(snapshot)` → bool（成交额<5000万）
    - [ ] `check_wash_trading(snapshot)` → bool（均单价偏差>5%）
  - 依赖：T01

- [x] T05 `ice_point_detector.py` — 冰点检测
  - 完成判据：
    - [ ] `count_limit_down()` → 用`special limit-down-pool`(非-9.5%)，返回int
    - [ ] `is_ice_point()` → 连续2日跌停>50家，从落库历史读取
    - [ ] 首日无历史时`is_ice_point()`返回False
  - 依赖：T01

- [x] T06 `signal_store.py` — 信号落库SQLite
  - 完成判据：
    - [ ] 建表SQL含`record_type`+`seed`+3个索引
    - [ ] `save_signal(...)`写入signal行
    - [ ] `save_control_group(signal_code, all_stocks, n=5)`随机选+写入control行
    - [ ] `get_signals(tactic, min_n=60)`查询
    - [ ] `get_control_group(date, tactic)`查询
  - 依赖：T01

- [~] T08 录制fixture数据（延后 Phase B：当前 inline 测试数据够用，无测试加载=死文件 YAGNI）
  - 完成判据：4个JSON文件存在且格式正确
    - [ ] `tests/fixtures/auction_snapshot_live.json` — 竞价live快照mock
    - [ ] `tests/fixtures/auction_snapshot_final.json` — 竞价final快照mock
    - [ ] `tests/fixtures/market_snapshot_sample.json` — 全市场快照mock(20只)
    - [ ] `tests/fixtures/limit_up_pool_sample.json` — 涨停池mock
  - 依赖：T01

### Wave 2：依赖Wave 1的模块

- [x] T03 `anti_quant_engine.py` — 三战法引擎
  - 完成判据：
    - [ ] `HARD_PRECONDITIONS`三战法各列硬条件
    - [ ] `FACTOR_WEIGHTS`三组权重和均=1.0（硬条件移出后重归一）
    - [ ] `evaluate_reversal(code, prev_klines, auction_1, auction_2, auction_final)` → JSON
    - [ ] `evaluate_tail_breakout(code, snapshot, limit_up_pool)` → JSON
    - [ ] `evaluate_ice_rebound(code, snapshot, market_stats, prev_snapshot)` → JSON
    - [ ] `_veto_check(tactic, factors)` → 硬条件任一=0→score=0
    - [ ] `_build_control_group(signal_code, signal_mc, all_stocks, n=5)` → list
    - [ ] 输出JSON含is_triggered/tactic_name/score/reason/risk_warning
  - 依赖：T02（factor_calculator）

- [x] T07 `trade_journal.py` — 实盘记录
  - 完成判据：
    - [ ] `save_trade(signal_id, entry_price, fill_price, ...)`记录
    - [ ] `calc_stop_loss(entry, stop_pct, next_bar)` → realistic gap-through
    - [ ] 滑点0.3%：`fill_price *= (1 - 0.003)`
    - [ ] `get_trade_pnl(signal_id)` → 收益率
  - 依赖：T06（signal_store）

### Wave 3：测试（依赖Wave 2）

- [x] T09 `test_anti_quant_engine.py`（实为 test_tactics_anti_quant_engine.py，位置按项目约定 backend/tests/）
  - 完成判据：
    - [ ] 反例1：非冰点日全因子命中→ice_rebound不触发
    - [ ] 反例2：prev_drop=0→reversal不触发
    - [ ] 正例：全因子命中→触发
    - [ ] 权重和=1.0断言
    - [ ] veto优先于评分断言
  - 依赖：T03

- [x] T10 `test_factor_calculator.py`（实为 test_tactics_factor_calculator.py）
  - 完成判据：
    - [ ] VWAP边界值（全高价/全低价）
    - [ ] 换手率区间归一化边界（12%/22%/区间外）
    - [ ] 量比4.5→1.0/2.0→0.44线性
    - [ ] gap_pct 2%→1.0/5%→1.0/1%→0/6%→0
    - [ ] close_position 0.7→1.0/0.3→0.43
  - 依赖：T02

- [x] T11 `test_anti_quant_gateway.py`（实为 test_tactics_anti_quant_gateway.py）
  - 完成判据：
    - [ ] 竞价假抢筹：live_1>live_2×0.5→True
    - [ ] 尾盘偷袭：turnover<5000万→True
    - [ ] 对倒检测：均单价偏差>5%→True
    - [ ] 正常标的→False
  - 依赖：T04

- [x] T12 `test_signal_store.py`（实为 test_tactics_signal_store.py）
  - 完成判据：
    - [ ] 写入signal行+读取
    - [ ] 写入control行+读取
    - [ ] seed可复现
    - [ ] min_n=60过滤
  - 依赖：T06

### Wave 4：全量验证

- [ ] T13 `pytest backend/tactics/ -v`全部通过
  - 完成判据：0失败
  - 依赖：T09+T10+T11+T12

---

## Phase B：live-gated（10/8开盘后）

- [ ] T14 实测CLI竞价数据延迟+字段
  - 完成判据：
    - [ ] `auction-snapshot --stage live`延迟<30秒
    - [ ] `auction-snapshot --stage final`延迟<30秒
    - [ ] 返回字段含成交量+成交额+开盘价
    - [ ] 换手率/流通股本字段口径确认
  - 依赖：T13
  - 10/8开盘09:20执行

- [ ] T15 候选池生成函数
  - 完成判据：
    - [ ] 用`market history`拉前日K线（非当日snapshot）
    - [ ] 跌幅>5%+炸板池(`limit-break-pool`)+连板断板
    - [ ] 按|跌幅|降序截断前200只
    - [ ] 输出到`/tmp/snap_candidates.json`（独立路径）
  - 依赖：T14

- [ ] T16 竞价数据分批拉取
  - 完成判据：
    - [ ] 200只÷100=2批<5分钟
    - [ ] 09:21拉live + 09:23拉live + 09:26拉final
  - 依赖：T15

- [ ] T17 `feishu_daily_push.py`加`--mode tactics --stage X`
  - 完成判据：
    - [ ] argparse新增`tactics` mode + `--stage` choices
    - [ ] `--stage auction`→拉竞价+防线检查
    - [ ] `--stage reversal`→反核评分+落库+飞书推送
    - [ ] `--stage tail_candidate`→尾盘候选扫描
    - [ ] `--stage tail_signal`→尾盘评分+落库+推送
    - [ ] S234 verdict透出到卡片
    - [ ] 人工确认提醒（看指数+看新闻）
    - [ ] "探索性，未经验证"标注
  - 依赖：T16+T03+T04

- [ ] T18 S234 filter接线
  - 完成判据：
    - [ ] `TACTIC_TO_S234`映射表定义
    - [ ] `safe_action=Block`→信号压制不推送（仍落库标suppressed）
    - [ ] 冰点反抽→仅过第一层财务过滤
  - 依赖：T17

- [ ] T19 定时任务plist
  - 完成判据：
    - [ ] `com.vibe-research.feishu-push-tactics.plist`创建
    - [ ] 4个job：09:21+09:26+14:31+14:46
    - [ ] 独立tmp路径`/tmp/snap_tactics_*`
    - [ ] `launchctl load`成功
  - 依赖：T17

- [ ] T20 `--mode tactics --stage tail_signal --force`冒烟
  - 完成判据：飞书收到卡片+JSON格式正确
  - 依赖：T17+T19

- [ ] T21 `launchctl list | grep tactics`确认
  - 完成判据：4个job状态正常
  - 依赖：T20

---

## Backlog（MEDIUM，不阻断Phase A/B）

| ID | 问题 | 修复时机 |
|----|------|---------|
| N2 | 孤儿因子prev_sector_strength | T03实现时决定：进权重或删 |
| N5 | S234 filter映射+Block语义 | T18 |
| N6 | 额占比分母+换手率单位 | T14实测确认 |
| N7 | tasks已写（本文件）+分支名已声明 | — |
| N8 | 候选池加炸板+排序 | T15 |
| N9 | n门槛统一为60 | spec已修 |
| N10 | calc_stop_loss复用S229 | T07实现时评估 |
| N11 | edge_type改名tactic_id | T03实现时 |
