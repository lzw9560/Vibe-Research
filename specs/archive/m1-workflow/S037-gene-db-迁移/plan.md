# 技术方案 · S037 gene DB 路径迁移

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 级别：large，feature 分支 `feature/S037-gene-db-migration`。

## 1. 文件结构与职责

### 改动
| 文件 | 改动 |
|---|---|
| `backend/config/__init__.py` | R1 加 PRIVATE_DATA_DIR + 三库文件名/全路径常量 |
| `backend/config.py` | R2 确认是否还被引用；若是则 re-export |
| `backend/limitup_screener/data.py` | R4 `_DB_PATH` 从 config 取 |
| `backend/limitup_sti/data.py` | R5 `DB_PATH` 从 config 取 |
| `backend/routers/sentiment_weather.py` | R6 两条硬编码路径改从 config 取 |
| `backend/win_rate_tracker.py` | R7 默认参数 + 3 处模块级函数 |
| `backend/strategies/strategy_optimizer.py` | R8 默认参数 |
| `backend/routers/health.py` | R9 winrate_path |
| `backend/settlement_recorder.py` | R10 docstring 更新 |
| `backend/tests/test_s034_settlement.py` | R12 注释更新 |
| `backend/conftest.py` | R13 适配（如有 DB 路径 fixture） |

### 新增
| 文件 | 职责 |
|---|---|
| `scripts/migrate_dbs.py` | R11 迁移脚本：cp 三库 + 验证行数 + 旧库改名 .bak + 幂等 |

## 2. config 常量设计

```python
# config/__init__.py
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVATE_DATA_DIR = os.path.join(_BACKEND_DIR, ".vibe-research")

GENE_SCORES_DB = "gene_scores.db"
STI_TIMELINE_DB = "sti_timeline.db"
WINRATE_DB = "winrate.db"

GENE_SCORES_DB_PATH = os.path.join(PRIVATE_DATA_DIR, GENE_SCORES_DB)
STI_TIMELINE_DB_PATH = os.path.join(PRIVATE_DATA_DIR, STI_TIMELINE_DB)
WINRATE_DB_PATH = os.path.join(PRIVATE_DATA_DIR, WINRATE_DB)
```

各模块改为 `from config import GENE_SCORES_DB_PATH` 等。旧 `default_config.DB_PATH` 标 deprecated。

## 3. 迁移脚本设计

```python
# scripts/migrate_dbs.py
MIGRATIONS = [
    {
        "name": "gene_scores",
        "old": "backend/limitup_screener/vibe_research.db",
        "new": ".vibe-research/gene_scores.db",
        "tables": ["gene_scores", "fuse_pardon_records", "migrations"],
    },
    {
        "name": "sti_timeline",
        "old": "backend/limitup_sti/vibe_research.db",
        "new": ".vibe-research/sti_timeline.db",
        "tables": ["sti_timeline", "migrations"],
    },
    {
        "name": "winrate",
        "old": "backend/data/winrate.db",
        "new": ".vibe-research/winrate.db",
        "tables": ["winrate_records", "migrations"],
    },
]
```

流程：
1. mkdir -p .vibe-research/
2. 对每个库：
   a. 新库已存在且行数匹配 -> 跳过（幂等）
   b. 旧库 PRAGMA wal_checkpoint(TRUNCATE) -> cp 到新路径 -> 验证行数 -> 旧库改名 .bak
3. 打印迁移报告

## 4. config.py 双入口排查

```bash
rg "from config import\|import config" backend/ --glob '*.py' | grep -v __pycache__ | grep -v .venv
```
确认所有 import 走 `config/__init__.py` 包入口。`config.py` 如已被遮蔽则只改 `__init__.py`。

## 5. conftest.py 排查

`conftest.py:28-29` monkeypatch `st._DB_PATH` / `wsr._DB_PATH` 是 `scheduled_tasks` / `workflow_state_repo` 的 `market_data.db`——不在本 spec 范围。确认不受 config 常量改动影响。
