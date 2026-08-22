# 技术方案 · S044 候选池漏斗数据源补全

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 原则：最小改动、照搬现有 pattern、勤 commit、东财走 em_get 限流层、避免未来函数。
> 实现顺序（grill Q5 锁定）：北向 → 板块联动 → 公告类型化 → 龙虎榜游资频次（从轻到重，串行，每步独立 commit + 单测）。

---

## 1. 文件结构与职责

### 新增
无（不新建独立文件——fetcher 补进 `predict/features/fund_flow.py`，sources 改动进既有文件）。

### 改动
| 文件 | 改动 | 依赖 spec R |
|---|---|---|
| `backend/predict/features/fund_flow.py` | 补三个 TODO live fetcher：`fetch_northbound(code, date)` / `fetch_sector_flow(code, date)` / `fetch_dt_hot_money_relay(code, date)`；每个 fetcher 声明对应 FeatureSpec 的 stage/availability_offset | R1/R2/R4 |
| `backend/predict/features/registry.py` | 确认 `list_for_stage` 可被 candidate_funnel sources 调用；如需扩展 stage 查询接口则加 | R6 |
| `backend/candidate_funnel/sources/fund_flow.py` | 调 `fetch_northbound` / `fetch_dt_hot_money_relay` 填字段，替换写死值 | R1/R4 |
| `backend/candidate_funnel/sources/catalyst.py` | 调 `fetch_sector_flow` 填 `sector_flow`；加公告类型分类逻辑 `_classify_announcement(ann) -> str` | R2/R3 |
| `backend/candidate_funnel/funnel.py` | `_filter_r2` 加北向绝对值过滤；`_filter_r3` 支持按公告类型筛；`run_funnel` 加 stage 防护（调 registry.list_for_stage 过滤 future-stage 数据） | R3/R5/R6 |
| `backend/candidate_funnel/thresholds.py` | `BaseThreshold` 加 `northbound_abs_min: float` 字段（默认 0.0，等价于"有北向数据即保留"）；`PHASE_ADJUSTMENTS` 视情况加北向档位（初版不加，沿用基数） | R5 |
| `backend/candidate_funnel/models.py` | `IndicatorSet` 加 `dragon_tiger_hot_money_relay: float | None = None`（向后兼容） | R9 |
| `backend/candidate_funnel/diagnosis.py` | `build_indicator_set` 拼接 `dragon_tiger_hot_money_relay` | R9 |

---

## 2. 实现顺序与各步设计

### 2.1 Step 1：北向 fetcher（R1）

#### 前置：live 探测东财个股北向端点（spec 风险点）

astock 无现成北向函数。`em_get` 拼 `push2his.eastmoney.com/api/qt/stock/fflow/daykline/get` 是个股资金流（`stock_fund_flow_120d` 已用）；个股北向是另一个端点。

**实现期第一步**：写探测脚本 `_probe_northbound.py`（照搬 grill 期间 `_probe_sector_fund_flow.py` 模式），探测候选端点：
- `push2his.eastmoney.com/api/qt/stock/hsgt/...`（港股通个股持仓）
- `datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_STOCK_HSGT_HOLD...`

探测成功则用该端点；探测失败（东财已下线个股北向）→ 标 missing + spec 回退记录。

#### fetcher 实现

```python
# predict/features/fund_flow.py 新增
def fetch_northbound(code: str, date: str) -> float | None:
    """个股北向净流入（盘后可得）。走 em_get 限流。
    
    Returns:
        float: 北向净流入额（万元），取不到返回 None
    """
    # 用探测成功的端点拼 em_get 调用
    # 返回值统一为"万元"（跟 fund_flow.py 其他字段口径一致）
    ...

# FeatureSpec 声明（已有 northbound_net_segmented，补 fetcher）
# stage="s1" availability_offset=1（盘后公布）
```

#### candidate_funnel sources 调用

```python
# candidate_funnel/sources/fund_flow.py 改
from predict.features.fund_flow import fetch_northbound

def fetch_fund_flow(codes: list[str], as_of: str) -> dict[str, dict]:
    ...
    # 原: entry["missing"]["northbound"] = "北向数据不可得"
    # 改:
    try:
        nb = fetch_northbound(c, as_of)
        entry["northbound"] = nb
        if nb is None:
            entry["missing"]["northbound"] = "北向盘后未取得"
    except Exception:
        entry["missing"]["northbound"] = "北向取数失败"
```

