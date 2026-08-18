# 技术方案 · S079 打板 P2 仓位闸 + 龙虎榜黑名单

> 对应 spec：`specs/S079-打板P2战法与仓位闸/spec.md`（草案）
> 性质：技术实现方案（受 `CLAUDE.md` §0 SDD 约束，文件/函数级设计）
> 作者：Claude ｜ 日期：2026-08-18
> 分级：**large**（碰外部数据源 datacenter 龙虎榜 + 仓位闸熔断，按 AGENTS.md 自动 large）

---

## 0. 依据与复用清单

| spec 要求 | 复用的现有能力（不重造） |
|---|---|
| R1 龙虎榜取数 | `seat_engine/service.py:231 SeatEngine.compute_consensus_signal(trade_date, stock_code)`（返回 buy_seats/sell_seats/total_buy_amount 等）+ `hot_money_seats.py:95 fetch_billboard_for_date(trade_date)`（datacenter 通道）|
| R2 黑名单硬剔除 | 新增 `backend/dragon_tiger_seat_filter.py` + `config/seat_blacklist.yaml`，复用 `compute_consensus_signal` 的 buy_seats 做子串模糊匹配 + 占比计算 |
| R3 独食独大软标记 | 复用 `compute_consensus_signal` 的 buy_seats[0] 计算买一占比，扩展 `seat_engine/service.py` 输出 buy_one_ratio 字段；复用 `hot_money_seats.py:57 SeatRiskFactor` 基础 |
| R4 散户霸榜软标记 | 复用 `compute_consensus_signal` 的 buy_seats 做拉萨席位子串匹配计数；复用 `hot_money_seats.day_trip_ratio` 基础扩展 |
| R5 数据缺失处置 | 复用 `compute_consensus_signal` 返回 None / signal="未取得" 时标"席位风控数据未取得"，硬剔除不可执行 |
| R6 _market_phase 扩展 | 修改 `first_board_filter.py:100 _market_phase(zt_count)`，加默认参数扩展为 4 因子 + 红期硬熔断覆盖；保留旧签名向后兼容（line 1341 score_candidate 调用不破坏）|
| R7 cap_by_market_phase 后处理 | 修改 `position_advisor.py` 加 `cap_by_market_phase(positions, phase)` 函数，叠加在 `advise_batch`（line 137）输出之上；不修改既有 advise/advise_batch 签名 |
| R8 STI 时序分离 | 文档层声明，不改代码（STI 是 T-1 盘后总结，_market_phase 是 T+1 盘前仓位闸因子）|
| R9 信号输出 | 复用 `pre_market_workflow.py` 既有链路（line 96-97 实例化，line 124 match，line 150 advise_batch），在 advise_batch 后串两层后处理 |
| R10 checklist 推送 | 复用既有飞书推送通道 + `routers/workflow.py` 既有 `/api/workflow/pre-market` 端点，响应加字段，不新增端点 |
| 限流/熔断 | `hot_money_seats.py:75` datacenter 通道需核实是否需 em_get 防护（AC6）|
| 验算工具 | `~/tools/financial_rigor.py`（AC8 阈值复算 + 触发频率统计）|

**新增**：`dragon_tiger_seat_filter.py`（龙虎榜三分级风控）+ `config/seat_blacklist.yaml`（黑名单配置）+ `_market_phase` 扩展 + `cap_by_market_phase` 后处理 + 前端仓位闸/风控标记展示。
**不新增**：数据层（S070/S080）、战法匹配扩展（S081）、akshare 龙虎榜通道、新路由端点、新状态机概念。

---

## 1. 目录结构

### 1.1 后端新增/改动

```
backend/
├── strategies/
│   ├── first_board_filter.py        # 【修改】_market_phase 扩展 4 因子 + 红期硬熔断覆盖（R6）
│   ├── position_advisor.py          # 【修改】加 cap_by_market_phase 后处理函数（R7）
│   └── hot_money_seats.py           # 【修改】处置"绕过 em_get"问题（AC6），核实/套限流
├── seat_engine/
│   └── service.py                  # 【修改】compute_consensus_signal 输出加 buy_one_ratio 字段（R3）
├── dragon_tiger_seat_filter.py     # 【新增】龙虎榜席位三分级风控（R1-R5）
├── pre_market_workflow.py          # 【修改】在 advise_batch 后串 DragonTigerSeatFilter + cap_by_market_phase（R9）
├── routers/
│   └── workflow.py                  # 【修改】/api/workflow/pre-market 响应加 market_phase_cap + risk_flags（R10）
└── (既有 routers/limitup/seats.py 不改，复用 /api/limitup/seats/*)
```

