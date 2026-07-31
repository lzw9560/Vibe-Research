# Tasks: S018 — 多源特征工程

> 关联：`spec.md` / `plan.md`。对接 S017 `feature_interface.py`。
> 起步范围：第一批 ~20 特征（外盘5+热钱5+行为微观4+情绪2+文本1+日历2+宏观1）+ 游资画像。

## 阶段 0：注册表与接口
- [ ] T0 `registry.py`：FeatureSpec schema + 注册表骨架 + 单测（offset/stage 过滤、look-ahead 校验）。
- [ ] T1 `feature_interface.py`：`get_features(head,stage,t)` 对接 S017（先用 stub 数据跑通接口）。依赖 T0。
- [ ] T2 "特征-可得时间"对齐表（文档 + `registry.py` 声明）+ 单测断言短线头特征在对应 stage 可得。依赖 T0。

## 阶段 1：第一批特征模块
- [ ] T3 `external.py`：外盘5（SPX/VIX/A50/恒生科技/美债10Y）+ DXY；A50 夜盘/美债可得性验证（联动 S017 T0b）。依赖 T0。
- [ ] T4 `fund_flow.py`：热钱组5（主力净流入5日累计/龙虎榜游资接力/封板资金强度/北向分段/融资余额变化）+ 板块资金轮动/大宗折价。依赖 T0。
- [ ] T5 `behavior.py`：行为微观4（短期反转/异常换手量比/集合竞价/昨涨停今表现）+ 游资画像·一日游风险（席位历史持仓周期聚类）。依赖 T0。
- [ ] T6 `sentiment.py`：涨停四池聚合情绪（aggregate_only 不泄露个股名）+ 板块分歧度。依赖 T0。
- [ ] T7 `text.py`：newsradar LLM 情绪分（固定模型版本+提示词）+ 单测可复算。依赖 T0。
- [ ] T8 `calendar.py`：节假日/交割日/会议哑变量。依赖 T0。
- [ ] T9 `macro.py`：DXY（第一批）；汇率/大宗/利差第二批预留空实现。依赖 T0。

## 阶段 2：北向分段
- [ ] T10 `NorthFlowSegmenter`：2024 规则变更日断点 + 前后分桶 + staleness 标记 + 单测。依赖 T4。

## 阶段 3：特征选择
- [ ] T11 `selection.py`：SHAP 排列重要性 + Boruta，短线头 ≤25 稳定特征 + 保留/剔除依据可复现。依赖 T3-T9 全部。

## 阶段 4：集成与验收
- [ ] T12 通过 `feature_interface.py` 供给 S017 short_sector 全量第一批特征 + 联调。依赖 T1,T3-T9,T11。
- [ ] T13 `pytest -m "not live"` + live 冒烟抽检特征取数（走 em_get 限流）。
- [ ] T14 合规自查：聚合特征无个股名/文本不引入收益承诺/取数可复现/新端点走 em_get。

## 第二批（验证有边缘后）
- [ ] T15 `macro.py` 汇率/大宗/利差 + Fed funds 隐含利率路径。
- [ ] T16 `text.py` LLM 事件抽取（监管/并购/回购/减持/业绩预告）。
- [ ] T17 期权 IV（替代已停 iVIX）。

## 依赖图（关键路径）
T0 → T1 → T12 → T13
   ├→ T3,T4,T5,T6,T7,T8,T9 → T11 → T12
   └→ T10（依 T4）