---

### 2.2 Step 2：板块联动 fetcher（R2）

#### fetcher 实现

```python
# predict/features/fund_flow.py 新增
def fetch_sector_flow(code: str, date: str) -> float | None:
    """个股所属板块当日主力净流入（万元）。走 push2 clist 端点（grill Q11 已探测）。
    
    流程：
    1. astock.concept_blocks(code) 取个股所属板块列表
    2. 对每个板块，em_get push2 clist（fid=f62）取板块主力净流入
    3. 取主力板块（净流入最高）或平均
    
    板块口径（申万一级 vs 东财概念）——实现期定，spec §5 D5 标未决
    """
    ...

# stage="s1"
```

#### candidate_funnel sources 调用

```python
# candidate_funnel/sources/catalyst.py 改
from predict.features.fund_flow import fetch_sector_flow

def fetch_catalyst(codes, as_of):
    ...
    for c in codes:
        ...
        try:
            sf = fetch_sector_flow(c, as_of)
            entry["sector_flow"] = sf
            if sf is None:
                entry["missing"]["sector_flow"] = "板块资金流未取得"
        except Exception:
            entry["missing"]["sector_flow"] = "板块资金流取数失败"
```

#### 历史参数探测（spec R8）

`push2 clist` 端点是否支持历史日期参数——live 探测。不支持则 90 天回溯时板块联动标 missing。

---

### 2.3 Step 3：公告类型化（R3）

#### 分类逻辑

```python
# candidate_funnel/sources/catalyst.py 新增
_ANN_TYPES = {
    "预增": ["预增", "业绩预增", "净利润增长"],
    "重组": ["重组", "并购", "吸收合并"],
    "回购": ["回购", "增持计划"],
    # 其他归入 "其他"
}

def _classify_announcement(ann: dict) -> str:
    """按 title 关键词分类。返回 预增/重组/回购/其他。"""
    title = (ann.get("title") or "")
    for type_name, keywords in _ANN_TYPES.items():
        if any(kw in title for kw in keywords):
            return type_name
    return "其他"
```

#### R3 过滤扩展

```python
# candidate_funnel/funnel.py _filter_r3 改
def _filter_r3(codes, auction, catalyst, genes, activity, 
               ann_types: list[str] | None = None) -> tuple[...]:
    """R3 定稿。ann_types 非空时，只保留公告类型在 ann_types 里的标的。
    
    默认 None：保留所有有公告的标的（向后兼容）。
    """
    ...
    for c in codes:
        ...
        if has_auction or has_catalyst:
            if ann_types:
                # 按 ann_types 过滤
                cat_anns = [a for a in (catalyst.get(c, {}).get("announcements") or []) 
                           if _classify_announcement(a) in ann_types]
                if cat_anns:
                    kept.append(c)
                else:
                    filtered.append(...)
            else:
                kept.append(c)
```

---

### 2.4 Step 4：龙虎榜游资席位接力频次（R4）

#### fetcher 实现

```python
# predict/features/fund_flow.py 新增
def fetch_dt_hot_money_relay(code: str, date: str, look_back: int = 30) -> float | None:
    """龙虎榜游资席位接力频次（聚合，不依赖个体席位标签）。
    
    流程：
    1. astock.dragon_tiger_board(code, trade_date=date, look_back=look_back) 
       取 look_back 日龙虎榜明细（含 BillboardDetail.operate_dept_name）
    2. 聚合席位出现频次：同一席位在 look_back 日内出现 N 次 → 接力频次
    3. 取"接力型"席位（出现 >= 2 次）的净买入额合计，作为游资接力强度
    
    合规：S018 R11 明确"个体席位标签 alpha 已衰减，只用聚合频次"——
    不输出个体席位名，只输出聚合频次值。
    
    Returns:
        float: 游资接力频次/强度指标，取不到返回 None
    """
    ...

# stage="s1" availability_offset=1（T+1 盘后公布）
```

#### 模型字段

```python
# candidate_funnel/models.py IndicatorSet 加
dragon_tiger_hot_money_relay: float | None = None  # 向后兼容
```

#### diagnosis 拼接