### 1.2 配置新增

```
config/
└── seat_blacklist.yaml             # 【新增】黑名单席位名单 + 阈值可配（R2.1）
```

### 1.3 前端改动

```
frontend/src/
├── pages/
│   └── Workflow.tsx                # 【修改】pre-market 报告展示仓位上限 + 龙虎榜风控标记 + 人工 checklist
└── lib/
    └── api.ts                      # 【修改】pre-market 响应类型加 market_phase_cap + risk_flags 字段
```

### 1.4 文档改动

```
docs/
└── limitup-design.md                # 【修改】标注"策略逻辑教育展示定位"段落 supersede（T6，不阻断）
```

---

## 2. 实现步骤（R1-R10 逐条）

### 总体架构（spec §5.1 两层后处理）

```
[既有 pre_market_workflow.py 链路，本 spec 不改既有调用]
候选池 → StrategyMatcher.match → PositionAdvisor.advise_batch(weather_state)
                ↓ position_suggestions (list[PositionSuggestion])
        ┌───────────────────────────────────────────┐
        │ 1. DragonTigerSeatFilter（新增）          │
        │    龙虎榜席位三分级（R1-R5）              │
        │    输入：suggestions + T-1 龙虎榜         │
        │    复用：seat_engine + hot_money_seats   │
        │    输出：硬剔除后标的 + risk_flags        │
        └───────────────────────────────────────────┘
                ↓
        ┌───────────────────────────────────────────┐
        │ 2. cap_by_market_phase（新增后处理）      │
        │    输入：标的 + T+1 _market_phase         │
        │    叠加：min(weather_cap,                │
        │           market_phase_cap,              │
        │           max_total_position)            │
        │    输出：标的 + 仓位上限 + risk_flags     │
        └───────────────────────────────────────────┘
                ↓
        推送飞书/弹窗 + 人工执行 checklist（R10）
```

> **串行链**：两层为串行依赖（龙虎榜风控 → 仓位闸）。回滚策略见 spec §9。

---

### R1：龙虎榜取数（复用 seat_engine）

**复用点**：
- `backend/seat_engine/service.py:231` `SeatEngine.compute_consensus_signal(trade_date, stock_code)`
  - 返回结构：`{signal, details:{buy_seats, sell_seats, institution_buy_amt, total_buy_amount, ...}}`
  - `buy_seats` 是 `list[{name, buy_amt, sell_amt, net, seat_type}]`
- `backend/strategies/hot_money_seats.py:95` `fetch_billboard_for_date(trade_date)`（datacenter 通道，作为聚合/fallback）

**实现要点**：
- 龙虎榜取数统一走 `seat_engine.compute_consensus_signal`，不新增 akshare 通道（spec §2.2 冲突 3 处置）
- `trade_date` 取 T-1 交易日（龙虎榜为盘后数据，T+1 盘前使用）
- 取数失败时返回 None / signal="未取得"，交由 R5 处置

---

### R2：黑名单硬剔除（新增 dragon_tiger_seat_filter.py + config）

**新增文件**：`backend/dragon_tiger_seat_filter.py`

**核心函数签名**：

```python
def filter_by_blacklist(
    suggestions: list[PositionSuggestion],
    blacklist_config: dict,
    trade_date: str,
    seat_engine: SeatEngine,
) -> tuple[list[PositionSuggestion], dict[str, list[str]]]:
    """
    R2 黑名单硬剔除。
    
    输入：
      suggestions: PositionSuggestion 列表（含 stock_code 字段）
      blacklist_config: seat_blacklist.yaml 解析后的配置（含 blacklist 席位名单 + 阈值）
      trade_date: T-1 交易日
      seat_engine: SeatEngine 实例（复用，不新建）
    
    输出：
      filtered: 硬剔除后的 PositionSuggestion 列表
      risk_flags: {stock_code: ["【拒绝介入】黑名单占比 X%"]}（被剔除标的的风控标记）
    """
```

