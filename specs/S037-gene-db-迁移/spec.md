# Spec: S037 — gene DB 路径迁移（#5：三库 + winrate 统一到 .vibe-research/）

> 状态：草案
> 作者：Codex  日期：2026-08-08
> 关联：`../S028-limitup-screener-fix/spec.md`（#5 延迟项）、`../S034-结算接线/spec.md`（winrate.db cwd 依赖 wart）、`backend/limitup_screener/data.py`、`backend/limitup_sti/data.py`、`backend/win_rate_tracker.py`、`backend/routers/sentiment_weather.py`、`backend/config/__init__.py`
>
> 级别：**large**（数据迁移有丢数据风险 + 跨多模块路径常量改动 + 迁移脚本需 live 验证）

## 1. 问题 / 目标

三个 `vibe_research.db` + 一个 `winrate.db` 散落在 `backend/` 各子目录和 `data/` 下，路径拼接方式不统一（`os.path.join(__file__, ...)` 相对文件 vs cwd 相对），且不符合 AGENTS.md 私有数据隔离约定（`.vibe-research/`）。现状：

| 库 | 当前路径 | 表 | 行数 | 日期范围 |
|---|---|---|---|---|
| gene_scores | `backend/limitup_screener/vibe_research.db` | gene_scores / fuse_pardon_records / migrations | 1733 | 2026-07-09 ~ 08-07 |
| sti_timeline | `backend/limitup_sti/vibe_research.db` | sti_timeline / migrations | （待迁移脚本确认） | — |
| winrate | `data/winrate.db` | winrate_records / migrations | 15 | — |

三个库同名 `vibe_research.db` 造成混淆（`routers/sentiment_weather.py` 跨模块硬拼路径有歧义）。路径常量散落在 8+ 文件。

**目标**：三库 + winrate 统一迁到 `.vibe-research/`，重命名为语义名，路径常量统一到 config，旧库留 `.bak`。

## 2. 背景

- `.vibe-research/` 现有内容：`fred_api_key` / `portfolio.json`——私有数据隔离目录。
- `config/__init__.py:32` 已有 `_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`——项目根锚点可用。
- `config/__init__.py:167` 和 `config.py:93`（旧文件，被 `config/__init__.py` 取代）：`DB_PATH: str = "vibe_research.db"`——limitup_screener 的 DB 名常量。
- 三个库 schema 完全无关，零跨表 JOIN——保持独立库。
- 各库有独立 migration 管理器（`limitup_screener.data.run_migrations()` / `limitup_sti.data.run_initial_migrations()` / `WinRateTracker` 内建）。

### 完整路径引用清单（grep 验证）

**gene_scores.db 引用**：
- `limitup_screener/data.py:14` — `_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), default_config.DB_PATH)`
- `config/__init__.py:167` / `config.py:93` — `DB_PATH: str = "vibe_research.db"`
- `routers/sentiment_weather.py:21-25` — `_PARDON_DB_PATH` 指向 `limitup_screener/vibe_research.db`

**sti_timeline.db 引用**：
- `limitup_sti/data.py:16` — `DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vibe_research.db")`
- `routers/sentiment_weather.py:18` — `DB_PATH` 指向 `limitup_sti/vibe_research.db`

**winrate.db 引用**：
- `win_rate_tracker.py:53` — `__init__(self, db_path: str = "data/winrate.db")`
- `win_rate_tracker.py:278/304/335` — 3 处模块级函数硬编码 `sqlite3.connect("data/winrate.db")`
- `strategies/strategy_optimizer.py:19` — `__init__(self, db_path: str = "data/winrate.db")`
- `routers/health.py:30` — `winrate_path = "data/winrate.db"`
- `settlement_recorder.py:29` — docstring 引用 `data/winrate.db` 约定

## 3. 需求清单

### 路径常量统一

- [ ] R1 `config/__init__.py`：加 `PRIVATE_DATA_DIR` 常量（`os.path.join(_BACKEND_DIR, ".vibe-research")`）+ 三库文件名常量：`GENE_SCORES_DB = "gene_scores.db"` / `STI_TIMELINE_DB = "sti_timeline.db"` / `WINRATE_DB = "winrate.db"`。
- [ ] R2 `config.py`（旧文件，如仍被引用）：同步加常量或 re-export from `config/__init__.py`。
- [ ] R3 `default_config.DB_PATH` 改为指向 `.vibe-research/gene_scores.db` 的语义（或废弃 `DB_PATH` 字段，改用 `GENE_SCORES_DB_PATH` 全路径常量）。

