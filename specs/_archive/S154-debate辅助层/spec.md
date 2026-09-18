# Spec: S154 — T6.1 debate 辅助层（盘中事实进底稿，标"辅助非 edge"）

> 状态：草案→实现中（2026-09-05）
> 作者：Claude  日期：2026-09-05
> 关联：[量化模型验证路线.md debate 辅助层]、S152（H2 证否）、S151（评价层）、debate.py

## 1. 问题 / 目标

§44 + S152 verdict：选股（forward 0.983）+ 盘中 H2（0.7843）全劣于随机，无 validated edge。
专家共识（路线图 §73-75）："验证不过的别让 debate 综合，给无 edge 的东西穿体面衣服"——
**辅助层非 edge，标"辅助非 edge"**。

但 debate.py 底稿当前只有 5 面（估值/财报/资金/事件/行业），**缺盘中事实**（封单/开板/last_lock_time）。
用户原意"结合盘中信号增加确定性"——盘中事实让 AI 看结构（非买卖信号）是合理扩展（fund_flow 已在底稿同款）。

**目标**：debate 底稿加盘中封单特征 section（query_intraday_features 工具读 seal_derived_features），
**透明标"辅助非 edge（§44 H2 证否）"**，AI 可看盘中结构但不据此判 edge。不新增 edge 声明。

## 2. 背景

- debate.py：多空辩论 + 事实底稿 + 不打分不裁决（中立主持只归纳分歧）。底稿 = 后端按 `_DOSSIER_SPEC` 清单拉客观数据
- `_DOSSIER_SPEC`：每项 (tool_name, params, title, parallel, empty_ok)。含 query_fund_flow（资金）等
- `seal_derived_features` 表（seal_intraday.db）：date/code/last_lock_time/broken_duration_min/max_drop_pct/limit_price/data_status
- `get_derived_result(code, date)`（risk.seal_intraday_collector:316）：单日读，S084 C3 预采集读范式
- §44 H2 verdict（S152）：lift=0.7843 劣于随机——盘中封板时间无 edge，标"辅助非 edge"

## 3. 需求清单（R1-R3）

- [ ] R1 `query_intraday_features(code, days=5)` 工具（ai/tools/stock_tools.py，@register_tool）：
  读 seal_derived_features 近 N 日（ORDER BY date DESC LIMIT N），返 list[{date, last_lock_time, broken_duration_min, max_drop_pct, limit_price, data_status, note}]。
  note 固定 "辅助非 edge（§44 H2 lift=0.7843 劣于随机，仅供看盘中结构）"。
  fresh env 表不存在 → 返 [] 不臆造。chat.TOOLS 自动获（registry），MCP 同步
- [ ] R2 debate `_DOSSIER_SPEC` 加项：("query_intraday_features", {"days": 5}, "盘中封单特征（辅助，非 edge）", True, True)。
  parallel=True（读本地 DB 不走 em_get 防封无关）；empty_ok=True（多数股无 seal_derived_features，空是正常非缺口）
- [ ] R3 诚实标注：dossier_text 渲染该 section 时带"辅助非 edge"标签（note 已含，渲染透传）。
  底稿顶部已有的"客观事实不含观点"声明覆盖——AI 不得据此判 edge

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/ai/tools/stock_tools.py | R1：query_intraday_features 工具 |
| backend/debate.py | R2：_DOSSIER_SPEC 加 query_intraday_features 项 |
| backend/tests/test_stock_tools.py（或新建） | R1-R3 测试 |

## 5. 设计方案

**A. query_intraday_features**：复用 `risk.seal_intraday_collector._get_conn`（SEAL_INTRADAY_DB_PATH）。
SELECT date/last_lock_time/broken_duration_min/max_drop_pct/limit_price/data_status WHERE code=? ORDER BY date DESC LIMIT ?。
sqlite3.OperationalError（表不存在/fresh env）→ 返 [] 不臆造。每行附 note="辅助非 edge（§44 H2 lift=0.7843 劣于随机，仅供看盘中结构）"。

**B. debate 底稿 section**：parallel=True（本地 DB 读，不触 em_get 防封底线）+ empty_ok=True（多数股无预采集，空正常）。
dossier_text 渲染时 note 透传——AI 看到"辅助非 edge"明示，不据此判 edge。

**C. 不新增 edge 声明**：工具 description + note 双重标"辅助非 edge"。debate 中立主持不裁决不变。
§44 verdict 文档化（DIMENSION_LIFT_REGISTRY.first_plate_h2 已冻结 0.7843）——工具透明降权而非假装 edge。

## 6. 验收标准

- [ ] A1 query_intraday_features(code with data) → 返 list，每行含 last_lock_time/broken_duration_min/note="辅助非 edge"
- [ ] A2 query_intraday_features(code no data) → 返 [] 不臆造
- [ ] A3 fresh env 表不存在 → 返 [] 不抛
- [ ] A4 debate.build_dossier(code) 底稿含"盘中封单特征" section（code 有预采集时）
- [ ] A5 pytest -m "not live" --deselect (newsradar+s032+s040) 全绿 + 新增 test_query_intraday_features

## 7. 合规与工程底线自查

- [x] 不臆造：读 seal_derived_features 实数据，缺表/缺行返 [] 不臆造；note 诚实标"辅助非 edge"
- [x] 私有数据隔离：读 SEAL_INTRADAY_DB_PATH（.vibe-research/，vr_paths 隔离不进 git）
- [x] em_get 防封：query_intraday_features 走本地 SQLite 不触东财，不触防封底线
- [x] 弱合规：note 标"辅助非 edge"非买卖信号；debate 不裁决不变；§44 verdict 透明不假装