**实现逻辑**：

1. **对每个 suggestion**，调 `seat_engine.compute_consensus_signal(trade_date, suggestion.stock_code)` 取 `buy_seats` + `total_buy_amount`
2. **子串模糊匹配**（R2.2，应对"中国国际金融上海分公司" vs "中金公司上海分公司"写法差异）：
   - 对 `blacklist_config["blacklist"]` 中每个黑名单席位名 `bl_name`
   - 遍历 `buy_seats`，检查 `bl_name` 的子串是否出现在 `seat["name"]` 中（或反向：`seat["name"]` 子串是否在 `bl_name` 中）
   - 匹配方式：双向子串包含 `bl_name in seat_name or seat_name in bl_name`，或更稳的 `bl_name` 关键词子串匹配
3. **占比计算**：
   - `matched_buy_amt = sum(seat["buy_amt"] for seat in buy_seats if matched)`
   - `blacklist_ratio = matched_buy_amt / total_buy_amount`
4. **硬剔除判定**：
   - `if blacklist_ratio > blacklist_config["threshold"]["blacklist_ratio"]`（默认 0.15 即 15%）→ 从 suggestions 列表移除 + 标 `risk_flags[stock_code] = ["【拒绝介入】黑名单占比 {:.1%}".format(blacklist_ratio)]`
5. **返回**：`(filtered_suggestions, risk_flags)`

**新增配置**：`config/seat_blacklist.yaml`

```yaml
# 龙虎榜黑名单席位配置（PRD §3 初始列举 + 可扩展）
# 标注：探索性（外部 PRD 拍定，零数据支撑，进 config 可配，AC8 回测调参）

# 黑名单席位名单（子串模糊匹配）
blacklist:
  - "拉萨团结路"           # 散户大本营典型
  - "拉萨东环路"
  - "东方财富拉萨"         # 写法变体覆盖
  # ... PRD §3 初始列举，可扩展

# 硬剔除阈值
threshold:
  blacklist_ratio: 0.15    # 黑名单席位买入额占比 > 15% → 硬剔除
  buy_one_ratio: 0.55      # 买一占比 ≥ 55%（前五买入额）→ 独食独大软标记
  buy_one_ratio_daily: 0.10  # 买一占比 ≥ 10%（全天成交额）→ 独食独大软标记
  retail_seat_count: 3     # 拉萨席位 ≥ 3 个 → 散户霸榜软标记

# 散户大本营席位名单（子串模糊匹配）
retail_seats:
  - "拉萨团结路"
  - "拉萨东环路"
  - "拉萨金融路"
  # ...
```

---

### R3：独食独大软标记（扩展 seat_engine + 复用 SeatRiskFactor）

**修改文件**：`backend/seat_engine/service.py`

**修改点**：`compute_consensus_signal`（line 231）输出 `details` 加 `buy_one_ratio` 字段：

```python
# 在 compute_consensus_signal 返回的 details 中增加：
details = {
    "buy_seats": buy_seats,           # 既有
    "sell_seats": sell_seats,         # 既有
    "institution_buy_amt": ...,       # 既有
    "total_buy_amount": ...,         # 既有
    "buy_one_ratio": buy_one_ratio,  # 【新增】买一占比 = buy_seats[0].buy_amt / total_buy_amount
    # ...
}
```

**独食独大判定逻辑**（在 `dragon_tiger_seat_filter.py` 中实现）：

```python
def check_monopoly(seat_details: dict, daily_amount: float | None) -> list[str]:
    """
    R3 独食独大软标记。
    
    判定：
      buy_one_ratio >= 0.55（前五买入额占比）→ 标 ["独食独大"]
      或 buy_seats[0].buy_amt / daily_amount >= 0.10（全天成交额占比）→ 标 ["独食独大"]
    
    输出：risk_flags 列表（空列表 = 无标记）
    """
```

