# 验收报告 · S020（离线降级路径验收）

- 日期：2026-08-01
- 结果：✅ PASS
- 关联 spec：`specs/S020-worldmonitor决策因子接入/spec.md`（worldmonitor 决策因子接入 · P0–P6 离线降级路径）
- 验收范围：数据层/无 UI spec → 后端 API 冒烟 + 离线降级单测（AGENTS.md 验收门口径）

## 用例结果

- 通过：**27 / 27**
- 失败：0

| # | 用例 | 断言 | 结果 |
|---|---|---|---|
| 1 | `test_offline_degrade_when_fetcher_none`（P6 离线降级） | fetcher 不可达（None）时返回降级 JSON：`error` 含「暂不可达」、`tool` 回显、`note` 提示重试，不抛异常、不注入猜测数据 | ✅ |
| 2 | `test_fetcher_exception_captured`（异常捕获） | fetch 抛异常时同样走降级路径，错误信息被捕获进 `error`，不冒泡 | ✅ |
| 3 | `test_s020_p6_worldmonitor_tool.py` 其余 5 用例 | 11 工具白名单 enum、required=`["tool"]`、jmespath 支持、未知 tool → `{"error": "未知 worldmonitor 工具 ..."}` 等 | ✅ |
| 4 | `test_s020_worldmonitor.py` 全量（~20 用例） | S020 P0–P6 既有离线单测（接入注册、工具 schema、降级、备注语义等）回归 | ✅ |
| 5 | 真实网络降级（无 mock） | `worldmonitor.app:443 /mcp` ConnectTimeout → `chat._exec_tool("worldmonitor_query", {"tool":"get_market_data"})` 返回 `{'error': 'worldmonitor get_market_data 暂不可达（离线或熔断）', 'tool': 'get_market_data', 'note': '联网后可重试；本工具不注入猜测数据'}` | ✅ |

## 失败明细

无（4 个既有 pre-existing 失败——`test_newsradar_global_intel` + 3 个 `test_s003_fixes` mootdx——与本 spec 无关，不计入）。

## 运行时间

- 总耗时：2.88s（27 用例，单进程）
- 运行命令：`cd backend && .venv/bin/python -m pytest tests/test_s020_p6_worldmonitor_tool.py tests/test_s020_worldmonitor.py -q`（注意：系统 `python` 为 Python 2，必须用 `.venv/bin/python`）

## 测试环境

- 本机：macOS 12.7.6（Apple Silicon，darwin）
- 解释器：`backend/.venv/bin/python`（Python 3.14）
- 外部依赖：`worldmonitor_api_key` 缺失；到 `worldmonitor.app:443` 网络不可达（公司网 + 远程 ecs 均被阻断）→ fetcher 正确降级 None

## 备注

- **验收边界**：P6 为离线降级路径（方案 A），live 数据路径（≥2 fetcher 非空）因 key 缺失 + 网络不可达**未验**，属 P7 live 冒烟范围，待联网后另行验收。
- 降级 JSON 三字段约定：`error`（含「暂不可达（离线或熔断）」）+ `tool`（回显）+ `note`（「联网后可重试；本工具不注入猜测数据」）。
- 11 工具保序白名单：get_market_data / get_country_risk / get_news_intelligence / get_news_clusters / get_economic_data / get_country_macro / get_tariff_trends / get_supply_chain_data / get_energy_intelligence / get_china_decision_signals / get_hotspot_escalation。
- 实现位置：`backend/chat.py:85`（TOOLS 注册）/ L88-96（`_exec_tool`）/ L182（agnes `use_tools=False`），fetch 派发在 `backend/ai/tools/worldmonitor_tools.py`。
- 提交纪律：本报告与 README/tasks 状态更新一并提交；pro key 不进 git（grep 已验证无泄漏）。
