# 任务拆分 · S037 gene DB 路径迁移

> 级别：large，feature/S037-gene-db-migration 分支。

## 阶段 A · config 常量（R1-R3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | `config/__init__.py` 加 PRIVATE_DATA_DIR + 三库文件名 + 三库全路径常量 | — | `backend/config/__init__.py` | `python -c "from config import GENE_SCORES_DB_PATH"` 不报错 | A5 |
| A2 | `config.py` 排查：grep 确认是否还被直接 import | — | — | grep 确认走包入口 | A5 |
| A3 | `default_config.DB_PATH` 标 deprecated，保留字段防 breakage | A1 | `backend/config/__init__.py` | grep DB_PATH 标注 deprecated | — |

## 阶段 B · 代码路径改写（R4-R10）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | `limitup_screener/data.py` `_DB_PATH` 改为 `from config import GENE_SCORES_DB_PATH` | A1 | `backend/limitup_screener/data.py` | import 路径不含 `os.path.join(__file__` | A5 |
| B2 | `limitup_sti/data.py` `DB_PATH` 同理改为 `STI_TIMELINE_DB_PATH` | A1 | `backend/limitup_sti/data.py` | 同上 | A5 |
| B3 | `routers/sentiment_weather.py` 两条硬编码路径改从 config 取 | A1 | `backend/routers/sentiment_weather.py` | grep 无硬编码路径 | A5 |
| B4 | `win_rate_tracker.py`：`__init__` 默认参数 + 3 处模块级 `sqlite3.connect` 改 `WINRATE_DB_PATH` | A1 | `backend/win_rate_tracker.py` | grep 无 `"data/winrate.db"` | A4 |
| B5 | `strategies/strategy_optimizer.py` 默认参数改 | A1 | `backend/strategies/strategy_optimizer.py` | 同上 | A4 |
| B6 | `routers/health.py` `winrate_path` 改从 config 取 | A1 | `backend/routers/health.py` | 同上 | A4 |
| B7 | `settlement_recorder.py` docstring 更新路径描述 | — | `backend/settlement_recorder.py` | grep 无旧路径 | — |
| B8 | `tests/test_s034_settlement.py` 注释更新 | — | `backend/tests/test_s034_settlement.py` | 注释准确 | — |
| B9 | `conftest.py` 确认不受影响（market_data.db 不在本 spec 范围） | — | `backend/conftest.py` | 无改动或确认兼容 | — |
| B10 | grep 全面验证：`rg "vibe_research.db" backend/ --glob '*.py'` 零命中 | B1-B7 | — | grep 无输出 | A3 |
| B11 | grep 验证：`rg '"data/winrate.db"' backend/ --glob '*.py'` 零命中 | B4-B6 | — | grep 无输出 | A4 |

## 阶段 C · 迁移脚本（R11）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | `scripts/migrate_dbs.py` 骨架：MIGRATIONS 列表 + mkdir | — | `scripts/migrate_dbs.py` | `python scripts/migrate_dbs.py --help` 不报错 | — |
| C2 | 逐库迁移逻辑：wal_checkpoint -> cp -> 验证行数 -> 改名 .bak | C1 | `scripts/migrate_dbs.py` | 构造 tmp 旧库 -> 迁移成功 | A1,A2 |
| C3 | 幂等逻辑：新库已存在且行数匹配则跳过 | C2 | `scripts/migrate_dbs.py` | 二次执行不报错不重复 cp | A7 |
| C4 | 迁移报告打印：每个库名/旧行数/新行数/状态 | C2 | `scripts/migrate_dbs.py` | 输出含行数对比 | A1 |
| C5 | 单测：迁移脚本 mock tmp 库 | C2 | `backend/tests/test_migrate_dbs.py` | pytest 过 | A1,A2,A7 |

## 阶段 D · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| D1 | pytest -m "not live" 全过 | B10,B11,C5 | — | 全绿 | A6 |
| D2 | 执行迁移脚本：三库到新路径，行数一致 | C4 | — | 脚本报告确认 | A1,A2 |
| D3 | 旧库改名 .bak 保留 | D2 | — | ls 确认 .bak 存在 | A2 |
| D4 | 迁移脚本幂等：二次执行不报错 | D2 | — | 脚本输出"已迁移跳过" | A7 |
| D5 | live 冒烟：启动后端 -> 三个端点能读数据 | D2 | — | curl 确认 | A8 |
| D6 | 合并到 develop：`git merge --squash` + 一 commit | D1-D5 | — | develop 干净 | — |