**仓位砍半**：在 `cap_by_market_phase` 或 `pre_market_workflow` 中，若 `risk_flags` 含"独食独大"，对该标的 `suggested_pct *= 0.5`（复用 `hot_money_seats.SeatRiskFactor` 的 `score_modifier` 机制，day_trip_ratio>0.5→×0.7 先例）

---

### R4：散户霸榜软标记（复用 buy_seats 席位计数）

**实现位置**：`backend/dragon_tiger_seat_filter.py`

**判定逻辑**：

```python
def check_retail_dominance(buy_seats: list[dict], retail_seats_config: list[str]) -> list[str]:
    """
    R4 散户霸榜软标记。
    
    判定：
      buy_seats 前五中，匹配 retail_seats_config（拉萨团结路/东环路等）的席位 >= 3 个
      → 标 ["散户霸榜"]
    
    匹配方式：子串模糊匹配（同 R2.2）
    输出：risk_flags 列表
    """
```

**战法匹配置信度降权**：在 `pre_market_workflow` 链路中，若 `risk_flags` 含"散户霸榜"，对该标的的战法匹配置信度降权（复用 `hot_money_seats.day_trip_ratio` 基础扩展，具体降权系数进 config 可配）

---

### R5：数据缺失处置（透明原则，不默认放行/拒绝）

**实现位置**：`backend/dragon_tiger_seat_filter.py`

**判定逻辑**：

```python
def filter_by_blacklist(suggestions, blacklist_config, trade_date, seat_engine):
    filtered = []
    risk_flags = {}
    data_missing_flags = {}  # 【新增】数据缺失标记
    
    for sug in suggestions:
        consensus = seat_engine.compute_consensus_signal(trade_date, sug.stock_code)
        
        # R5 数据缺失处置
        if consensus is None or consensus.get("signal") == "未取得":
            data_missing_flags[sug.stock_code] = "席位风控数据未取得，硬剔除不可执行"
            # 不剔除（不默认拒绝），不硬剔除（不默认放行）
            # 保留在 filtered 中，标 data_missing，由用户决策
            filtered.append(sug)
            continue
        
        # R2 黑名单硬剔除
        # ... 占比计算 + 硬剔除逻辑
    
    return filtered, risk_flags, data_missing_flags
```

**显著警示**：`data_missing_flags` 中的标的前端展示显著警示标记"席位风控数据未取得，硬剔除不可执行"，由用户决策（AC4）

---

### R6：_market_phase 扩展（4 因子 + 红期硬熔断覆盖）

**修改文件**：`backend/strategies/first_board_filter.py`（line 100 `_market_phase`）

**修改要点**：

1. **扩展签名**（用默认参数实现向后兼容）：

```python
def _market_phase(
    zt_count: int,
    big_loss: int | None = None,       # 大面股≥10% 家数（spec R6.1 big_loss_count）
    floor: int | None = None,          # 跌停家数（spec R6.1 floor_count）
    ladder_success: float | None = None,  # 连板晋级率（spec R6.1 ladder_success_rate）
    ladder_height: int | None = None,  # 连板最高高度（spec R6.1 max_ladder_height）
) -> str:
    """
    R6 扩展：4 因子输入 + 红期硬熔断覆盖。
    
    返回：冰点 / 普通 / 活跃 / 亢奋 / 红期
    
    兼容性：_market_phase(zt_count) 旧签名调用（big_loss=None 等）走原四档判定逻辑，
            score_candidate（line 1341）现有调用不破坏。
    """
    # R6.2 红期硬熔断覆盖（优先级最高）
    if big_loss is not None and big_loss >= 8:
        return "红期"
    if floor is not None and floor >= 20:
        return "红期"
    
    # R6.1 四档判定（原逻辑保留，zt_count 单因子）
    if zt_count < 30:
        return "冰点"
    elif zt_count < 60:
        return "普通"
    elif zt_count < 100:
        return "活跃"
    else:
        return "亢奋"
```

2. **三状态映射**（R6.3，供 R7 cap_by_market_phase 使用）：

```python
# 绿 = 活跃 + 亢奋
# 黄 = 普通
# 红 = 冰点 或 红期硬熔断覆盖触发

PHASE_TO_CAP_TIER = {
    "活跃": "green",
    "亢奋": "green",
    "普通": "yellow",
    "冰点": "red",
    "红期": "red",
}
```

