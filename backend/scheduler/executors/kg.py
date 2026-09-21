# -*- coding: utf-8 -*-
"""kg executors——知识图谱审查/数据同步。"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("vibe-research")


def daily_kg_audit(payload: Dict[str, Any]) -> Dict[str, Any]:
    """知识图谱每日审查——跑 daily_audit.py 生成审查报告。

    每天收盘后跑，检查断链/孤立/coverage/confidence 覆盖率。
    报告写到 vault 的 reviews/YYYY-MM-DD-daily-audit.md。
    """
    vault_path = Path("/Users/lizhiwei/Documents/Obsidian Vault")
    script = vault_path / "scripts" / "daily_audit.py"

    if not script.exists():
        logger.warning("[daily_kg_audit] daily_audit.py 不存在，跳过")
        return {"status": "script_not_found"}

    try:
        result = subprocess.run(
            ["python3", str(script), "--quiet"],
            capture_output=True, text=True, timeout=60,
            cwd=str(vault_path),
        )
        if result.returncode == 0:
            logger.info("[daily_kg_audit] %s", result.stdout.strip())
            return {"status": "ok", "output": result.stdout.strip()}
        else:
            logger.error("[daily_kg_audit] 审查失败: %s", result.stderr[:200])
            return {"status": "error", "error": result.stderr[:200]}
    except subprocess.TimeoutExpired:
        logger.warning("[daily_kg_audit] 审查超时（60s）")
        return {"status": "timeout"}
    except Exception as e:
        logger.error("[daily_kg_audit] 异常: %s", e)
        return {"status": "error", "error": str(e)}


def daily_kg_sync(payload: Dict[str, Any]) -> Dict[str, Any]:
    """知识图谱每日数据同步——从后端 API 拉情绪数据更新 scores/ + DASHBOARD。

    每天 16:00（收盘后）跑 daily_sync.py：拉 /api/market/emotion + /api/indices →
    写 scores/YYYY-MM-DD_score.md → 刷新情绪仪表盘预编译块 → 重跑 precompile/
    refresh_stats/daily_audit → git commit + push。超时 300s，错误不阻断主调度循环。

    与 daily_kg_audit 的分工：audit 跑结构审查（断链/孤立/coverage），sync 跑数据更新
    （拉 API 写 scores 刷 DASHBOARD）。sync 先跑（16:00）audit 后跑（可晚于 sync）。
    """
    vault_path = Path("/Users/lizhiwei/Documents/Obsidian Vault")
    script = vault_path / "scripts" / "daily_sync.py"

    if not script.exists():
        logger.warning("[daily_kg_sync] daily_sync.py 不存在，跳过")
        return {"status": "script_not_found"}

    try:
        result = subprocess.run(
            ["python3", str(script)],
            capture_output=True, text=True, timeout=600,
            cwd=str(vault_path),
        )
        if result.returncode == 0:
            logger.info("[daily_kg_sync] %s", result.stdout.strip()[-500:])
            return {"status": "ok", "output": result.stdout.strip()[-500:]}
        else:
            logger.warning("[daily_kg_sync] 同步失败: %s", result.stderr[:300])
            return {"status": "error", "error": result.stderr[:300]}
    except subprocess.TimeoutExpired:
        logger.warning("[daily_kg_sync] 同步超时（300s）")
        return {"status": "timeout"}
    except Exception as e:
        logger.error("[daily_kg_sync] 异常: %s", e)
        return {"status": "error", "error": str(e)}


def kg_inject(payload: Dict[str, Any]) -> Dict[str, Any]:
    """M7 注入流 executor：扫 payload codes 公告 → LLM 提取 → inbox/ 待审。

    payload: {codes: ["600519", ...], limit: 10}。codes 缺返 error（不自动扫涨停池，
    手动触发用 POST /api/kg/inject?code= 或 cron 传 codes）。
    """
    from tools.kg_inject import inject_announcements_to_inbox  # noqa: PLC0415
    codes = payload.get("codes") or []
    limit = int(payload.get("limit", 10))
    if not codes:
        return {"status": "no_codes", "error": "payload.codes 缺（手动触发用 POST /api/kg/inject?code=）"}
    results = [inject_announcements_to_inbox(c, limit=limit) for c in codes]
    n_injected = sum(1 for r in results if r.get("status") == "ok")
    logger.info("[kg_inject] %d codes → %d injected", len(codes), n_injected)
    return {"status": "ok", "n_codes": len(codes), "n_injected": n_injected, "results": results}