### 代码路径改写

- [ ] R4 `limitup_screener/data.py`：`_DB_PATH` 改为从 config 取 `os.path.join(PRIVATE_DATA_DIR, GENE_SCORES_DB)`，不再 `os.path.join(__file__, ...)`。
- [ ] R5 `limitup_sti/data.py`：`DB_PATH` 同理改为从 config取 `os.path.join(PRIVATE_DATA_DIR, STI_TIMELINE_DB)`。
- [ ] R6 `routers/sentiment_weather.py`：`DB_PATH`（sti）和 `_PARDON_DB_PATH`（screener）改为从 config 取对应常量。
- [ ] R7 `win_rate_tracker.py`：`__init__` 默认参数 + 3 处模块级函数 `sqlite3.connect` 改为从 config 取 `os.path.join(PRIVATE_DATA_DIR, WINRATE_DB)`。
- [ ] R8 `strategies/strategy_optimizer.py`：`__init__` 默认参数同理。
- [ ] R9 `routers/health.py`：`winrate_path` 改为从 config 取。
- [ ] R10 `settlement_recorder.py`：`_get_tracker()` docstring 更新路径约定描述。

### 数据迁移脚本

- [ ] R11 写 `scripts/migrate_dbs.py`：
  1. `cp` 三个旧库到 `.vibe-research/` 新路径（新文件名）
  2. 验证行数：`SELECT count(*) FROM <table>` 旧库 == 新库
  3. 旧库改名 `.bak`（留同目录）
  4. `.vibe-research/` 目录不存在则 `mkdir -p`
  5. 幂等：新库已存在且行数匹配则跳过（防重复迁移）

### 测试适配

- [ ] R12 `tests/test_s034_settlement.py`：注释/docstring 中 `winrate.db` 路径描述更新（测试用 tmp 注入，路径字符串不受影响，但注释要保持准确）。
- [ ] R13 `conftest.py`：如有 DB 路径相关 fixture / monkeypatch，适配新常量。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/config/__init__.py` | R1 加 PRIVATE_DATA_DIR + 三库文件名常量 |
| `backend/config.py` | R2 同步或 re-export |
| `backend/limitup_screener/data.py` | R4 _DB_PATH 改从 config 取 |
| `backend/limitup_sti/data.py` | R5 DB_PATH 改从 config 取 |
| `backend/routers/sentiment_weather.py` | R6 DB_PATH + _PARDON_DB_PATH 改从 config 取 |
| `backend/win_rate_tracker.py` | R7 默认参数 + 3 处模块级函数 |
| `backend/strategies/strategy_optimizer.py` | R8 默认参数 |
| `backend/routers/health.py` | R9 winrate_path |
| `backend/settlement_recorder.py` | R10 docstring |
| `backend/tests/test_s034_settlement.py` | R12 注释更新 |
| `backend/conftest.py` | R13 适配（如有） |
| `scripts/migrate_dbs.py`（新） | R11 迁移脚本 |

## 5. 设计方案

### D1 路径锚点统一

所有 DB 路径从 `config.default_config`（或 config 模块级常量）取，基于 `_BACKEND_DIR`（项目根）。消除 `os.path.join(__file__, ...)`（依赖文件物理位置）和 cwd 相对（依赖启动目录）两种不可靠锚点。

### D2 config 常量设计

```python
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVATE_DATA_DIR = os.path.join(_BACKEND_DIR, ".vibe-research")

# DB 文件名（语义命名，不再共用 vibe_research.db）
GENE_SCORES_DB = "gene_scores.db"
STI_TIMELINE_DB = "sti_timeline.db"
WINRATE_DB = "winrate.db"

