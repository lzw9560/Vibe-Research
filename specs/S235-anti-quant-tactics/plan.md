# Plan: S235 — 反量化短线战法集成

> 状态：草案
> 分支：`feature/S235-anti-quant-tactics`
> 关联：spec.md（v2.1，Oracle grill复审通过，3个HIGH已修）

## 技术方案

### 架构总览

```
backend/tactics/                    ← 新建包
├── __init__.py
├── anti_quant_engine.py            ← 三战法因子计算+评分
├── factor_calculator.py            ← VWAP/换手率/量比/收盘位置比
├── anti_quant_gateway.py           ← 反量化拦截(对倒+竞价假抢+小单偷袭)
├── ice_point_detector.py           ← 冰点检测+落库
├── signal_store.py                 ← 信号落库SQLite(含对照组)
├── trade_journal.py                ← 实盘记录+slippage
└── tests/
    ├── test_anti_quant_engine.py
    ├── test_factor_calculator.py
    ├── test_anti_quant_gateway.py
    ├── test_signal_store.py
    └── fixtures/                   ← 录制的mock数据
        ├── auction_snapshot_live.json
        ├── auction_snapshot_final.json
        ├── market_snapshot_sample.json
        └── limit_up_pool_sample.json

feishu_daily_push.py                ← 新增--mode tactics --stage X
~/Library/LaunchAgents/com.vibe-research.feishu-push-tactics.plist  ← Phase B

.vibe-research/tactics_signals.db   ← 信号+对照组落库
.vibe-research/tactics_journal.db   ← 实盘记录
```

### 数据流

```
盘前08:30 premarket → 全市场snapshot落/tmp/snap_push.json
         ↓
候选池生成 → /tmp/snap_candidates.json（前日跌>5%标的，<200只）
         ↓
09:21 tactics --stage auction → 拉200只竞价live快照(2批×100)
         ↓
09:23 tactics --stage auction → 第二次live快照（对比委买单）
         ↓
09:26 tactics --stage reversal → 拉200只竞价final快照 → 反核评分
         ↓
信号落库(.vibe-research/tactics_signals.db)
         ↓
飞书推送(含S234 verdict透出)
         ↓
人工确认(看指数30秒+看新闻30秒) → 下单 → trade_journal记录
         ↓
14:31 tactics --stage tail_candidate → 全市场扫描(VWAP+换手+板块)
         ↓
14:46 tactics --stage tail_signal → 尾盘突破评分
         ↓
信号落库+飞书推送+人工确认
```

### 复用现有基建（不重造）

| 现有模块 | 复用点 | 不改 |
|---------|--------|------|
| `backend/engine/bar_utils.py` | `is_unbuyable_next_bar`/`is_onesell_locked_next_bar` | 不改 |
| `backend/tools/short_term_tactics_filter.py` | `filter_stock(code, tactic)` → S234 verdict透出 | 不改 |
| `feishu_daily_push.py` | `run_cli()`/`send_feishu()`/`get_index_snapshot()` | 新增mode不改现有 |
| `.vibe-research/` | 数据隔离目录 | 不改 |
| `hithink-finance CLI` | 行情/龙虎榜/涨停池/竞价快照 | 不改 |

### 新建模块设计

#### anti_quant_engine.py

```python
class AntiQuantEngine:
    def evaluate_reversal(self, code, prev_klines, auction_live_1, auction_live_2, auction_final) -> dict:
        """战法一：反核 — 硬条件prev_drop veto + 4软因子加权"""
        
    def evaluate_tail_breakout(self, code, snapshot, limit_up_pool) -> dict:
        """战法二：尾盘突破 — 硬条件above_vwap veto + 5软因子加权"""
        
    def evaluate_ice_rebound(self, code, snapshot, market_stats, prev_snapshot) -> dict:
        """战法三：冰点反抽 — 硬条件ice_point veto + 5软因子加权"""
        
    def _normalize(self, factor_name, raw_value) -> float:
        """因子归一化为0-1，每因子有独立归一化函数"""
        
    def _veto_check(self, tactic_name, factors) -> bool:
        """硬条件veto：任一硬条件=0→直接否决"""
        
    def _build_control_group(self, signal_code, signal_market_cap, all_stocks, n=5) -> list:
        """随机选N只同市值段标的做对照组"""
```

#### factor_calculator.py

```python
def calc_vwap(snapshot) -> float:
    """VWAP近似 = (open + high + low + 2*close) / 4"""

def calc_turnover_rate(snapshot, float_share=None) -> float:
    """换手率 = 成交额/流通市值（流通股本需从snapshot推断或外部传入）"""

def calc_vol_ratio(auction_data, prev_5d_open_volumes) -> float:
    """竞价量比 = 竞价成交量 / 过去5日开盘均量"""

def calc_amount_ratio(auction_data, prev_day_turnover) -> float:
    """竞价额占比 = 竞价成交额 / 前日全天成交额"""

def calc_close_position(snapshot) -> float:
    """收盘位置比 = (close - low) / (high - low)"""

def calc_prev_drop(prev_klines) -> float:
    """前日跌幅 = (前日close - 前日prev_close) / 前日prev_close"""

def normalize_factor(name, value) -> float:
    """归一化分发表 — 每因子独立归一化逻辑"""
    NORMALIZERS = {
        "prev_drop": lambda v: 1.0 if v <= -5 else 0.0,
        "gap_pct": lambda v: 1.0 if 2 <= v <= 5 else max(0, 1 - abs(v - 3.5) / 3.5),
        "vol_ratio": lambda v: min(1.0, v / 4.5),
        "amount_ratio": lambda v: min(1.0, v / 0.10),
        "bid_increasing": lambda v: 1.0 if v else 0.0,
        "above_vwap": lambda v: 1.0 if v else 0.0,
        "ice_point": lambda v: 1.0 if v else 0.0,
        "turnover_rate": lambda v: 1.0 if 0.12 <= v <= 0.22 else ...,
        "breakout_high": lambda v: 1.0 if v >= 0.995 else v,
        "close_position": lambda v: min(1.0, v / 0.7),
        ...
    }
```

