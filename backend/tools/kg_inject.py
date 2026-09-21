"""M7 图谱注入流——公告→DeepSeek JSON→inbox/ markdown 待审。

调 astock.announcements（em_get 防封）+ chat._call_llm（VR_LLM env）提取实体 JSON，
写 vault/investing/inbox/{ts}-{code}-inject.md 待审。审过移 reference/。

合规（CLAUDE.md §1.2 工程底线）：
- 不臆造：LLM 输出进 inbox 待审，非直接进正式区
- 私有数据隔离：公告公开数据，不读持仓/研报
- 不碰选股分/§44v2——认知层非交易信号
- 秘密走 env：VR_LLM_API_KEY 走 os.environ，不贴 key 值
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("vibe-research")

_VAULT_INVESTING = Path(
    os.environ.get(
        "VR_KG_VAULT_PATH",
        "/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing",
    )
)
_INBOX_DIR = _VAULT_INVESTING / "inbox"
_REFERENCE_DIR = _VAULT_INVESTING / "reference"

# M7 LLM 提取实体的 prompt
_EXTRACT_PROMPT = """你是投研知识图谱助手。从以下A股公告中提取实体信息，返 JSON：
{{
  "entities": [
    {{"name": "公司/行业/概念名", "type": "stock/industry/concept/event", "code": "股票代码或空", "key_facts": "1-2句关键事实"}}
  ],
  "relationships": [
    {{"from": "实体A", "to": "实体B", "relation": "属于/合作/竞争/供应等"}}
  ]
}}
只返 JSON，不要其他文字。公告内容：
{announcements}
"""


def inject_announcements_to_inbox(code: str, limit: int = 10) -> dict[str, Any]:
    """M7 注入流：拉 code 公告 → LLM 提取实体 JSON → 写 inbox/ markdown 待审。

    Returns: {status, code, n_announcements, n_entities, inbox_path}
    """
    import astock  # noqa: PLC0415
    from chat import _call_llm, _get_env_llm_config  # noqa: PLC0415

    # 1. 拉公告（em_get 防封）
    try:
        announcements = astock.announcements(code, limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("[M7] announcements 拉取失败 code=%s: %s", code, e)
        return {"status": "announcements_failed", "code": code, "error": str(e)[:200]}
    if not announcements:
        return {"status": "no_announcements", "code": code, "n_announcements": 0}

    # 2. LLM 提取实体 JSON
    ann_text = json.dumps(announcements, ensure_ascii=False)[:4000]  # 截断防超 token
    cfg = _get_env_llm_config()
    if not cfg.get("baseURL") or not cfg.get("apiKey"):
        return {"status": "llm_not_configured", "code": code, "error": "VR_LLM_BASE_URL/API_KEY 未设"}
    messages = [
        {"role": "system", "content": "你是投研知识图谱助手，从公告提取实体和关系，返 JSON。"},
        {"role": "user", "content": _EXTRACT_PROMPT.format(announcements=ann_text)},
    ]
    try:
        resp = _call_llm(cfg, messages, use_tools=False)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        # 解析 JSON（LLM 可能返 ```json 包裹）
        content = content.strip().strip("`").removeprefix("json").strip()
        extracted = json.loads(content)
    except Exception as e:  # noqa: BLE001
        logger.warning("[M7] LLM 提取失败 code=%s: %s", code, e)
        return {"status": "llm_failed", "code": code, "error": str(e)[:200]}

    # 3. 写 inbox/ markdown 待审
    _INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{ts}-{code}-inject.md"
    inbox_path = _INBOX_DIR / filename
    frontmatter = [
        "---",
        f"code: {code}",
        f"injected_at: {datetime.now().isoformat()}",
        "source: M7_LLM_inject",
        f"n_announcements: {len(announcements)}",
        "status: pending_review",
        "---",
        "",
    ]
    body = [
        f"# M7 注入待审：{code}",
        "",
        "## LLM 提取实体 JSON",
        "```json",
        json.dumps(extracted, ensure_ascii=False, indent=2),
        "```",
        "",
        f"## 源公告（前 {limit}）",
    ]
    for a in announcements[:limit]:
        body.append(f"- {a.get('date', '')} · {a.get('title', '')} · {a.get('type', '')}")
    inbox_path.write_text("\n".join(frontmatter + body), encoding="utf-8")

    n_entities = len(extracted.get("entities", [])) if isinstance(extracted, dict) else 0
    logger.info("[M7] 注入 code=%s: %d 公告 → %d 实体 → %s", code, len(announcements), n_entities, filename)
    return {
        "status": "ok",
        "code": code,
        "n_announcements": len(announcements),
        "n_entities": n_entities,
        "inbox_path": str(inbox_path),
    }


def approve_inbox_to_reference(filename: str) -> dict[str, Any]:
    """审过：inbox/{filename} → reference/{filename}（移到正式区）。

    Returns: {status, filename, reference_path}
    """
    src = _INBOX_DIR / filename
    if not src.exists():
        return {"status": "not_found", "filename": filename}
    _REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    dst = _REFERENCE_DIR / filename
    src.rename(dst)
    logger.info("[M7] 审过 %s → reference/", filename)
    return {"status": "ok", "filename": filename, "reference_path": str(dst)}


__all__ = ["inject_announcements_to_inbox", "approve_inbox_to_reference"]
