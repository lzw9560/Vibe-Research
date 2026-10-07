# Spec: S235 — 反量化短线战法集成（三战法+飞书推送+人工确认）

> 状态：**草案v2**（2026-10-07 Oracle grill驳回后修订，11个HIGH全部修复）
> 作者：opencode  日期：2026-10-07
> 关联：S229（§44 v3 anti-fake-edge）、S234（short-term-tactics-filter）、S203（龙头战法数字化改造）、feishu_daily_push.py

## 1. 问题 / 目标

将本次会话**提出**的三大反量化短线战法（反核/尾盘突破/冰点反抽）集成到 Vibe-Research 项目中。三战法基于"不可撤单阶段真实资金动作"和"反量化收割"逻辑，但**未经任何统计验证**——所有阈值参数来自社区经验或本会话推演，非数据回测得出。

**目标：** 不是"实现一个已验证的alpha策略"，而是"搭建一个可审计的探索框架——信号即落库，30笔后做归因对照，能证明有效就继续、不能证明就停"。

## 2. 背景

### 2.1 本会话验证结论（其他策略的证伪结果）

| 策略 | Bootstrap p值 | 判定 | 数据来源 |
|------|-------------|------|---------|
| 笼统跟庄(日K线近似9933事件) | 1.0000 | ❌不显著 | 日K线近似 |
| A组跟庄(真实龙虎榜27只) | 1.0000 | ❌负期望(胜率14.8%) | 真实龙虎榜 |
| 弱转强(119事件) | 0.0930 | ❌不显著 | 日K线 |
| 策略4尾盘错杀(1838事件) | 0.7430 | ❌不显著 | 日K线 |

> **核心教训：没有随机对照组的胜率=确认偏误。三战法在此基础上增加了更严格的因子条件，但更严格=更少信号=更小样本=更难验证。接受这个悖论。**

### 2.2 三战法因子定义

**战法一反核（09:25竞价）：** 前日跌>5% + 09:25高开2-5% + 竞价量比>4.5 + 竞价额占比>10%

**战法二尾盘突破（14:45）：** 站稳VWAP + 换手12-22% + 突破日内高点 + 板块≥2涨停

**战法三冰点反抽（全天）：** 跌停>50家×2日 + 盘中抗跌 + 换手8-15%

### 2.3 阈值来源标注

| 阈值 | 来源 | 标注 |
|------|------|------|
| 量比>4.5 | 社区经验参数 | 探索性参数，禁止production硬编码 |
| 额占比>10% | 社区经验参数 | 探索性参数 |
| 高开2-5% | 社区经验参数 | 探索性参数 |
| 换手12-22% | 社区经验参数 | 探索性参数 |
| 换手8-15%(冰点) | 社区经验参数 | 探索性参数 |
| 跌停>50家×2日 | 社区经验参数 | 探索性参数 |
| 评分阈值60 | 本spec拍脑袋 | 探索性参数 |
| 止损-10%(2×ATR) | 本会话ATR中位4.9%×2 | 有数据支撑 |
| 单票≤1% | 本会话凯利4.5%×0.22 | 有数据支撑（总仓3%÷3只=1%） |

## 3. 需求清单

- [ ] R1：三战法因子计算引擎 — 输入标的代码+数据，输出JSON评分
- [ ] R2：竞价数据集成 — 盘前生成候选池(<200只)，09:20/09:23拉auction-snapshot(live)，09:26拉auction-snapshot(final)
- [ ] R3：尾盘扫描集成 — 14:31/14:46两次拉snapshot，计算VWAP/换手/突破/板块共振
- [ ] R4：冰点检测 — 每日统计跌停家数(用special limit-down-pool，非-9.5%近似)，落库连续2日计数
- [ ] R5：反量化拦截网关 — 对倒检测(均单价偏差)+竞价假抢筹过滤(09:20后量比断崖)+小单偷袭过滤
- [ ] R6：飞书推送新模式 — `--mode tactics --stage auction/reversal/tail_candidate/tail_signal`，错开现有定时
- [ ] R7：信号落库 — 每次触发(含未成交)落库完整因子快照JSON到`.vibe-research/tactics_signals.db`
- [ ] R8：人工确认流程 — 飞书卡片含"看指数30秒"+"看新闻30秒"提醒
- [ ] R9：实盘记录 — 交易记录到`.vibe-research/tactics_journal.db`，含信号价vs实际成交价
- [ ] R10：统计验证标注 — 所有推送标注"探索性，未经Bootstrap验证，≤3%资金跟踪"

