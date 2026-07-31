# Spec: S019 — 宏观特征 Fred API 接入（macro.py 第二批）

> 状态：草案  作者：Claude  日期：2026-07-30
> 关联：`../S018-多源特征工程/spec.md`（§4.6 macro、验收报告 §5 遗留）、`../S017-A股涨跌预测模型栈/`、`../../CLAUDE.md` §1
> 前置：S017-T0b 已验证东财 push2 候选 secid（美债10Y/DXY）全空，须接 Fred API 补数据源。

---

## 1. 问题 / 目标

S018 macro.py 第一批（DXY / 美债 10Y）因东财端点不可得（T0b 验证）被延后。这两个是短线头的外盘锚变量，缺则短线头少一个宏观维度。本 spec 接 Fred API（免费 key）补登 S2 特征，并守"国外源独立通道+代理、key 隔离、未补前不入短线头"约束。

## 2. 背景

- Fred（圣路易斯联储）免费 API：`series_id=DGS10`（10 年期美债收益率）、`DTWEXBGS`（贸易加权美元指数广义，后继；原 `DTWEXB` 已于 2019-12-31 废止）。
- CLAUDE.md §3：gstock.py 注释声明 Yahoo/SEC 等国外源不并入东财通道——Fred 属国外源，须在 macro.py 内独立通道（不混入 em_get），可走系统代理。
- §1 合规：私有 key 只存 `项目内 .vibe-research/`（`VR_DATA_DIR`），绝不进 git。
- S018 验收报告 §5：macro 待 Fred API 接入后补登 S2；未补前不入短线头，`availability_offset` 标 N/A（即不加入 HEAD_FEATURE_SUBSETS）。

## 3. 需求清单

- [ ] R1 `features/macro.py` 注册 2 特征 FeatureSpec：`us_10y_yield`（source=fred_api, category=macro, offset=1, stage=s2, ok）、`dxy`（同）。
- [ ] R2 `get_fred_api_key() -> str | None`：从 `项目内 .vibe-research/fred_api_key`（VR_DATA_DIR）读 key，缺失返 None。key 绝不进 git、不打日志。
- [ ] R3 `fetch_fred_series(series_id, api_key, proxy=None) -> dict | None`：调 Fred observations 端点，独立 requests 通道（不走 em_get），可选系统代理。失败/无 key 返 None。
- [ ] R4 `parse_fred_observations(resp: dict) -> list[dict]`：纯解析 Fred JSON → `[{date:"YYYY-MM-DD", value:float|None}]`，过滤缺失值（"."）。可复算单测。
- [x] R5 ~~注册的特征不加入 HEAD_FEATURE_SUBSETS~~ **已满足**：Fred key 到位 + live 冒烟通过后，macro 2 特征已加入 `HEAD_FEATURE_SUBSETS["short_sector"]`（short_sector 21→23，commit 10c61fc）。
- [ ] R6 Fred 端点走独立通道，不裸调 em_get；key 隔离在 VR_DATA_DIR。
- [ ] R7 可复现：series_id 固定、解析纯函数、key 不参与计算逻辑（仅鉴权）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/predict/features/macro.py` | macro 特征 + Fred fetcher + 解析 |
| ➕`backend/tests/test_features_macro.py` | FeatureSpec + key reader + 解析单测 |
| `backend/predict/feature_interface.py` | 暂不改（macro 不入 head 子集，待 key 到位） |

## 5. 设计方案

- 独立通道：`fetch_fred_series` 用 `requests`（非 `astock.em_get`），可读 `VR_HTTP_PROXY` 环境变量走代理；失败降级返 None。
- key 读取：`get_fred_api_key` 读 `vr_paths.resolve_data_dir() / "fred_api_key"`。
- 解析：Fred observations 返 `{observations:[{date,value},...]}`，value="." 表缺失→None。
- 不入短线头：MACRO_SPECS 注册进 registry（存在性可见），但 `feature_interface.HEAD_FEATURE_SUBSETS` 不含 macro 特征；key 到位 + 冒烟后另开 PR 加入。

## 6. 验收标准

- [ ] A1 2 FeatureSpec 注册合法（source=fred_api/stage=s2/ok）
- [ ] A2 get_fred_api_key 读 VR_DATA_DIR，缺失返 None，不打日志
- [ ] A3 parse_fred_observations 纯函数：正常 JSON→list，"."缺失→None value
- [ ] A4 fetch_fred_series 无 key/失败返 None（不抛）
- [x] A5 ~~macro 特征未加入任何 HEAD_FEATURE_SUBSETS~~ **已加入** short_sector（key 到位 + live 冒烟通过，S019 R5 解除）。
- [ ] A6 `pytest -m "not live"` 全过

## 7. 合规自查（CLAUDE.md §1）

- [ ] key 只存 项目内 .vibe-research/，绝不进 git/日志/异常
- [ ] Fred 国外源走独立通道，不混入 em_get 东财限流
- [ ] 特征为客观宏观指标，无个股名/无方向性
- [ ] 未承诺收益/未代客决策
- [ ] 可复现（series_id 固定 + 解析纯函数）

## 8. 测试计划

- 单测：FeatureSpec 构造/注册、key reader（monkeypatch VR_DATA_DIR）、parse_fred_observations（mock JSON + "."缺失）。
- live 冒烟（标 live，key 到位后跑）：fetch_fred_series("DGS10", key) 返非空。

## 9. 风险与回滚

- 🟡 key 未到位：特征注册但不入 head 子集，零影响短线头；回滚=删 macro.py。
- 🟡 Fred 限流/代理不稳：失败降级 None，调用方 fallback。
- 🟢 不动现有 em_get 通道。
