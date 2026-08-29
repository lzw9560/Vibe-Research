"""S058：战法卡查询工具。

读 strategies/cards/<code>.md 返回文本；AI 三出口（chat/MCP/cli_runtime）透明复用。
code 不存在返 error dict（registry 惯例）；别名检索（aliases）。

S102：运行时拼接「历史战绩」段（win_rate/avg_return/sample_size + §44 口径）。
战绩从 run_strategy_backtest（12h 缓存）取；缓存未命中时异步触发预计算不阻塞返回
（卡片查询是高频热路径，不能等 ~2min 满回测）。战绩差（win<50% 且 n>=30）标红警告。
"""
from __future__ import annotations

import threading
from pathlib import Path

from .registry import register_tool

_CARDS_DIR = Path(__file__).resolve().parent.parent.parent / "strategies" / "cards"

# S102：战绩预计算触发节流（同一战法 5min 内不重复触发异步预计算）
_BACKTEST_TRIGGER_TS: dict[str, float] = {}
_BACKTEST_TRIGGER_COOLDOWN = 300.0  # 5min


def _resolve_strategy_code(code_or_alias: str) -> str | None:
    """按 code 或别名解析出战法 code。"""
    from limitup_strategy import STRATEGY_REGISTRY

    s_lower = str(code_or_alias).strip().lower()
    for s in STRATEGY_REGISTRY:
        if s["code"].lower() == s_lower:
            return s["code"]
        for a in s.get("aliases", []):
            if a.lower() == s_lower:
                return s["code"]
    return None


def _build_backtest_section(code: str) -> str:
    """构建「历史战绩」段（S102 运行时拼接）。

    从 run_strategy_backtest（12h 缓存）取该战法 win_rate/avg_return/sample_size。
    缓存未命中 → 返「战绩待算」+ 异步触发预计算（不阻塞卡片查询）。
    §44 口径：n<30 标样本不足；win<50% 且 n>=30 标红警告（战绩差）。
    """
    import time

    try:
        from strategies.strategy_backtest import _CACHE, _CACHE_TS, _CACHE_TTL, run_strategy_backtest
    except Exception:  # noqa: BLE001 — strategy_backtest import 失败不阻塞卡片
        return ""

    lookback = 60
    cache_key = (lookback, None)
    now = time.time()
    cached = cache_key in _CACHE and now - _CACHE_TS.get(cache_key, 0) < _CACHE_TTL

    if not cached:
        # 缓存未命中：异步触发预计算（节流），本次返"待算"不阻塞
        _trigger_backtest_async(code)
        return (
            "\n## 历史战绩\n"
            "战绩计算中（首次查询触发，约 2min，12h 缓存后秒回）。\n"
        )

    results = _CACHE.get(cache_key, [])
    result = next((r for r in results if r.strategy_code == code), None)
    if result is None or result.sample_size == 0:
        return (
            "\n## 历史战绩\n"
            "无样本（该战法在回测窗口内未命中）。\n"
        )

    n = result.sample_size
    win = result.win_rate
    avg = result.avg_return
    win_pct = win * 100

    # §44 口径判定
    if n < 30:
        sample_note = f"n={n}<30 样本不足，不下结论"
        verdict = "探索性"
    elif win < 0.50:
        sample_note = f"n={n}"
        verdict = "⚠️ 战绩偏弱（胜率<50%）"  # 标红警告
    else:
        sample_note = f"n={n}"
        verdict = "历史正胜率"

    return (
        f"\n## 历史战绩（{lookback}日回测）\n"
        f"- 胜率 {win_pct:.1f}% · 均值收益 {avg:+.2f}% · 样本 {n}\n"
        f"- §44 口径：{sample_note}，{verdict}，未 validated\n"
    )


def _trigger_backtest_async(code: str) -> None:
    """异步触发 run_strategy_backtest 预计算（填 12h 缓存），不阻塞调用方。

    节流：同一 code 在 _BACKTEST_TRIGGER_COOLDOWN 内不重复触发。
    守护线程 fire-and-forget，失败静默（缓存填不上则下次查询仍返"待算"）。
    """
    import time

    now = time.time()
    last = _BACKTEST_TRIGGER_TS.get(code, 0.0)
    if now - last < _BACKTEST_TRIGGER_COOLDOWN:
        return  # 节流期内，不重复触发
    _BACKTEST_TRIGGER_TS[code] = now

    def _run() -> None:
        try:
            from strategies.strategy_backtest import run_strategy_backtest
            run_strategy_backtest(60)  # 填 12h 缓存
        except Exception:  # noqa: BLE001 — 异步预计算失败静默
            pass

    threading.Thread(target=_run, daemon=True).start()


@register_tool(
    "query_strategy_card",
    "查战法卡片：适用天气/核心逻辑/入场条件/退出参数/历史战绩/风险点。按战法 code 或别名检索。"
    "返回 Markdown 文本（含运行时拼接的 60 日回测战绩段），供 AI 解读战法逻辑+历史表现。",
    params={"code": {"description": "战法 code 或别名（如 first_plate / 首板 / consecutive_relay / 连板）"}},
)
def query_strategy_card(code: str) -> dict:
    resolved = _resolve_strategy_code(str(code))
    if not resolved:
        return {"error": f"未知战法 code 或别名：{code}"}
    card_path = _CARDS_DIR / f"{resolved}.md"
    if not card_path.exists():
        return {"error": f"战法卡片文件缺失：{resolved}.md"}
    card = card_path.read_text(encoding="utf-8")
    # S102：运行时拼接历史战绩段（插在「风险点」段前，避免破坏尾部风险提醒）
    backtest_section = _build_backtest_section(resolved)
    if backtest_section:
        card = _insert_before_section(card, "风险点", backtest_section)
    return {
        "code": resolved,
        "card": card,
    }


def _insert_before_section(card: str, section_name: str, insert_text: str) -> str:
    """把 insert_text 插在 `## {section_name}` 段前；找不到则追加到末尾。"""
    marker = f"## {section_name}"
    idx = card.find(marker)
    if idx == -1:
        return card.rstrip() + "\n" + insert_text
    return card[:idx] + insert_text + card[idx:]

