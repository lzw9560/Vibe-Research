# S058 原子任务清单

> 级别：medium（跨层；新增一个 AI 工具但复用现有 registry）
> 基线：后端 1022 passed / 前端 41 files 302 tests（S057 验收后）。

## S1 注册表字段 + 适配度函数

- [x] T1 STRATEGY_REGISTRY 每战法补 `weather_regimes` + `aliases`：
  - first_plate=[阴天]、consecutive_relay=[晴天]、break_reseal=[阴天,极端反弹]
  - low_absorption=[晴天,阴天]、reverse_package=[极端反弹]、n_shape_counterattack=[晴天,极端反弹]
  - platform_breakout=[晴天]、end_of_day_sneak=[阴天]
  - commit 门：注册表 schema 测试绿 ✅

- [x] T2 `limitup_strategy.calc_weather_fit(strategy_code, weather_state)`：
  - 三态：适配/不适配/中性
  - weather_state ∈ regimes → 适配；regimes 非空且不含 → 不适配；None/未知/regimes 空 → 中性
  - commit 门：三态逻辑单测绿 ✅

## S2 战法卡 + AI 工具

- [x] T3 `strategies/cards/<code>.md` 8 张卡（与注册表 code 一一对应）：
  - 每张：适用天气/核心逻辑/入场条件/退出参数/风险点 + 风险提醒
  - commit 门：卡片完整性测试（all cards exist for registry）✅

- [x] T4 `ai/tools/strategy_tools.py` 新增 `query_strategy_card(code)`：
  - 读卡片返文本；code 不存在返 error dict；别名检索（aliases）
  - `ai/tools/__init__.py` 触发注册
  - commit 门：工具单测（命中/别名/缺失）✅
  - 三出口（chat/MCP/cli_runtime）透明复用——TOOLS = registry.get_openai_tools() 自动包含

## S3 前端展示

- [x] T5 `StrategyFilter` 增 `weatherFit` prop：
  - 适配战法 chip 显绿色「适配」标签；不适配淡化 + 「不适配」标签；中性不显
  - vitest：适配/不适配/中性三态渲染 ✅ 3 new + 5 既有 = 8 passed

## S4 全测与合规

- [x] T6 离线全测：`pytest -m "not live" --no-cov` 全绿（后端 +17 新）；`tsc + vitest run` 全绿
- [x] T7 合规自查：卡片文案中性 + 风险提醒；不臆造胜率数字；新工具走 registry 声明式注册；无新外部数据源

## S5 归档

- [x] T8 spec.md 状态改已实现 + commit `docs(S058): 验收`