```python
# candidate_funnel/diagnosis.py build_indicator_set 改
ind.dragon_tiger_hot_money_relay = f.get("dragon_tiger_hot_money_relay")
```

---

## 3. R2 北向过滤设计（R5）

### BaseThreshold 加字段

```python
# candidate_funnel/models.py BaseThreshold 加
northbound_abs_min: float = 0.0  # 默认 0，等价于"有北向数据即保留"
```

### _filter_r2 加过滤

```python
# candidate_funnel/funnel.py _filter_r2 改
def _filter_r2(codes, activity, eff, fund) -> tuple[...]:
    ...
    for c in codes:
        ...
        # 换手过滤（原有）
        if t is None or t < eff.turnover_cold:
            filtered.append(...)
            continue
        # 北向过滤（新增，非方向占位口径）
        nb = fund.get(c, {}).get("northbound")
        if nb is None:
            # missing 保留，不因缺数据过滤掉（grill Q9 锁定）
            pass
        elif abs(nb) < eff.northbound_abs_min:
            filtered.append(FilterRecord(
                code=c, name=name,
                reason=f"北向|{nb}|<|{eff.northbound_abs_min}|万"
            ))
            continue
        kept.append(c)
```

### 阈值默认值（spec 风险点）

`northbound_abs_min` 默认 0.0 = 只要有北向数据即保留。实际阈值（几百到几千万）待 live 探测 + 后续 S041/S043 回测调参确定。spec 标注"基于交易经验，未经历史回测验证"。

---

## 4. 避免未来函数设计（R6）

### run_funnel 加 stage 防护

```python
# candidate_funnel/funnel.py run_funnel 改
from predict.features.registry import Registry

# 获取当前 stage（R1/R2 在 s1=T-1盘后，R3 在 s2/s3=盘前）
_STAGE_MAP = {"pre_market": "s1", "auction": "s3"}

def run_funnel(stage: str, date: str, cfg: ThresholdConfig) -> FunnelResult:
    current_stage = _STAGE_MAP.get(stage, "s1")
    # 调 source fetcher 前，按 stage 过滤 future-stage 数据
    # 龙虎榜 availability_offset=1：在 s1（T-1盘后）跑时取不到，标 missing 保留
    ...
```

### fetcher 内部 stage 检查

各 fetcher 内部检查 `availability_offset`：
- `fetch_northbound`：availability_offset=1（盘后公布），回溯 T-1 跑时——若 date == yesterday 则可取，若 date < yesterday 则取历史数据
- `fetch_dt_hot_money_relay`：availability_offset=1，同上

---

## 5. 历史取数设计（R7）

### 统一 date 参数

各 source `fetch_xxx(codes, date)` 已支持 date 参数。补充历史路径：

| source | 当日路径 | 历史路径 |
|---|---|---|
| activity | `astock.tencent_quote(batch)` | `astock.kline(code, offset)` 复算：换手=成交量/流通股本、量比=今日量/5日均量、成交额=close*vol、振幅=(high-low)/preclose |
| fund_flow | `stock_fund_flow_120d(code)`（已返回 120 日历史，含历史 date） | 同左，按 date 取对应日 |
| dragon_tiger | `dragon_tiger_board(code, trade_date=date, look_back=30)` | 同左（已支持 trade_date） |
| announcements | `announcements(code, limit=100)` | 同左 + 按日期本地截断（取 date 当天及之前的 N 条） |
| block_trade | `block_trade(code, page_size=100)` | 同左 + 按日期本地截断 |
| sector_flow | `push2 clist`（当日） | **未探测**——不支持则标 missing |
| auction | `auction_screener.analyze(trade_date)` | 同左（已支持 trade_date） |

### activity 历史复算（最重替代逻辑）

```python
# candidate_funnel/sources/activity.py 改
def fetch_activity(codes: list[str], as_of: str) -> dict[str, dict]:
    is_historical = _is_historical_date(as_of)  # as_of < today
    if is_historical:
        return _fetch_activity_from_kline(codes, as_of)
    else:
        return _fetch_activity_from_tencent(codes)  # 原逻辑

def _fetch_activity_from_kline(codes, date) -> dict[str, dict]:
    """从 K 线复算活跃度。需 astock.kline + individual_info（流通股本）。"""
    out = {}
    for c in codes:
        bars = astock.kline(c, category=4, offset=10)  # 取 10 日 K 线
        # 找 date 对应的 bar，复算 turnover_pct/vol_ratio/amount_yi/amplitude_pct
        ...
    return out
```