## 4. 受影响文件

| 文件 | 改动 | Phase |
|------|------|-------|
| `backend/tactics/__init__.py` | 新建包 | A |
| `backend/tactics/anti_quant_engine.py` | 新建：三战法因子计算引擎 | A |
| `backend/tactics/factor_calculator.py` | 新建：VWAP/换手率/量比/收盘位置比计算 | A |
| `backend/tactics/anti_quant_gateway.py` | 新建：反量化拦截网关 | A |
| `backend/tactics/ice_point_detector.py` | 新建：冰点检测+落库 | A |
| `backend/tactics/signal_store.py` | 新建：信号落库SQLite(含未成交信号) | A |
| `backend/tactics/trade_journal.py` | 新建：实盘记录+信号价vs成交价 | A |
| `backend/tactics/tests/test_*.py` | 新建：单元测试(fixture数据) | A |
| `feishu_daily_push.py` | 新增`--mode tactics --stage X` + 候选池生成 | B |
| `~/Library/LaunchAgents/com.vibe-research.feishu-push-tactics.plist` | 新建定时(09:21/09:26/14:31/14:46) | B |

## 5. 设计方案

### 5.1 候选域设计（修复Oracle阻断2.1）

**问题：** auction-snapshot单次≤100 codes，全市场5000只=50次调用，5分钟内不可行。

**方案：** 盘前(08:30 premarket推送时)生成候选池：

```python
def generate_auction_candidates() -> list[str]:
    """盘前生成竞价候选池(<200只)"""
    # 从前日K线筛选：跌幅>5% 或 炸板 或 连板断板
    all_stocks = get_market_snapshot_all()
    candidates = []
    for s in all_stocks:
        chg = s.get("price_change_ratio_pct")
        if chg is not None and chg < -5:
            candidates.append(s["thscode"])
    # 通常<200只，分2批拉竞价
    return candidates[:200]
```

09:20只拉候选池的竞价数据（200只÷100=2批），5分钟内完成。

### 5.2 评分函数重写（修复Oracle阻断3.4）

**问题：** 原`sum(factors)`异纲量相加（换手率15+量比4.5+bool），数学上无效。

**方案：** 每因子归一化为0-1，预注册权重：

```python
# 硬性前置条件：任一不满足→score强制0，is_triggered=False
HARD_PRECONDITIONS = {
    "reversal": ["prev_drop"],      # 前日必须跌>5%
    "tail_breakout": ["above_vwap"], # 必须站稳VWAP
    "ice_rebound": ["ice_point"],    # 必须冰点期
}

# 软因子权重（硬条件移出后重归一）
FACTOR_WEIGHTS = {
    "reversal": {  # 战法一（prev_drop移出做gate）
        "gap_pct": 0.30,        # 2-5%→1.0, 越偏离越低
        "vol_ratio": 0.30,      # 4.5→1.0, 线性缩放
        "amount_ratio": 0.25,  # 10%→1.0, 线性缩放
        "bid_increasing": 0.15, # bool→0/1
    },
    "tail_breakout": {  # 战法二（above_vwap移出做gate）
        "turnover_rate": 0.25,   # 12-22%→1.0, 区间外线性衰减
        "breakout_high": 0.25,
        "big_order_proxy": 0.10, # 降级因子，权重减半
        "sector_resonance": 0.25,
        "close_position": 0.15,
    },
    "ice_rebound": {  # 战法三（ice_point移出做gate）
        "anti_drop": 0.35,
        "break_vwap": 0.20,
        "turnover_rate": 0.20,
        "bottom_divergence": 0.15, # 降级因子
        "big_order_proxy": 0.10,   # 降级因子
    },
}

def score_tactic(name: str, factors: dict) -> dict:
    # 1. 硬条件veto：任一硬条件归一化值=0→直接否决
    hard = HARD_PRECONDITIONS.get(name, [])
    for h in hard:
        if normalize_factor(h, factors.get(h)) == 0:
            return {
                "is_triggered": False,
                "tactic_name": "None",
                "score": 0,
                "reason": f"硬条件{h}不满足，veto",
                "risk_warning": "不适用（硬条件未通过）",
            }
    # 2. 软因子加权评分
    weights = FACTOR_WEIGHTS[name]
    normalized = {k: normalize_factor(k, factors.get(k)) for k in weights}
    score = sum(normalized[k] * w for k in weights) * 100
    is_triggered = score >= 60  # 探索性阈值，标来源
    return {
        "is_triggered": is_triggered,
        "tactic_name": name if is_triggered else "None",
        "score": int(score),
        "reason": build_reason(normalized, weights),
        "risk_warning": build_risk_warning(name, normalized),
    }
```