3. **因子来源**（R6.4，T-1 盘后数据计算）：
   - `zt_count`：既有（first_board_filter 现有）
   - `big_loss` / `floor` / `ladder_success` / `ladder_height`：从 T-1 盘后市场数据计算，复用 `market._emotion` 既有端点（实现阶段核实具体端点，标注 T2 待定）

4. **向后兼容**（R6.5）：
   - 旧签名 `_market_phase(zt_count=40)` 调用 → big_loss/floor/ladder_success/ladder_height 均为 None → 跳过红期硬熔断 → 走原四档判定 → 返回"普通"
   - `score_candidate`（line 1341 `market_phase="普通"`）现有调用不破坏

---

### R7：cap_by_market_phase 后处理（叠加仓位闸）

**修改文件**：`backend/strategies/position_advisor.py`

**新增函数**（不修改既有 `advise` / `advise_batch` 签名）：

```python
def cap_by_market_phase(
    positions: list[PositionSuggestion],
    phase: str,
    weather_state: dict | None = None,
) -> list[PositionSuggestion]:
    """
    R7 仓位闸后处理。叠加在 PositionAdvisor.advise_batch 输出之上。
    
    输入：
      positions: advise_batch 返回的 PositionSuggestion 列表
                 （每个 position.suggested_pct 已经过 weather_cap 处理）
      phase: _market_phase 返回的字符串（冰点/普通/活跃/亢奋/红期）
      weather_state: 既有 weather 状态（用于读取 weather_cap，可选）
    
    输出：仓位上限叠加处理后的 PositionSuggestion 列表
    """
    # R7.1 三状态映射
    MARKET_PHASE_CAP = {
        "green": 1.0,   # 活跃/亢奋 → 绿（不放宽，只收紧）
        "yellow": 0.5,   # 普通 → 黄
        "red": 0.2,      # 冰点/红期 → 红
    }
    
    tier = PHASE_TO_CAP_TIER.get(phase, "yellow")  # 未知 phase 降级黄
    market_phase_cap = MARKET_PHASE_CAP[tier]
    
    # 既有上限（PositionAdvisor 类属性，line 76 advise 逻辑）
    max_single_position = 0.2   # 单票仓位上限（实现阶段核实，T5）
    max_total_position = 0.8    # 总仓位硬上限（既有）
    
    for pos in positions:
        # pos.suggested_pct 已经过 weather_cap 处理（advise_batch 输出）
        weather_cap_result = pos.suggested_pct
        
        # market_phase_cap 叠加
        market_phase_cap_result = min(
            pos.suggested_pct,
            max_single_position * market_phase_cap
        )
        
        # R7.1 叠加代数：final_cap = min(weather_cap, market_phase_cap, max_total_position)
        final_pct = min(weather_cap_result, market_phase_cap_result, max_total_position)
        pos.suggested_pct = final_pct
        
        # 标记仓位闸信息（供前端展示）
        pos.market_phase = phase
        pos.market_phase_cap = market_phase_cap
    
    return positions
```

**关键约束**：

- **R7.2 绿档不放宽**：`market_phase_cap` 绿档=1.0，`max_single_position * 1.0 = max_single_position`，`min(suggested_pct, max_single_position)` 不会超过既有单票上限，只收紧不放宽
- **R7.3 互斥说明**：同一情绪现象（大面股爆炸≈暴风雨）可能同时触发 weather 熔断和 market_phase 熔断，取 `min()` 不冲突（取最严）
- **叠加代数**：`final_cap = min(weather_cap, market_phase_cap, max_total_position)`（spec §2.2 冲突 5 处置）

**集成位置**（在 `pre_market_workflow.py` 中，R9 详述）：

```python
# pre_market_workflow.py 既有 line 150
position_suggestions = advisor.advise_batch(signals, weather_state)

# 【新增 R7 仓位闸后处理】
phase = _market_phase(zt_count, big_loss, floor, ladder_success, ladder_height)
position_suggestions = cap_by_market_phase(position_suggestions, phase)
```

---

### R8：STI 时序分离（文档层声明，不改代码）

