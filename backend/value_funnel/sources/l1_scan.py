"""S005 L1 全市场扫描：按行业/主题/指数/关键词扫描主要上市公司。

合规：只列客观候选（按成交额/市值排序的公开榜单），不推荐、不预测。
ST/*ST/退市在 L1 即剔除；未上市候选（无代码）由调用方另行处理。
"""

from __future__ import annotations

from typing import Optional

from .. import quality  # 复用 _akshare


def _akshare():
    return quality._akshare()


def _is_st(name: str) -> bool:
    n = (name or "").strip().upper()
    return n.startswith("ST") or n.startswith("*ST") or "退" in n


def scan_universe(direction: str, top_n: int = 60) -> list[dict]:
    """扫描方向 → 候选列表 [{code, name}]。

    策略（按优先级，任一成功即返回）：
      1. 行业板块成分：akshare stock_board_industry_cons_em
      2. 概念板块成分：akshare stock_board_concept_cons_em
      3. 指数成分：akshare index_stock_cons（沪深300等）
      4. 兜底：全市场 spot，按名称/行业含 direction 关键词过滤，按成交额取 top_n
    """
    if not direction:
        return []
    ak = _akshare()
    # 1. 行业成分
    res = _try_industry_cons(ak, direction)
    if res:
        return _finalize(res, top_n)
    # 2. 概念成分
    res = _try_concept_cons(ak, direction)
    if res:
        return _finalize(res, top_n)
    # 3. 指数成分
    res = _try_index_cons(ak, direction)
    if res:
        return _finalize(res, top_n)
    # 4. 兜底：全市场过滤
    return _fallback_keyword(ak, direction, top_n)


def _try_industry_cons(ak, name: str) -> Optional[list[dict]]:
    try:
        df = ak.stock_board_industry_cons_em(symbol=name)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return [{"code": str(r.get("代码") or r.get("code")), "name": str(r.get("名称") or r.get("name"))}
            for _, r in df.iterrows()]


def _try_concept_cons(ak, name: str) -> Optional[list[dict]]:
    try:
        df = ak.stock_board_concept_cons_em(symbol=name)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return [{"code": str(r.get("代码") or r.get("code")), "name": str(r.get("名称") or r.get("name"))}
            for _, r in df.iterrows()]


def _try_index_cons(ak, name: str) -> Optional[list[dict]]:
    idx_map = {"沪深300": "000300", "上证50": "000016", "中证500": "000905",
               "创业板指": "399006", "科创50": "000688"}
    sym = idx_map.get(name)
    if not sym:
        return None
    try:
        df = ak.index_stock_cons_csindex(symbol=sym)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    col_code = "成分券代码" if "成分券代码" in df.columns else df.columns[0]
    col_name = "成分券名称" if "成分券名称" in df.columns else df.columns[1]
    return [{"code": str(r[col_code]).zfill(6), "name": str(r[col_name])}
            for _, r in df.iterrows()]


def _fallback_keyword(ak, keyword: str, top_n: int) -> list[dict]:
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception:
        return []
    if df is None or df.empty:
        return []
    # 名称含关键词或行业含关键词
    name_col = "名称" if "名称" in df.columns else None
    if name_col is None:
        return []
    mask = df[name_col].str.contains(keyword, na=False)
    sub = df[mask]
    if sub.empty:
        # 无匹配，按成交额取全市场 top_n 作为候选
        amt_col = "成交额" if "成交额" in df.columns else None
        sub = df.sort_values(amt_col, ascending=False).head(top_n) if amt_col else df.head(top_n)
    out = [{"code": str(r.get("代码")), "name": str(r.get("名称"))} for _, r in sub.iterrows()]
    return out[:top_n]


def _finalize(candidates: list[dict], top_n: int) -> list[dict]:
    """去 ST/退市，去重，限 top_n。"""
    seen, out = set(), []
    for c in candidates:
        code, name = c.get("code", ""), c.get("name", "")
        if not code or _is_st(name) or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": name})
        if len(out) >= top_n:
            break
    return out