> **N1修复说明：** 硬条件(prev_drop/above_vwap/ice_point)从权重表移出做gate，任一不满足→score=0。权重表重归一(三组和均=1.0)。验收A1加反例测试：非冰点日全因子命中不触发、prev_drop=0不触发。

### 5.3 信号落库（修复Oracle阻断3.2+5.2）

**问题：** today-only数据源，信号发出后原始数据蒸发，不可复现。

**方案：** 每次触发(含未成交)落库完整因子快照：

```python
# .vibe-research/tactics_signals.db
CREATE TABLE signals (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,           -- 触发时间
    tactic_name TEXT,         -- 战法名
    code TEXT,                -- 标的代码
    score INTEGER,            -- 评分
    is_triggered INTEGER,     -- 是否触发
    factors_json TEXT,        -- 完整因子快照(JSON)
    raw_data_json TEXT,       -- 原始数据快照(JSON, auction/snapshot原文)
    record_type TEXT DEFAULT 'signal',  -- 'signal'=策略信号 / 'control'=随机对照
    seed INTEGER,              -- 随机对照选取种子(可复现)
    executed INTEGER DEFAULT 0,  -- 是否实际成交
    entry_price REAL,        -- 信号时价格
    fill_price REAL,          -- 实际成交价(如有)
    exit_price REAL,          -- 卖出价
    exit_reason TEXT,         -- 止损/止盈/超时
    hold_days INTEGER,        -- 持有天数
    return_pct REAL,          -- 实际收益
);
CREATE INDEX idx_code ON signals(code);
CREATE INDEX idx_tactic ON signals(tactic_name);
CREATE INDEX idx_record_type ON signals(record_type);
```

> 未成交信号也落库→30笔后做全体样本分析(非仅成交样本)→避免survivorship偏差。
> 对照组：每次信号触发时，同日随机选N只同市值段标的，以record_type='control'落库，seed记录可复现→n≥60时做signal vs control归因对照。

### 5.4 R6成交假设（修复Oracle阻断1.5+我的R6审查）

**问题：** 止损-10%假设按止损价精确成交，但跳空穿仓实际成交=开盘价更差。

**方案：** 止损用realistic gap-through：

```python
def calc_stop_loss(entry_price, stop_pct, next_bar):
    """realistic fill: 跳空穿仓按开盘价成交"""
    stop_price = entry_price * (1 + stop_pct / 100)
    if next_bar['open_price'] <= stop_price:
        # 跳空穿仓，按开盘价成交(更差)
        return next_bar['open_price'], "gap_through"
    elif next_bar['low_price'] <= stop_price:
        # 盘中触及，按止损价成交
        return stop_price, "normal_stop"
    else:
        return None, "no_stop"
```

加滑点0.2-0.5%：`fill_price *= (1 - 0.003)` (卖出滑点)。

### 5.5 Board-aware涨跌停判定（修复Oracle阻断1.4）

**问题：** 用`pct <= -9.5%`判跌停，创业板/科创板20%板会漏判。

**方案：** 用CLI涨跌停池，不用百分比近似：

```python
def count_limit_down() -> int:
    """用CLI涨跌停池统计，不用-9.5%近似"""
    d = run_cli("hithink-finance special limit-down-pool --size 200 --format json 2>/dev/null")
    if d and d.get('ok'):
        return d.get('data',{}).get('pagination',{}).get('total',0)
    return 0
```

### 5.6 09:25板块涨停数因子删除（修复Oracle阻断2.2）

**问题：** 09:25是竞价结束时刻，全市场涨停数=0，因子恒为0。

**方案：** 反核战法删除09:25板块涨停数因子，改用"前日板块强度"：

```python
# 前日板块涨停数（从limit-up-pool取前日数据）
prev_sector_strength = count_prev_day_sector_limit_up(code)
```

### 5.7 定时任务错开（修复Oracle阻断4.1）

