# 技术方案 · S023 漏斗可用性与因子解耦

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 原则：TDD、DRY、YAGNI、勤 commit。东财端点走 em_get，不写方向/参考价位（合规）。

## 1. 文件结构与职责

### 新增 `backend/factors/`
| 文件 | 职责 |
|---|---|
| `base.py` | `FactorResult`/`Candidate`/`SelectionFactor` Protocol 定义 |
| `registry.py` | 因子注册表（id→factor），`get_all_factors()`/`get_factor(id)` |
| `limitup_screener_factor.py` | 旧因子适配：调 PreMarketWorkflow，包成 FactorResult（单层+战法/仓位） |
| `candidate_funnel_factor.py` | 漏斗因子适配：调 run_funnel，原生多层 |
| `tests/` | 因子接口/适配层/注册表单测 |

### 改动
- `routers/workflow.py`：pre-market 端点遍历注册表
- `routers/candidates.py`：FunnelLayer 加 conditions/passed；诊断接口加来源字段；新增"重跑单层"端点
- `candidate_funnel/models.py`：FunnelLayer 加 `conditions`/`passed`；Candidate 加 `source_factor_id`/`source_layer`
- `candidate_funnel/sources/*.py`：取数失败返 data_status+reason，不静默空
- `vr_paths.py`：`last_trading_date()` 新增
- 前端：PreMarketBriefing 重构、CandidateDetail 新建、FunnelLayers 改造、DiagnosisCard 补依据链、router 加路由

## 2. 接口设计

### 2.1 因子接口
```python
# factors/base.py
@dataclass
class Candidate:
    code: str; name: str
    source_factor_id: str; source_layer: str
    hit_rules: list[str]           # 命中规则
    detail: dict                   # 因子特有（战法/仓位/指标取值）

@dataclass
class FactorResult:
    factor_id: str; factor_name: str
    candidates: list[Candidate]
    layers: list[FunnelLayer]       # 旧因子单层包装
    config: dict                    # 阈值/参数 + data_status + reason
    as_of: str; data_date: str

class SelectionFactor(Protocol):
    factor_id: str
    def fetch(self, date: str, config: dict | None = None) -> FactorResult: ...
    def describe(self) -> dict: ...
```

### 2.2 端点
- `GET /api/workflow/pre-market` → `{ factors: FactorResult[], data_date, market_emotion }`
- `GET /api/workflow/funnel/layers` → layers 含 conditions/passed（已有，扩字段）
- `PUT /api/workflow/funnel/layers/{layer_id}/rerun` → 只重跑该层，返回新 FunnelLayer
- `POST /api/workflow/funnel/layers/{layer_id}/rerun-downstream` → 用户确认后往下全跑
- `GET /api/workflow/candidates/{code}/diagnosis` → 已有，加 source_factor_id/source_layer

## 3. 逐层调参交互流程
1. 用户在 FunnelLayer 卡片调阈值 → `PUT /api/workflow/funnel/config`（更新该层相关阈值）
2. 点"重跑此层" → `PUT .../layers/{id}/rerun` → 只重跑该层，返回新 FunnelLayer
3. 前端展示新结果，出现"下游全跑"按钮
4. 用户点 → `POST .../layers/{id}/rerun-downstream` → 往下全跑

## 4. 真实数据链路
- `vr_paths.last_trading_date()`：周末/节假日/盘后 → 最近 A 股交易日（查 market_data.db 的交易日历，无则按工作日推断）
- sources 取数失败：返 `{"data_status": "未取得", "reason": "..."}`，不返空 dict
- 漏斗层 input_count 区分"采集到 0"（正常空）与"采集失败"（data_status 标记）
