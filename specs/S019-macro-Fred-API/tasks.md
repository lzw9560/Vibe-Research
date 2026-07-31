# Tasks: S019 — Fred API 收尾验证

> 实现 已完成，本 tasks 为验证 + spec 闭合。依赖 `plan.md` §2。

---

## T1 离线单测确认（远程）
- 远程 `cd backend && .venv/bin/python -m pytest -m "not live" tests/test_features_macro.py -q`
- 验证：parse_fred_observations（正常 JSON + "."缺失→None）、get_fred_api_key（monkeypatch VR_DATA_DIR）、MACRO_SPECS 注册 全绿。
- 已含在全量 814 passed 内，本任务仅单独确认 + 记录输出。
- **验收**：test_features_macro 全绿。

## T2 live 冒烟（远程，key 在位）
- 远程 `.venv/bin/python -c "from predict.features.macro import get_fred_api_key, fetch_fred_series, parse_fred_observations, FRED_SERIES; k=get_fred_api_key(); r=fetch_fred_series('DGS10', k); obs=parse_fred_observations(r); print(len(obs), obs[-3:])"`（DGS10 + DTWEXBGS 各一次）。
- 或加 `@pytest.mark.live` 冒烟用例入 `test_features_macro.py`（fetch DGS10 返非空、parse 出 ≥1 条 value 非 None）。
- **验收**：两 series 各返非空 observations list；失败则记 Fred 通道异常，不阻塞（降级 None 已设计）。

## T3 spec 勾选闭合
- `spec.md`：R1–R4/R6–R7 `[ ]`→`[x]`；A1–A4/A6 `[ ]`→`[x]`；状态行"草案"→"已实现 2026-07-31（R5 live 冒烟通过，macro 入 short_sector）"。
- 记录 commit 哈希（d39a48d/56bc825）+ 验证日期。
- **验收**：spec 无未勾选的实现项；状态行准确。