| 时间 | 现有任务 | tactics任务 | 错开 |
|------|---------|-----------|------|
| 09:20 | sentiment | — | — |
| 09:21 | — | **tactics --stage auction** | +1min |
| 09:25 | — | — | — |
| 09:26 | — | **tactics --stage reversal** | +1min after 09:25 |
| 14:30 | intraday | — | — |
| 14:31 | — | **tactics --stage tail_candidate** | +1min |
| 14:45 | — | — | — |
| 14:46 | — | **tactics --stage tail_signal** | +1min |
| 14:55 | alert | — | — |

**tmp文件独立命名：** `/tmp/snap_tactics_*.json`，不与`/tmp/snap_push.json`冲突。

### 5.8 候选域缩收后的auction拉取

```python
def fetch_auction_data(candidates: list[str]) -> dict:
    """分批拉竞价数据(每批100)"""
    results = {}
    for i in range(0, len(candidates), 100):
        batch = candidates[i:i+100]
        codes_str = ",".join(batch)
        d = run_cli(f"hithink-finance market auction-snapshot --thscodes {codes_str} --stage live --format json 2>/dev/null")
        if d and d.get('ok'):
            for item in d.get('data',{}).get('item',[]):
                results[item['thscode']] = item
    return results
```

### 5.9 argparse契约（修复Oracle阻断4.3）

```python
parser.add_argument("--mode", choices=["premarket","intraday","postmarket","alert","scan","sentiment","tactics","test"])
parser.add_argument("--stage", choices=["auction","reversal","tail_candidate","tail_signal"], default=None)
parser.add_argument("--force", action="store_true")
```

### 5.10 飞书卡片人工确认提醒

```
📋 执行前确认：
□ 看上证指数（30秒）— 跌>1%减半，跌>2%不买
□ 看新闻标题（30秒）— 确认题材级别
□ 确认后下单 — 单票≤3%，止损-10%(realistic gap-through)
⚠️ 探索性策略，未经Bootstrap验证
```

## 6. 冲突审查表（修复Oracle阻断5.1+6.1）

| 旧spec R-item | 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S229 R1 entry close涨停价filter | 涨停价filter | 战法一买入=竞价价(非涨停价)，但加"竞价价=涨停价时不买"条件；战法二/三加board-aware涨停价filter | 共存 | 复用bar_utils.is_unbuyable_next_bar |
| S229 R2 窗口语义 | 合并R1+R4+R5标注 | 三战法标注edge_type："reversal"/"tail_breakout"/"ice_rebound" | 共存 | 不独立classify，只标注 |
| S229 R3 exit一字跌停 | 单向(is_onesell_locked) | 保留：trade_journal记录exit日四价+is_onesell_locked | 共存 | 复用bar_utils |
| S229 R4 涨停vs未涨停对比 | filter前后对比+样本量check | 信号落库时记录"标的是否涨停/触及涨停"，30笔后做涨停vs未涨停分组归因 | 共存 | signal_store落库 |
| S229 R5 模板样本量check | n<60→underpowered | S235标注"n<30为探索性，30-60为初步评估，≥60才出verdict" | 共存 | 严格遵守n≥60才出verdict |
| S229 R6 成交虚构 | realistic gap-through | 5.4节落地：跳空穿仓按开盘价+滑点0.3% | 共存 | calc_stop_loss函数 |
| S234 R2 战法1/2因子 | 标falsified | **S235 tactics信号强制过S234 short_term_tactics_filter，falsified标注随卡片透出** | **共存(选a)** | tactics→filter→飞书卡片含verdict |
| S203 冻结决议 | milestone pivot冻结新spec | S235头部记录：用户决策(2026-10-07)解冻，用户明确要求实现 | **解冻** | spec头部记录解冻依据 |
| S203 R16 执行层 | 60s轮询延迟不可用 | S235用人工确认(1-3min延迟)，记录信号价vs成交价 | 共存 | trade_journal记录slippage |

## 7. §44 v3 anti-fake-edge sanity（修复Oracle阻断1.1-1.6）