**实现**：纯文档层声明，不改代码

- **STI**：T-1 盘后总结（`limitup_sti/` 8 维度加权 → 4 天气），用于 PositionAdvisor.advise 的 weather_state 参数
- **_market_phase**：T+1 盘前仓位闸因子（`first_board_filter._market_phase`），用于 cap_by_market_phase 的 phase 参数
- **时序用途不同**：STI 是总结，_market_phase 是开关，不引入新概念，不替代 STI（spec §2.2 冲突 6 处置）

**声明位置**：`first_board_filter.py` `_market_phase` 函数 docstring + `position_advisor.py` `cap_by_market_phase` 函数 docstring

---

### R9：信号输出（仓位参数，不接券商不下单）

**修改文件**：`backend/pre_market_workflow.py`

**修改点**：在既有 `advise_batch`（line 150）后串两层后处理：

```python
# 既有 line 96-97
matcher = StrategyMatcher(...)
advisor = PositionAdvisor(...)

# 既有 line 124
signals = matcher.match(...)

# 既有 line 150
position_suggestions = advisor.advise_batch(signals, weather_state)

# 【新增 R9 串两层后处理】

# Layer 1: 龙虎榜席位三分级风控（R1-R5）
from backend.dragon_tiger_seat_filter import DragonTigerSeatFilter
import yaml

with open("config/seat_blacklist.yaml") as f:
    blacklist_config = yaml.safe_load(f)

dt_filter = DragonTigerSeatFilter(seat_engine=seat_engine)  # 复用既有 seat_engine 实例
position_suggestions, seat_risk_flags, data_missing_flags = dt_filter.filter(
    suggestions=position_suggestions,
    blacklist_config=blacklist_config,
    trade_date=t_minus_1_date,
)

# Layer 2: 仓位闸后处理（R6-R7）
from backend.strategies.first_board_filter import _market_phase
from backend.strategies.position_advisor import cap_by_market_phase

# R6.4 因子从 T-1 盘后数据计算（实现阶段核实具体端点，T2）
zt_count = ...  # 既有
big_loss = ...  # 从 T-1 市场数据计算
floor = ...
ladder_success = ...
ladder_height = ...

phase = _market_phase(zt_count, big_loss, floor, ladder_success, ladder_height)
position_suggestions = cap_by_market_phase(position_suggestions, phase)

# 输出仓位参数 + 风控标记（R9.1）
output = {
    "position_suggestions": position_suggestions,
    "market_phase": phase,
    "market_phase_cap": MARKET_PHASE_CAP[PHASE_TO_CAP_TIER[phase]],
    "seat_risk_flags": seat_risk_flags,        # 龙虎榜风控标记
    "data_missing_flags": data_missing_flags,   # 数据缺失标记
    # R9.2 触发价/竞价达标额：属 S081 战法匹配 spec 范围，本 spec 不输出
}
```

**R9.1 仓位参数输出**：
- 单笔委托金额 = 总仓位上限 × 个股仓位分配 ÷ 标的数
- 黄色期砍半（`market_phase_cap=0.5` 已在 cap_by_market_phase 中处理）
- 参数标注"参考值，非执行指令"（AC5/AC7）

**R9.2 触发价/竞价达标额**：属 S081 战法匹配 spec 范围，本 spec 不输出（战法因子未就绪）

---

### R10：checklist 推送（飞书/前端，复用既有通道）

**修改文件**：
- `backend/routers/workflow.py`（响应加字段）
- `frontend/src/lib/api.ts`（响应类型加字段）
- `frontend/src/pages/Workflow.tsx`（展示仓位上限 + 风控标记 + checklist）

**后端响应扩展**（`routers/workflow.py`，复用既有 `/api/workflow/pre-market` 端点，不新增端点）：