# 全路径便捷常量
GENE_SCORES_DB_PATH = os.path.join(PRIVATE_DATA_DIR, GENE_SCORES_DB)
STI_TIMELINE_DB_PATH = os.path.join(PRIVATE_DATA_DIR, STI_TIMELINE_DB)
WINRATE_DB_PATH = os.path.join(PRIVATE_DATA_DIR, WINRATE_DB)
```

各模块改为 `from config import GENE_SCORES_DB_PATH` 等，不再自己拼路径。

### D3 废弃 default_config.DB_PATH

`DB_PATH: str = "vibe_research.db"` 是 limitup_screener 专用，改名后语义不清。改为 `GENE_SCORES_DB_NAME = "gene_scores.db"`，`limitup_screener/data.py` 从 config 取全路径 `GENE_SCORES_DB_PATH`。旧 `DB_PATH` 字段保留但标 deprecated，防 breakage。

### D4 迁移脚本幂等设计

脚本先检查新路径文件是否存在且行数匹配——是则跳过；否则执行 cp + 验证 + bak。可重复运行不报错。

### D5 不合库

三个库 schema 无关，合库需统一 migration 框架——YAGNI。

## 6. 验收标准

- [ ] A1 `scripts/migrate_dbs.py` 执行成功：三库在新路径存在，行数与旧库一致
- [ ] A2 旧库改名 `.bak` 保留在同目录
- [ ] A3 `rg "vibe_research.db" backend/ --glob '*.py'`（排除 .venv）零命中
- [ ] A4 `rg '"data/winrate.db"' backend/ --glob '*.py'`（排除 .venv）零命中
- [ ] A5 所有 DB 路径引用从 config 取，无 `os.path.join(__file__` 残留
- [ ] A6 `pytest -m "not live"` 全过
- [ ] A7 迁移脚本幂等：二次执行不报错、不重复 cp
- [ ] A8 live 冒烟：启动后端，`GET /api/limitup/screener/report` 能读 gene_scores；`GET /api/winrate/stats` 能读 winrate；`GET /api/sentiment-weather` 能读 sti_timeline

## 7. 合规与工程底线自查

- [ ] 不涉及研判/数据输出/买卖时机——纯路径迁移
- [ ] 用户私有数据（winrate 交易记录）迁移到 `.vibe-research/`，符合私有数据隔离约定
- [ ] gene_scores 是公开榜单衍生计算，非用户私有
- [ ] 不涉及东财端点
- [ ] 迁移脚本不删除旧库（改 .bak），数据安全

## 8. 测试计划

- **迁移脚本单测**：构造 tmp 旧库 → 运行脚本 → 验证新库行数 + 旧库 .bak 存在 + 幂等二次执行
- **代码路径单测**：`limitup_screener/data.py` 的 `_DB_PATH` 指向 config 常量；`win_rate_tracker.WinRateTracker()` 默认路径指向 config 常量
- **离线全量**：`cd backend && .venv/bin/python -m pytest -m "not live"`
- **live 冒烟**（手动）：运行迁移脚本 → 启动后端 → A8 三个端点能读数据
- **回滚验证**：`mv .bak` 回原路径 + `git revert` 代码 → 系统恢复旧路径

## 9. 风险与回滚

- 🟡 **数据迁移风险**：cp + 验证行数可捕获大部分问题；极端情况（SQLite WAL 模式下 cp 时机不当）可能 cp 到不一致快照。**缓解**：迁移脚本在 cp 前对源库 `PRAGMA wal_checkpoint(TRUNCATE)` 确保全量落盘。
- 🟡 **config.py vs config/__init__.py 双入口**：`config.py` 是旧文件，`config/__init__.py` 取代了它。需确认 `config.py` 是否还被直接 import（Python 包优先级：`config/__init__.py` > `config.py`）。**缓解**：grep 确认 `from config import` 全部走包入口；`config.py` 如已被遮蔽则只改 `__init__.py`。
- 🟡 **conftest.py monkeypatch**：`conftest.py:28-29` monkeypatch `st._DB_PATH` / `wsr._DB_PATH`——这些是 `scheduled_tasks` / `workflow_state_repo` 的 `market_data.db` 路径，不在本 spec 范围，但需确认不受 config 常量改动影响。
- 🟢 回滚：旧库 `.bak` 留存 + `git revert` 代码改动 = 完全恢复。