---

## 6. 交易日历与日期处理

复用 `backtest_lite._next_trading_day` 的日历逻辑（`data/trading_calendar.json` 节假日）。

`vr_paths.last_trading_date()` 已有（S023 实现）：非交易时段返回最近 A 股交易日。各 source fetch 收到非交易日内部转上一交易日，data_date 如实标注。

---

## 7. 与既有 spec 的边界澄清

| 既有 spec | 边界 |
|---|---|
| S018 R11 | 本 spec 补 fund_flow.py 三个 TODO fetcher——是 S018 欠债，补完后 S018 R11 需求满足 |
| S017 short_sector | 补完的 fetcher 可被 short_sector 头消费——一处取数两处消费 |
| S040（90 天回填） | S040 回填 gene_scores（涨停基因因子），本 spec 改 candidate_funnel sources——不重叠 |
| S041（回测趋势看板） | 本 spec 不建回测框架——数据源补完后 S041 可消费补全后的 R3 定稿池验证增量贡献 |
| S043（次日溢价单因子） | 本 spec 不做单因子分析——溢价口径（T+1 开盘）跟 S043 一致，可引用 |
| S031（按战法回测引擎） | 本 spec 复用 S031 的"次日开盘入场"逻辑概念，但不碰 strategy_backtest.py |

---

## 8. 实现顺序与 commit 节奏

| 步 | 内容 | commit message |
|---|---|---|
| 0 | live 探测北向端点 + 板块资金流历史参数 | `probe(S044): 北向端点+板块资金流历史参数探测` |
| 1 | 北向 fetcher + sources 调用 + 单测 | `feat(S044): 北向 fetcher + R2 sources 接入` |
| 2 | 板块联动 fetcher + sources 调用 + 单测 | `feat(S044): 板块联动 fetcher + catalyst 接入` |
| 3 | 公告类型化 + R3 过滤扩展 + 单测 | `feat(S044): 公告类型化 + R3 按类型过滤` |
| 4 | 龙虎榜游资频次 fetcher + models + diagnosis + 单测 | `feat(S044): 龙虎榜游资席位接力频次` |
| 5 | 北向进 R2 过滤 + BaseThreshold 字段 + 单测 | `feat(S044): 北向进 R2 非方向占位过滤` |
| 6 | 避免未来函数 stage 防护 + 单测 | `feat(S044): sources stage 防护 + list_for_stage 复用` |
| 7 | 历史取数支持（activity kline 复算 + 统一 date 参数）+ 单测 | `feat(S044): 历史取数支持 + activity kline 复算` |
| 8 | live 冒烟验收 + 补 missing 标注 | `test(S044): live 冒烟 + missing 标注核对` |

---

## 9. 风险与回滚

| 风险 | 应对 | 回滚 |
|---|---|---|
| 北向端点东财已下线 | Step 0 先探测；失败则标 missing + spec 回退记录 | fund_flow.py 北向字段改回 missing |
| 板块资金流无历史参数 | Step 0 探测；不支持则 90 天回溯板块联动标 missing | catalyst.py sector_flow 改回 None |
| northbound_abs_min 默认值无回测支撑 | 标注经验假设；默认 0 等价不过滤；回测调参由 S041/S043 承担 | 默认 0 = 不过滤 |
| activity kline 复算口径偏差 | 单测对比 kline 复算 vs tencent_quote 当日值，差异 < 5% | activity 改回只取当日 |
| S018 fetcher 补债 scope 蔓延 | 补的 fetcher 是 S018 spec 本该完成的工作，属还欠债 | 删除 fetcher 即回滚 |

---

## 10. 不做（scope 约束）

- 回测框架 / 90 天回填 / 次日溢价单因子分析（S040/S041/S043 已覆盖）
- 技术位（均线/BOLL/MACD）/ 补充参考信号（分时量比突变/大宗折溢价/筹码分布）（spec §5.1 "辅助"/"补充参考"，优先级靠后）
- 盘中信号 / 盘后结算（S002 P2/P3 范围）
- 板块口径申万 vs 东财概念（实现期定）
- 阈值 X 默认值（live 探测 + 回测调参确定）