```python
# /api/workflow/pre-market 响应增加字段：
{
    # 既有字段...
    "position_suggestions": [...],
    
    # 【新增】仓位闸字段
    "market_phase": "普通",              # _market_phase 返回值
    "market_phase_cap": 0.5,             # 绿1.0/黄0.5/红0.2
    "position_cap_tier": "yellow",       # green/yellow/red
    
    # 【新增】龙虎榜风控标记
    "seat_risk_flags": {
        "600000": ["【拒绝介入】黑名单占比 18.5%"],
        "600001": ["独食独大"],
        "600002": ["散户霸榜"],
    },
    "data_missing_flags": {
        "600003": "席位风控数据未取得，硬剔除不可执行",
    },
    
    # 【新增】人工执行 checklist
    "execution_checklist": [
        "仓位参数参考值，非执行指令",
        "黄色期仓位砍半，单笔委托金额 = 总仓位上限 × 个股仓位分配 ÷ 标的数",
        "【拒绝介入】标的不可开仓",
        "数据缺失标的需人工核实龙虎榜后决策",
        "历史统计特征，市场有风险",
    ],
}
```

**前端展示**（`Workflow.tsx`）：
- 仓位闸面板：显示 `market_phase` + `market_phase_cap` + `position_cap_tier`（绿/黄/红三色标识）
- 龙虎榜风控标记：每个标的旁显示 `seat_risk_flags`（【拒绝介入】/独食独大/散户霸榜）
- 数据缺失警示：显著警示标记"席位风控数据未取得"
- 人工执行 checklist：底部展示 `execution_checklist`，标注"参考值，非执行指令"

**飞书推送**：复用既有推送通道（`notification/`），推送格式包含仓位参数 + 风控标记 + checklist，标注"仓位参数参考值，非执行指令"

---

## 2.x AC6：hot_money_seats "绕过 em_get" 处置

**修改文件**：`backend/strategies/hot_money_seats.py`（line 75 注释"绕过 em_get 熔断"）

**处置步骤**：

1. **核实**：`datacenter-web.eastmoney.com` 域名的限流策略是否与 `push2ex.eastmoney.com`（em_get 防护对象）相同
   - 若不同（datacenter 无限流/限流更宽松）→ 在代码注释显式声明理由，保留 urllib 直接调用
   - 若相同（datacenter 也有限流）→ 套上 `em_get` 限流或 `circuit_breaker.get_breaker("eastmoney")` 熔断器 + 重试

2. **代码注释**（line 75 替换）：

```python
# datacenter-web.eastmoney.com 限流策略核实结果（AC6）：
# [实现阶段填写] datacenter 域名 [需要/不需要] em_get 防护，理由：...
# 若需防护：已套 em_get 限流 + circuit_breaker 重试
# 若不需防护：datacenter 与 push2ex 限流策略不同，直接 urllib 调用安全
```

3. **验证**：联网测试 `pytest -m live` 跑 datacenter 通道限流验证

---

## 3. 验收对齐（AC1-AC10 逐条对应）

| AC | 验收标准 | 对应 plan 实现步骤 | 验证方式 |
|---|---|---|---|
| AC1 | `_market_phase()` 扩展为 4 因子输入 + 红期硬熔断覆盖，旧签名向后兼容 | R6（§2 R6） | 单元测试：mock zt_count=40/big_loss=3/8/12 等场景；向后兼容 `_market_phase(zt_count=40)` 返回"普通" |
| AC2 | `cap_by_market_phase(positions, phase)` 叠加代数 `min(weather_cap, market_phase_cap, max_total_position)`，绿档不放宽 | R7（§2 R7） | 单元测试：mock PositionAdvisor 输出 + 三状态映射 + weather_cap，验证 `min()` 叠加 |
| AC3 | 龙虎榜三分级风控：黑名单占比>15% 硬剔除、独食独大仓位砍半、散户霸榜降权 | R2/R3/R4（§2 R2-R4） | 单元测试：mock 黑名单/独食独大/散户霸榜场景，验证硬剔除/砍半/降权 |
| AC4 | 龙虎榜数据"未取得"时，硬剔除不可执行 + 警示 + 用户决策 | R5（§2 R5） | 单元测试：mock 龙虎榜"未取得"，验证硬剔除不可执行 + 警示 |
| AC5 | 输出仓位参数 + 风控标记 + checklist，不接券商不下单，标注"参考值，非执行指令" | R9/R10（§2 R9-R10） | 手动验收：取近 5 交易日真实数据跑全链路，确认无券商 API 调用 |
| AC6 | `hot_money_seats.py` "绕过 em_get" 处置 —— 核实/套限流 | §2 AC6（§2 2.x） | 联网测试：`pytest -m live` datacenter 通道限流验证 |
| AC7 | 研判/买卖时机/仓位参数挂轻量风险提醒 | R9/R10（§2 R9-R10） | 代码审查：输出层挂「历史统计特征，市场有风险」提醒 |
| AC8 | PRD 阈值标注"探索性"，进 config 可配，回测调参门限 | R2 config（§2 R2） + §1.2 | 跑 `financial_rigor.py --thresholds prd_p2 --window 60d`，标注探索性，约定命中率<5% 或空池率>30% 触发调参 |
| AC9 | S002 AC10 在 P2 放宽到 §1.1 弱合规口径，允许输出仓位参数/红期熔断/【拒绝介入】 | R9/R10（§2 R9-R10） | 代码审查：确认 P2 输出层含仓位参数/红期熔断/【拒绝介入】，挂风险提醒 |
| AC10 | 不涉及战法匹配扩展（S081），不涉及参考价位（S081） | 全 plan 不涉及 | 代码审查：确认无战法匹配扩展 + 无止损/止盈参考价位输出 |

