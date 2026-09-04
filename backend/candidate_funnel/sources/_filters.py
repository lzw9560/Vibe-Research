# -*- coding: utf-8 -*-
"""入口过滤：ST/*ST/退市/新股次新/停牌 剔除或标注（AC8）。

纯客观字符串判定，不含方向词。返回 (是否剔除, 原因|None)。
停牌需行情层判定（外部传入），此处仅做名称/代码客观分类。
"""

from __future__ import annotations

import re

# 退市相关前缀/关键字
_DELISTING_KEYWORDS = ("退市", "退", "CR")
# 新股/次新标识
_NEW_SHARE_KEYWORDS = ("N", "C", "N*", "C*")
# 上市年限判定由调用方按 list_date 传入，本函数只做名称标记


def classify_exclusion(name: str, code: str) -> tuple[bool, str | None]:
    """按名称客观分类是否应剔除出漏斗。

    返回 (excluded, reason)。excluded=True 表示剔除或单独标注，不与正常股混排。
    """
    if not name:
        return False, None

    n = name.strip()
    # ST/*ST
    if "ST" in n or "*ST" in n:
        return True, "ST/*ST 标的"
    # 退市整理
    if any(k in n for k in _DELISTING_KEYWORDS):
        return True, "退市整理期标的"
    # 新股次新（N/C 开头标识）
    if re.match(r"^(N|C)\*?[A-Z一-龥]", n):
        return True, "新股/次新标的"
    return False, None


def classify_board(code: str) -> str:
    """A 股板块分类（code 前缀）。全仓首个共享 board 分类，补 688/北交所空缺。

    主板 600/601/603/605/000/001/002/003；创业板 300/301；科创板 688/689；
    北交所 4/8 开头（43/83/87…）及 920（2024+ 新码段，待 acceptance 验证）。
    其余 → 其他（保留不剔除，避免误伤可交易标的）。
    """
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith("920") or code.startswith(("4", "8")):
        return "北交所"
    if code.startswith(("6", "0")):
        return "主板"
    return "其他"


def classify_tradability(
    name: str, code: str, radar_set: dict[str, str] | None = None,
) -> tuple[bool, str | None, str | None]:
    """可交易性过滤（S148 R2）。扩展 classify_exclusion：加 board 排除 + ST 摘帽/重组 carve-out。

    返回 (keep, reason, st_play)。
    - board ∈ {创业板, 科创板, 北交所} → 排除（无权限硬约束，优先于 ST carve-out）
    - ST/*ST 且 code ∈ radar_set → 保留 + st_play=radar_set[code]（摘帽/重组/扭亏 carve-out）
    - ST/*ST 且 code ∉ radar_set → 排除
    - 退市/新股次新 → 排除（沿用 classify_exclusion，无 carve-out）
    - 其余 → 保留

    停牌不在此函数（S148 descope；盘中自行跳过）。
    radar_set=None → 等价空白名单 → ST flat 排除（radar 未上线前的安全默认）。
    """
    radar = radar_set or {}
    # board 硬约束优先：无权限的板，摘帽也救不了
    board = classify_board(code)
    if board in ("创业板", "科创板", "北交所"):
        return False, f"{board} 不可交易（无权限）", None
    # 名称缺失 → 无法判定 ST（ST 靠名称子串），fail-closed 排除（S148 审计：原空 name
    # 走 classify_exclusion 返 (False,None) → keep=True 泄漏 ST 股为可交易，unsafe direction）。
    if not name or not name.strip():
        return False, "名称缺失，无法判定 ST/可交易性（fail-closed）", None
    # 沿用 classify_exclusion 的 ST/退市/新股 客观分类
    excluded, reason = classify_exclusion(name, code)
    if not excluded:
        return True, None, None
    # ST 的 carve-out：在 radar 白名单 → re-include + st_play
    if "ST" in (reason or "") and code in radar:
        return True, None, radar[code]
    return False, reason, None