- [ ] **R1 entry涨停价审**：战法一竞价价≠涨停价，但加"竞价价=涨停价→不买"；战法二/三entry加board-aware涨停价filter，复用bar_utils
- [ ] **R2 窗口语义**：三战法标注edge_type(reversal/tail_breakout/ice_rebound)，不独立classify
- [ ] **R3 exit一字跌停**：trade_journal记录exit日is_onesell_locked
- [ ] **R4 涨停vs未涨停对比**：信号落库记录标的是否涨停，30笔后做分组归因+随机对照(同日随机选N只同市值段)
- [ ] **R5 样本量check**：n<30标"探索性不出verdict"，30-60标"初步评估"，≥60才出verdict；filter后样本量check
- [ ] **R6 成交假设虚构**：5.4节gap-through落地，跳空按开盘价+滑点0.3%

## 8. 验收标准

- [ ] A1：`anti_quant_engine.py`三战法评分输出正确JSON（因子归一化+预注册权重）
- [ ] A2：`anti_quant_gateway.py`三道防线正确拦截
- [ ] A3：`feishu_daily_push.py --mode tactics --stage tail_signal --force`成功推送
- [ ] A4：09:21竞价数据拉取成功（10/8开盘后实测延迟）—live-gated
- [ ] A5：14:46尾盘扫描输出≥1只候选或正确报告"无信号"
- [ ] A6：冰点检测用limit-down-pool(非-9.5%)，正确判断非冰点
- [ ] A7：对倒检测正确排除均单价异常标的
- [ ] A8：所有推送含"探索性，未经Bootstrap验证"标注
- [ ] A9：信号落库到`.vibe-research/tactics_signals.db`（含未成交信号+原始快照）
- [ ] A10：`pytest backend/tactics/ -v`通过（fixture数据，非live）
- [ ] A11：S234 filter verdict透出到飞书卡片

## 9. 合规与工程底线自查

- [ ] 研判/推荐属系统能力——标注"探索性，未经统计验证，市场有风险"
- [ ] 判断可复现——信号触发即落库原始JSON到`.vibe-research/`，可审计
- [ ] 涨停池/连板榜属公开客观事实——可呈现
- [ ] 私有数据隔离——`.vibe-research/`(gitignored)
- [ ] 新增东财端点走em_get()限流
- [ ] 所有阈值标来源（社区经验/数据回测/拍脑袋）
- [ ] ≤3%资金跟踪：总仓3%（三战法合计≤总资金3%），单票≤1%（凯利4.5%×0.22≈1%）

## 10. 统计验证状态

| 战法 | Bootstrap p值 | 判定 | 处置 |
|------|-------------|------|------|
| 反核战法 | 未验证(类似弱转强p=0.093) | ❌探索性 | ≤3%资金 |
| 尾盘突破 | 未验证(类似策略4 p=0.743) | ❌探索性 | ≤3%资金 |
| 冰点反抽 | 未验证 | ❌探索性 | ≤3%资金 |

**验证路径：** 信号落库→累计≥60笔→做R4涨停vs未涨停分组归因+随机对照→出verdict

> **悖论接受：因子越严格→信号越少→样本越小→越难统计验证。标注"探索性"，n≥60才出verdict。**

## 11. 分阶段交付（修复Oracle阻断3.3）

### Phase A（可合并，fixture数据）
- anti_quant_engine.py（因子计算+评分）
- anti_quant_gateway.py（反量化网关）
- factor_calculator.py
- ice_point_detector.py
- signal_store.py（落库）
- trade_journal.py
- 单元测试(fixture)
- 评分数学习正确性测试

### Phase B（live-gated，10/8冒烟后合）
- feishu_daily_push.py新增tactics模式
- 竞价数据拉取(auction-snapshot)
- 定时任务plist
- 候选池生成
- 10/8实测CLI延迟+字段完整性

## 12. 测试计划

- [ ] `pytest backend/tactics/ -v` — Phase A单元测试(fixture数据)
- [ ] `python3 feishu_daily_push.py --mode tactics --stage tail_signal --force` — Phase B冒烟
- [ ] 10/8开盘后实测竞价数据延迟和字段

## 13. 风险与回滚

| 风险 | 影响 | 回滚 |
|------|------|------|
| 竞价数据延迟>30秒 | 反核战法降级为半自动 | 人工看盘09:20-09:25 |
| 降级代理选入量化对倒 | 亏损 | 对倒检测+均单价方差排除 |
| 策略统计不显著 | 亏损 | ≤3%资金，n≥60后评估 |
| 飞书推送失败 | 信号遗漏 | 日志告警+手动触发 |
| S234 verdict矛盾 | 用户困惑 | 飞书卡片同时显示tactics评分+S234 verdict |