---

## 附录：实施阶段（按 AGENTS.md large 分级）

| 阶段 | 内容 | 产出 | 映射 AC |
|---|---|---|---|
| **A. _market_phase 扩展** | `first_board_filter.py` _market_phase 4 因子 + 红期硬熔断 + 向后兼容 | 单元测试可跑 | AC1 |
| **B. cap_by_market_phase** | `position_advisor.py` 新函数 + 叠加代数 + 三状态映射 | 单元测试可跑 | AC2 |
| **C. 龙虎榜三分级风控** | `dragon_tiger_seat_filter.py` + `seat_blacklist.yaml` + seat_engine 输出扩展 | 单元测试可跑（mock） | AC3/AC4 |
| **D. 链路集成** | `pre_market_workflow.py` 串两层后处理 + `routers/workflow.py` 响应扩展 | 端到端可跑（离线 mock） | AC5/AC9 |
| **E. AC6 处置** | `hot_money_seats.py` datacenter 限流核实/套限流 | 联网测试可跑 | AC6 |
| **F. 前端** | `Workflow.tsx` + `api.ts` 仓位闸/风控标记/checklist 展示 | 页面可用 | AC5/AC9 |
| **G. 验收** | 逐条 AC 核对 + `financial_rigor.py` 阈值复算 + 合规自查 + `pytest -m "not live"` 全过 | 验收报告 | 全 AC |

依赖：B 独立；C 独立；D 依赖 A+B+C；E 独立；F 依赖 D；G 依赖 D-F。A/B/C/E 可并行。

---

## 附录：风险与回滚（对应 spec §9）

| 风险 | 影响 | 缓解 |
|---|---|---|
| `_market_phase()` 扩展破坏 first_board_filter 评分链路 | 现有评分权重分层失效 | 保留四档判定 + 旧签名向后兼容（R6.5），红期硬熔断作为覆盖层不替换四档 |
| `cap_by_market_phase` 叠加与既有 weather 熔断冲突 | 双重熔断语义混乱 | 叠加代数 `min()` 取最严（R7.1），绿档不放宽（R7.2），互斥说明（R7.3） |
| `hot_money_seats` "绕过 em_get" 触 IP 封禁 | datacenter 通道被封 | 核实 datacenter 限流策略，套限流/重试（AC6） |
| PRD 阈值零数据支撑 | 阈值过严/过宽 | 标注"探索性"，进 config 可配，回测调参门限（AC8） |
| 龙虎榜数据"未取得"默认行为 | 默认放行=风控绕过，默认拒绝=误杀 | 硬剔除不可执行 + 警示 + 用户决策（R5/AC4） |

**回滚策略**（spec §9）：
1. **整链禁用**：回退到既有 pre_market_workflow 输出，不影响 S002 P1 已验收行为
2. **单层禁用**：需同时禁用其下游所有层（串行链）
3. **`_market_phase()` 扩展回滚**：删除 4 因子重载 + 红期硬熔断覆盖，旧签名自动恢复原行为（R6.5）
