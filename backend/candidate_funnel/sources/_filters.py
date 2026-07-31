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
