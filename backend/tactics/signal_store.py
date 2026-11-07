# -*- coding: utf-8 -*-
"""signal_store —— 信号落库 SQLite（S235 T06，spec §5.3）。

含未成交信号 + 随机对照组，避免 survivorship 偏差：
- 每次触发（含未成交）落库完整因子快照 + 原始数据 JSON
- 同日随机选 N 只同市值段标的作 control，seed 可复现
- n≥60 才出 verdict（get_signals min_n 过滤 underpowered）

私有数据隔离：db 落 .vibe-research/（resolve_data_dir 复用 vr_paths，gitignored）。
"""

from __future__ import annotations
import json
import random
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from vr_paths import resolve_data_dir  # 复用现有私有数据目录解析

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    tactic_name TEXT,
    code TEXT,
    score INTEGER,
    is_triggered INTEGER,
    factors_json TEXT,
    raw_data_json TEXT,
    record_type TEXT DEFAULT 'signal',
    seed INTEGER,
    executed INTEGER DEFAULT 0,
    entry_price REAL,
    fill_price REAL,
    exit_price REAL,
    exit_reason TEXT,
    hold_days INTEGER,
    return_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_code ON signals(code);
CREATE INDEX IF NOT EXISTS idx_tactic ON signals(tactic_name);
CREATE INDEX IF NOT EXISTS idx_record_type ON signals(record_type);
"""


def _dumps(obj: Any) -> str:
    """JSON 序列化，None/空→'{}'，ensure_ascii=False 保中文可读。"""
    if obj is None:
        return "{}"
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _same_mc_bucket(a: float, b: float) -> bool:
    """同市值段判定：a 在 [0.5b, 2b]（且 a,b>0）。

    粗分桶（0.5x~2x），够对照组随机选；后续归因可换更细 decile。
    """
    if a <= 0 or b <= 0:
        return False
    return 0.5 * b <= a <= 2 * b


class SignalStore:
    """信号 + 对照组落库。无 ORM，纯 sqlite3 stdlib。"""

    def __init__(self, db_path: str | Path | None = None):
        # 默认落 .vibe-research/tactics_signals.db（VR_DATA_DIR 隔离）
        if db_path is None:
            db_path = resolve_data_dir() / "tactics_signals.db"
        self.db_path = str(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)

    def save_signal(
        self,
        *,
        tactic: str,
        code: str,
        score: int,
        is_triggered: bool,
        factors_json: Any,
        raw_data_json: Any,
        record_type: str = "signal",
        seed: int | None = None,
        entry_price: float | None = None,
    ) -> int:
        """落库一条 signal/control 记录，返回新行 id。"""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO signals (timestamp, tactic_name, code, score, "
                "is_triggered, factors_json, raw_data_json, record_type, seed, "
                "entry_price) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    tactic,
                    code,
                    int(score),
                    int(bool(is_triggered)),
                    _dumps(factors_json),
                    _dumps(raw_data_json),
                    record_type,
                    seed,
                    entry_price,
                ),
            )
            return cur.lastrowid

    def save_control_group(
        self,
        *,
        signal_code: str,
        all_stocks: list[dict],
        n: int = 5,
        seed: int | None = None,
        tactic: str = "",
        factors_json: Any = None,
        raw_data_json: Any = None,
    ) -> list[int]:
        """随机选 n 只同市值段标的落库为 control，返回新行 id 列表。

        seed 固定→选取可复现。同市值段空时退到全量（除信号自身）。
        """
        rng = random.Random(seed)
        signal = next((s for s in all_stocks if s.get("thscode") == signal_code), None)
        if signal is None:
            pool = [s for s in all_stocks if s.get("thscode") != signal_code]
        else:
            mc = float(signal.get("float_mv", 0) or 0)
            pool = [s for s in all_stocks if s.get("thscode") != signal_code and _same_mc_bucket(float(s.get("float_mv", 0) or 0), mc)]
            if not pool:  # 同市值段空，退到全量
                pool = [s for s in all_stocks if s.get("thscode") != signal_code]
        picks = rng.sample(pool, min(n, len(pool))) if pool else []
        ids = []
        for pick in picks:
            rid = self.save_signal(
                tactic=tactic,
                code=pick.get("thscode", ""),
                score=0,
                is_triggered=False,
                factors_json=factors_json or {},
                raw_data_json=raw_data_json or {},
                record_type="control",
                seed=seed,
                entry_price=None,
            )
            ids.append(rid)
        return ids

    def get_signals(self, tactic: str | None = None, min_n: int = 60) -> list[dict]:
        """查询 signal 记录。n<min_n→返空（underpowered，不出 verdict）。"""
        sql = "SELECT * FROM signals WHERE record_type='signal'"
        params: list = []
        if tactic:
            sql += " AND tactic_name=?"
            params.append(tactic)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        if len(rows) < min_n:
            return []
        return [dict(r) for r in rows]

    def get_control_group(self, date: str, tactic: str) -> list[dict]:
        """查询某日某战法的对照组（date=YYYY-MM-DD，匹配 timestamp 前 10 字符）。"""
        sql = "SELECT * FROM signals WHERE record_type='control' AND tactic_name=? AND substr(timestamp,1,10)=?"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, (tactic, date)).fetchall()
        return [dict(r) for r in rows]