#### anti_quant_gateway.py

```python
class AntiQuantGateway:
    def check_auction_fake(self, live_1, live_2) -> bool:
        """防线1：竞价假抢筹 — 09:20后量比断崖"""
        
    def check_tail_fake(self, snapshot) -> bool:
        """防线2：尾盘小单偷袭 — 成交额<5000万"""
        
    def check_wash_trading(self, snapshot) -> bool:
        """防线3：对倒检测 — 均单价偏差>5%"""
```

#### signal_store.py

```python
class SignalStore:
    def __init__(self, db_path=".vibe-research/tactics_signals.db"):
        ...
    
    def save_signal(self, tactic, code, score, is_triggered, factors_json, raw_data_json,
                    record_type="signal", seed=None, entry_price=None):
        """落库信号或对照组"""
        
    def save_control_group(self, signal_code, all_stocks, n=5):
        """随机选N只同市值段+落库为control"""
        
    def get_signals(self, tactic=None, min_n=60) -> list:
        """查询信号用于归因分析"""
        
    def get_control_group(self, date, tactic) -> list:
        """查询对照组"""
```

### S234 filter映射表（修复N5）

```python
TACTIC_TO_S234 = {
    "reversal": "战法1_弱转强",       # 反核 → S234战法1
    "tail_breakout": "战法2_尾盘锁定",  # 尾盘突破 → S234战法2
    "ice_rebound": None,               # 冰点反抽 → S234无对应，仅过第一层财务过滤
}

def apply_s234_filter(code, tactic_name):
    """过S234 filter，返回verdict"""
    s234_tactic = TACTIC_TO_S234.get(tactic_name)
    if s234_tactic is None:
        # 冰点反抽：只过第一层财务硬过滤
        return {"safe_action": "Pass", "verdict": "财务过滤only"}
    result = short_term_tactics_filter.filter_stock(code, s234_tactic)
    # safe_action=Block → 信号压制不推送（仍落库标suppressed）
    return result
```

## Phase A 任务分解（可合并，fixture数据）

| 序号 | 任务 | 依赖 | 完成判据 |
|------|------|------|---------|
| A1 | 创建`backend/tactics/`包+`__init__.py` | — | 目录存在 |
| A2 | `factor_calculator.py` | A1 | 所有calc_*函数+normalize_factor分发表 |
| A3 | `anti_quant_engine.py` | A2 | 三战法evaluate_*方法+veto_check |
| A4 | `anti_quant_gateway.py` | A1 | 三道防线check_*方法 |
| A5 | `ice_point_detector.py` | A1 | 用limit-down-pool计数+落库 |
| A6 | `signal_store.py` | A1 | SQLite建表+save/get+对照组+索引 |
| A7 | `trade_journal.py` | A6 | 实盘记录+gap-through止损+slippage |
| A8 | 录制fixture数据 | A1 | 4个JSON mock文件 |
| A9 | `test_anti_quant_engine.py` | A3 | 含N1反例测试(非冰点不触发+prev_drop=0不触发) |
| A10 | `test_factor_calculator.py` | A2 | 归一化边界值测试 |
| A11 | `test_anti_quant_gateway.py` | A4 | 三防线拦截测试 |
| A12 | `test_signal_store.py` | A6 | 信号+对照组读写测试 |
| A13 | `pytest backend/tactics/ -v` | A9-A12 | 全部通过 |

## Phase B 任务分解（live-gated，10/8冒烟后）

| 序号 | 任务 | 依赖 | 完成判据 |
|------|------|------|---------|
| B1 | 候选池生成函数 | A13 | 前日跌>5%标的<200只+排序 |
| B2 | 竞价数据拉取(分批100) | B1 | 2批×100完成<5分钟 |
| B3 | `feishu_daily_push.py`加`--mode tactics --stage X` | B2+A3 | argparse契约+飞书推送 |
| B4 | S234 filter接线+verdict透出 | B3+A4 | 映射表+Block压制语义 |
| B5 | 定时任务plist(09:21/09:26/14:31/14:46) | B3 | 4个job+独立tmp路径 |
| B6 | 10/8实测CLI延迟+字段完整性 | B2 | auction-snapshot字段确认+延迟<30秒 |
| B7 | `--mode tactics --force`冒烟 | B3+B6 | 飞书推送成功 |
| B8 | `load plist`定时任务 | B7 | launchctl list确认 |

## 执行顺序

```
Phase A（本周内，可并行）:
  A1 → A2+A4+A5+A6（并行）→ A3（依赖A2）→ A7（依赖A6）
  A8（录制fixture，可与A2并行）
  A9-A12（测试，依赖各自模块）→ A13（全量pytest）

Phase B（10/8开盘后）:
  B6（实测）→ B1+B2（并行）→ B3 → B4 → B5 → B7 → B8
```

## 风险

| 风险 | 缓解 |
|------|------|
| auction-snapshot字段不符预期 | B6实测确认，不符则降级为半自动 |
| 候选池>200只 | 按|跌幅|降序截断前200 |
| S234 filter签名变更 | 用try/except兜底 |
| bar_utils接口变更 | 复用不改，如改则spec冲突审查 |
