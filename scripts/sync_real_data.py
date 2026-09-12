#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_real_data.py — 用 Vibe-Research 后端 astock 模块拉取 21 只股票的真实财务/估值/行情数据，
更新 Obsidian vault 的 metrics/ / valuations/ / stocks/ 实体 frontmatter（当前是占位值"待实时"）。

数据源（直接 import astock，方式 2）：
  - astock.financials(code)        → 财务摘要（revenue/net_profit/roe/gross_margin/net_margin/eps/bvps/op_cf_ps）
  - astock.full_valuation(code)    → 完整估值（pe_ttm/pb/ps_ttm/pcf_ttm/peg/forward_pe/consensus_eps）
  - astock.valuation_percentile(code) → 估值分位（pe_percentile/pb_percentile）
  - astock.tencent_quote([code])   → 实时行情（price/market_cap/pe_ttm/pb/turnover_rate）

容错：每只股票每步 try-except，失败标"获取失败"不阻塞其他。

用法：
    /Users/lizhiwei/project/code/stock/Vibe-Research/backend/.venv/bin/python \
        /Users/lizhiwei/project/code/stock/Vibe-Research/scripts/sync_real_data.py

合规：本脚本只按代码拉客观数据写盘，不预置标的、不排名、不建议。
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from datetime import date
from pathlib import Path

# ── astock 导入（方式 2：直接 import）──────────────────────────────────────
BACKEND_DIR = "/Users/lizhiwei/project/code/stock/Vibe-Research/backend"
sys.path.insert(0, BACKEND_DIR)

try:
    import astock  # noqa: E402
except Exception as e:  # pragma: no cover
    print(f"[FATAL] 导入 astock 失败：{e}", file=sys.stderr)
    traceback.print_exc()
    sys.exit(2)

# ── 路径 ────────────────────────────────────────────────────────────────────
VAULT_DIR = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing")
METRICS_DIR = VAULT_DIR / "metrics"
VALUATIONS_DIR = VAULT_DIR / "valuations"
STOCKS_DIR = VAULT_DIR / "stocks"
REPORT_PATH = Path("/Users/lizhiwei/project/code/stock/Vibe-Research/docs/real-data-sync-report.md")

# ── 21 只股票 ──────────────────────────────────────────────────────────────
CODES = [
    "600519", "000858", "300750", "688981", "002594", "002156", "002185",
    "002281", "600522", "600584", "601899", "003040", "600869", "002354",
    "601086", "600127", "688836", "300058", "600611", "605398", "605580",
]

TODAY = date.today().isoformat()  # YYYY-MM-DD

# ── frontmatter 解析/写回（round-trip 保留顺序与注释）─────────────────────
FM_RE = re.compile(r"\A---\n(.*?\n)---\n(.*)\Z", re.DOTALL)
# 单行 key: value（值不带引号或带引号都支持；我们只处理简单标量）
KV_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


def parse_frontmatter(text: str) -> tuple[dict, str, list[tuple[str, str]]]:
    """返回 (dict, body, ordered_kv_list)。ordered_kv_list 保留原文件顺序用于写回。"""
    m = FM_RE.match(text)
    if not m:
        return {}, text, []
    fm_text, body = m.group(1), m.group(2)
    kv_list: list[tuple[str, str]] = []
    for line in fm_text.split("\n"):
        kv = KV_RE.match(line)
        if kv:
            k, v = kv.group(1), kv.group(2).rstrip()
            kv_list.append((k, v))
    d = dict(kv_list)
    return d, body, kv_list


def _yaml_scalar(value) -> str:
    """把 Python 值渲染成 yaml 标量字符串（简单实现，够用）。"""
    if value is None:
        return "待实时"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        # 保留数值形式，避免被 yaml 当字符串
        return repr(value) if isinstance(value, bool) else str(value)
    s = str(value)
    # 含特殊字符则加引号；纯数值/普通字符串不加
    if s == "" or any(c in s for c in [":", "#", "\n", '"', "'"]) or s.lower() in ("true", "false", "null"):
        return json.dumps(s, ensure_ascii=False)
    return s


def set_field(kv_list: list[tuple[str, str]], key: str, value) -> bool:
    """更新或插入 frontmatter 字段，返回是否命中已有键。"""
    for i, (k, _) in enumerate(kv_list):
        if k == key:
            kv_list[i] = (key, _yaml_scalar(value))
            return True
    kv_list.append((key, _yaml_scalar(value)))
    return False


def render_frontmatter(kv_list: list[tuple[str, str]], body: str) -> str:
    fm_text = "\n".join(f"{k}: {v}" for k, v in kv_list)
    return f"---\n{fm_text}\n---\n{body}"


# ── 数值规范化（astock 返回值常带"亿"/"%"等后缀，vault 想要干净标量）────────
def _strip_unit(v) -> str | None:
    """astock financials 返回 "922.78亿" / "16.75%" / "35.5700"。
    vault metrics frontmatter 期望保留原始可读字符串（与现有风格一致，如 revenue: 922.78亿）。
    但为便于 dataview 数值排序，能转 float 的转成纯数字字符串。
    """
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "--", "false", "False"):
        return None
    return s


def _to_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("亿", "").replace("万", "").replace("%", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _fmt_market_cap(mcap_yi: float | None) -> str:
    """mcap_yi 单位为亿。转成人类可读：>=10000 亿 → X.YT，否则 X.YY亿。"""
    if mcap_yi is None:
        return "待实时"
    try:
        m = float(mcap_yi)
    except (TypeError, ValueError):
        return "待实时"
    if m >= 10000:
        return f"{m / 10000:.2f}T"
    return f"{m:.2f}亿"


# ── 单股数据拉取 ────────────────────────────────────────────────────────────
def fetch_one(code: str) -> dict:
    """拉一只股票的全部数据，返回结构化 dict。每步独立 try-except。"""
    result: dict = {"code": code}
    # 1) 财务摘要
    try:
        fin = astock.financials(code)
        result["financials"] = fin if fin else None
        result["financials_err"] = None if fin else "empty_result"
    except Exception as e:
        result["financials"] = None
        result["financials_err"] = f"{type(e).__name__}: {e}"

    # 2) 完整估值
    try:
        val = astock.full_valuation(code)
        result["full_valuation"] = val if val else None
        result["full_valuation_err"] = None if val else "empty_result"
    except Exception as e:
        result["full_valuation"] = None
        result["full_valuation_err"] = f"{type(e).__name__}: {e}"

    # 3) 估值分位
    try:
        pct = astock.valuation_percentile(code)
        result["valuation_percentile"] = pct if pct else None
        result["valuation_percentile_err"] = None if pct else "empty_result"
    except Exception as e:
        result["valuation_percentile"] = None
        result["valuation_percentile_err"] = f"{type(e).__name__}: {e}"

    # 4) 实时行情
    try:
        q = astock.tencent_quote([code])
        result["tencent_quote"] = q.get(code) if q else None
        result["tencent_quote_err"] = None if (q and q.get(code)) else "empty_result"
    except Exception as e:
        result["tencent_quote"] = None
        result["tencent_quote_err"] = f"{type(e).__name__}: {e}"

    return result


# ── 更新 metrics frontmatter + body ─────────────────────────────────────────
def update_metrics(code: str, data: dict) -> dict:
    """更新 metrics/{code}-latest.md。返回 {ok, path, note}。"""
    path = METRICS_DIR / f"{code}-latest.md"
    info: dict = {"ok": False, "path": str(path), "fields_updated": [], "errors": []}
    if not path.exists():
        info["errors"].append("文件不存在")
        return info
    text = path.read_text(encoding="utf-8")
    _, body, kv_list = parse_frontmatter(text)

    fin = data.get("financials")
    if not fin:
        info["errors"].append(f"financials 拉取失败：{data.get('financials_err')}")
        # 财务字段全部标"获取失败"
        for k in ["revenue", "net_profit", "roe", "gross_margin", "net_margin", "eps", "bvps", "op_cf_ps"]:
            set_field(kv_list, k, "获取失败")
        info["fields_updated"] = ["(financials 失败，字段标获取失败)"]
    else:
        # astock financials 字段映射
        mapping = [
            ("period", "period"),
            ("revenue", "revenue"),
            ("net_profit", "net_profit"),
            ("roe", "roe"),
            ("gross_margin", "gross_margin"),
            ("net_margin", "net_margin"),
            ("eps", "eps"),
            ("bvps", "bvps"),
            ("op_cf_ps", "op_cf_ps"),
        ]
        for fm_key, src_key in mapping:
            v = _strip_unit(fin.get(src_key))
            if v is not None:
                set_field(kv_list, fm_key, v)
                info["fields_updated"].append(f"{fm_key}={v}")
            else:
                set_field(kv_list, fm_key, "获取失败")
                info["fields_updated"].append(f"{fm_key}=获取失败")

    set_field(kv_list, "source", "astock.financials")
    set_field(kv_list, "last_synced", TODAY)
    info["fields_updated"].extend([f"source=astock.financials", f"last_synced={TODAY}"])

    # 同步更新 body 中的"待实时"行（保持文件内部一致）
    new_body = body
    if fin:
        replacements = {
            "营收（亿）：待实时": f"营收（亿）：{_strip_unit(fin.get('revenue')) or '获取失败'}",
            "归母净利（亿）：待实时": f"归母净利（亿）：{_strip_unit(fin.get('net_profit')) or '获取失败'}",
            "EPS：待实时": f"EPS：{_strip_unit(fin.get('eps')) or '获取失败'}",
            "BVPS：待实时": f"BVPS：{_strip_unit(fin.get('bvps')) or '获取失败'}",
            "每股经营现金流：待实时": f"每股经营现金流：{_strip_unit(fin.get('op_cf_ps')) or '获取失败'}",
            "ROE：待实时%": f"ROE：{_strip_unit(fin.get('roe')) or '获取失败'}",
            "毛利率：待实时%": f"毛利率：{_strip_unit(fin.get('gross_margin')) or '获取失败'}",
            "净利率：待实时%": f"净利率：{_strip_unit(fin.get('net_margin')) or '获取失败'}",
        }
        for old, new in replacements.items():
            new_body = new_body.replace(old, new)
    else:
        repl_fail = {
            "营收（亿）：待实时": "营收（亿）：获取失败",
            "归母净利（亿）：待实时": "归母净利（亿）：获取失败",
            "EPS：待实时": "EPS：获取失败",
            "BVPS：待实时": "BVPS：获取失败",
            "每股经营现金流：待实时": "每股经营现金流：获取失败",
            "ROE：待实时%": "ROE：获取失败",
            "毛利率：待实时%": "毛利率：获取失败",
            "净利率：待实时%": "净利率：获取失败",
        }
        for old, new in repl_fail.items():
            new_body = new_body.replace(old, new)

    # 报告期同步（如果拉到了真实 period）
    if fin and fin.get("period"):
        new_body = re.sub(r"报告期：[^\n]*", f"报告期：{fin['period']}", new_body)

    path.write_text(render_frontmatter(kv_list, new_body), encoding="utf-8")
    info["ok"] = True
    return info


# ── 更新 valuations frontmatter + body ──────────────────────────────────────
def update_valuations(code: str, data: dict) -> dict:
    """更新 valuations/{code}-latest.md。"""
    path = VALUATIONS_DIR / f"{code}-latest.md"
    info: dict = {"ok": False, "path": str(path), "fields_updated": [], "errors": []}
    if not path.exists():
        info["errors"].append("文件不存在")
        return info
    text = path.read_text(encoding="utf-8")
    _, body, kv_list = parse_frontmatter(text)

    val = data.get("full_valuation")
    pct = data.get("valuation_percentile")

    val_map = {
        "pe_ttm": None, "pb": None, "ps_ttm": None, "pcf_ttm": None,
        "peg": None, "forward_pe": None, "consensus_eps": None,
    }
    if val:
        # full_valuation 返回字段：pe_ttm/pb/ps_ttm/pcf_ttm/peg/pe_26e/eps_26e
        val_map["pe_ttm"] = val.get("pe_ttm")
        val_map["pb"] = val.get("pb")
        val_map["ps_ttm"] = val.get("ps_ttm")
        val_map["pcf_ttm"] = val.get("pcf_ttm")
        val_map["peg"] = val.get("peg")
        val_map["forward_pe"] = val.get("pe_26e")  # 远期 PE = pe_26e
        val_map["consensus_eps"] = val.get("eps_26e")  # 一致预期 EPS = eps_26e
    else:
        info["errors"].append(f"full_valuation 拉取失败：{data.get('full_valuation_err')}")

    # 分位
    pe_pct = pb_pct = None
    if pct and isinstance(pct.get("metrics"), dict):
        m = pct["metrics"]
        if "pe_ttm" in m and isinstance(m["pe_ttm"], dict):
            pe_pct = m["pe_ttm"].get("percentile")
        if "pb" in m and isinstance(m["pb"], dict):
            pb_pct = m["pb"].get("percentile")
    else:
        info["errors"].append(f"valuation_percentile 拉取失败：{data.get('valuation_percentile_err')}")

    # 写 frontmatter
    for k, v in val_map.items():
        if v is not None:
            f = _to_float(v)
            set_field(kv_list, k, f if f is not None else v)
            info["fields_updated"].append(f"{k}={v}")
        else:
            set_field(kv_list, k, "获取失败")
            info["fields_updated"].append(f"{k}=获取失败")

    if pe_pct is not None:
        set_field(kv_list, "pe_percentile", pe_pct)
        info["fields_updated"].append(f"pe_percentile={pe_pct}")
    else:
        set_field(kv_list, "pe_percentile", "获取失败")
        info["fields_updated"].append("pe_percentile=获取失败")

    if pb_pct is not None:
        set_field(kv_list, "pb_percentile", pb_pct)
        info["fields_updated"].append(f"pb_percentile={pb_pct}")
    else:
        set_field(kv_list, "pb_percentile", "获取失败")
        info["fields_updated"].append("pb_percentile=获取失败")

    # dividend_yield: astock 公开门面不直接提供，标"获取失败"（诚实缺失）
    set_field(kv_list, "dividend_yield", "获取失败")
    info["fields_updated"].append("dividend_yield=获取失败(astock未暴露)")

    set_field(kv_list, "source", "astock.full_valuation")
    set_field(kv_list, "last_synced", TODAY)
    info["fields_updated"].extend([f"source=astock.full_valuation", f"last_synced={TODAY}"])

    # body 同步（用正则匹配任意占位值，不硬编码 30.0/5.0/8.0）
    new_body = body
    if val:
        if val.get("pe_ttm") is not None:
            new_body = re.sub(
                r"PE\(TTM\)：`[^`]*`（从股票 frontmatter 抄）",
                f"PE(TTM)：`{val['pe_ttm']}`（astock.full_valuation）",
                new_body,
            )
            new_body = re.sub(r"^- PE\(TTM\)：`[^`]*`$", f"- PE(TTM)：`{val['pe_ttm']}`", new_body, flags=re.MULTILINE)
        if val.get("pb") is not None:
            new_body = re.sub(
                r"PB：`[^`]*`（从股票 frontmatter 抄）",
                f"PB：`{val['pb']}`（astock.full_valuation）",
                new_body,
            )
            new_body = re.sub(r"^- PB：`[^`]*`$", f"- PB：`{val['pb']}`", new_body, flags=re.MULTILINE)
        if val.get("ps_ttm") is not None:
            new_body = new_body.replace("- PS(TTM)：待实时", f"- PS(TTM)：`{val['ps_ttm']}`")
        if val.get("pcf_ttm") is not None:
            new_body = new_body.replace("- PCF(TTM)：待实时", f"- PCF(TTM)：`{val['pcf_ttm']}`")
        if val.get("peg") is not None:
            new_body = new_body.replace("- PEG：待实时", f"- PEG：`{val['peg']}`")
        if val.get("pe_26e") is not None:
            new_body = new_body.replace("- 远期 PE：待实时", f"- 远期 PE：`{val['pe_26e']}`（pe_26e）")
        if val.get("eps_26e") is not None:
            new_body = new_body.replace("- 一致预期 EPS：待实时", f"- 一致预期 EPS：`{val['eps_26e']}`（2026E 均值）")
    # 股息率：frontmatter 标"获取失败"，body 也同步（astock 公开门面未暴露）
    new_body = new_body.replace("- 股息率：待实时%", "- 股息率：获取失败%（astock 未暴露，需 dividend_history 计算）")
    # 缺失字段 body 同步标"获取失败"（与 frontmatter 一致：值 None 时 frontmatter 标获取失败）
    new_body = new_body.replace("- PS(TTM)：待实时", "- PS(TTM)：获取失败")
    new_body = new_body.replace("- PCF(TTM)：待实时", "- PCF(TTM)：获取失败")
    new_body = new_body.replace("- PEG：待实时", "- PEG：获取失败（无分析师覆盖/eps_26e 缺）")
    new_body = new_body.replace("- 远期 PE：待实时", "- 远期 PE：获取失败（无分析师覆盖）")
    new_body = new_body.replace("- 一致预期 EPS：待实时", "- 一致预期 EPS：获取失败（无分析师覆盖）")

    if pe_pct is not None:
        new_body = new_body.replace("- PE 历史分位：待实时%", f"- PE 历史分位：`{pe_pct}%`（百度股市通 近5年）")
    if pb_pct is not None:
        new_body = new_body.replace("- PB 历史分位：待实时%", f"- PB 历史分位：`{pb_pct}%`（百度股市通 近5年）")
    # 分位缺失时同步标获取失败
    new_body = new_body.replace("- PE 历史分位：待实时%", "- PE 历史分位：获取失败%（百度股市通 无数据）")
    new_body = new_body.replace("- PB 历史分位：待实时%", "- PB 历史分位：获取失败%（百度股市通 无数据）")

    path.write_text(render_frontmatter(kv_list, new_body), encoding="utf-8")
    info["ok"] = True
    return info


# ── 更新 stocks frontmatter ─────────────────────────────────────────────────
def update_stock(code: str, data: dict) -> dict:
    """更新 stocks/{code}.md 的 pe_ttm/pb/market_cap/last_synced。"""
    path = STOCKS_DIR / f"{code}.md"
    info: dict = {"ok": False, "path": str(path), "fields_updated": [], "errors": []}
    if not path.exists():
        info["errors"].append("文件不存在")
        return info
    text = path.read_text(encoding="utf-8")
    _, body, kv_list = parse_frontmatter(text)

    q = data.get("tencent_quote")
    if not q:
        info["errors"].append(f"tencent_quote 拉取失败：{data.get('tencent_quote_err')}")
        set_field(kv_list, "pe_ttm", "获取失败")
        set_field(kv_list, "pb", "获取失败")
        set_field(kv_list, "market_cap", "获取失败")
        info["fields_updated"].extend(["pe_ttm=获取失败", "pb=获取失败", "market_cap=获取失败"])
    else:
        pe = q.get("pe_ttm")
        pb = q.get("pb")
        mcap = _fmt_market_cap(q.get("mcap_yi"))
        # 数值化以便 dataview 排序；0.0 视为有效（停牌等）
        pe_f = _to_float(pe)
        pb_f = _to_float(pb)
        set_field(kv_list, "pe_ttm", pe_f if pe_f is not None else "获取失败")
        set_field(kv_list, "pb", pb_f if pb_f is not None else "获取失败")
        set_field(kv_list, "market_cap", mcap)
        info["fields_updated"].extend([
            f"pe_ttm={pe}", f"pb={pb}", f"market_cap={mcap}",
        ])

    set_field(kv_list, "last_synced", TODAY)
    info["fields_updated"].append(f"last_synced={TODAY}")

    # 更新 body 中的过时注释（pe_ttm/pb/market_cap 已非公开常识值，而是 astock 实时）
    new_body = body
    new_body = new_body.replace(
        "注：pe_ttm/pb/market_cap 为公开常识值，待实时更新。",
        f"注：pe_ttm/pb/market_cap 由 astock.tencent_quote 实时拉取（last_synced: {TODAY}）。",
    )

    path.write_text(render_frontmatter(kv_list, new_body), encoding="utf-8")
    info["ok"] = True
    return info


# ── 报告生成 ────────────────────────────────────────────────────────────────
def build_report(results: list[dict]) -> str:
    total = len(results)
    # 成功判定：financials + full_valuation + valuation_percentile + tencent_quote 四源都拉到
    fully_ok = sum(1 for r in results if all([
        r["data"].get("financials"), r["data"].get("full_valuation"),
        r["data"].get("valuation_percentile"), r["data"].get("tencent_quote"),
    ]))
    partial = sum(1 for r in results if any([
        r["data"].get("financials"), r["data"].get("full_valuation"),
        r["data"].get("valuation_percentile"), r["data"].get("tencent_quote"),
    ]) and not all([
        r["data"].get("financials"), r["data"].get("full_valuation"),
        r["data"].get("valuation_percentile"), r["data"].get("tencent_quote"),
    ]))
    failed = total - fully_ok - partial

    lines = [
        "---",
        "type: report",
        "title: 真实数据同步报告",
        f"date: {TODAY}",
        f"total: {total}",
        f"success: {fully_ok}",
        f"partial: {partial}",
        f"failed: {failed}",
        "---",
        "",
        "# 真实数据同步报告",
        "",
        f"**同步日期**：{TODAY}",
        f"**股票总数**：{total}",
        f"**完全成功**（四源齐）：{fully_ok}",
        f"**部分成功**（1-3 源）：{partial}",
        f"**完全失败**（零源）：{failed}",
        "",
        "## 数据源",
        "",
        "- `astock.financials(code)` → 财务摘要（同花顺财报）",
        "- `astock.full_valuation(code)` → 完整估值（腾讯行情 + 一致预期 EPS）",
        "- `astock.valuation_percentile(code)` → PE/PB 历史分位（百度股市通 近5年）",
        "- `astock.tencent_quote([code])` → 实时行情（PE/PB/市值）",
        "",
        "## 字段映射说明",
        "",
        "- `forward_pe` ← `full_valuation.pe_26e`（2026 远期 PE）",
        "- `consensus_eps` ← `full_valuation.eps_26e`（2026 一致预期 EPS 均值）",
        "- `dividend_yield` ← astock 公开门面未暴露，统一标`获取失败`（诚实缺失，非崩溃）",
        "- `market_cap` ← `tencent_quote.mcap_yi`（亿元）格式化为 `X.YY亿` 或 `X.YYT`",
        "",
        "## 逐股结果",
        "",
        "| 代码 | 财务 | 完整估值 | 估值分位 | 实时行情 | 失败原因 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        code = r["code"]
        d = r["data"]
        def mark(key):
            if d.get(key):
                return "✅"
            err = d.get(f"{key}_err") or "empty"
            return f"❌ {err}"
        errs = []
        for k in ["financials", "full_valuation", "valuation_percentile", "tencent_quote"]:
            if not d.get(k):
                errs.append(f"{k}: {d.get(f'{k}_err', 'empty')}")
        err_str = "; ".join(errs) if errs else "—"
        lines.append(f"| {code} | {mark('financials')} | {mark('full_valuation')} | {mark('valuation_percentile')} | {mark('tencent_quote')} | {err_str} |")

    lines.extend([
        "",
        "## vault 更新明细",
        "",
    ])
    for r in results:
        code = r["code"]
        lines.append(f"### {code}")
        for tag, info in [("metrics", r["metrics"]), ("valuations", r["valuations"]), ("stock", r["stock"])]:
            if info.get("ok"):
                lines.append(f"- **{tag}** (`{info['path']}`)：更新 {len(info.get('fields_updated', []))} 个字段")
            else:
                lines.append(f"- **{tag}：失败** — {', '.join(info.get('errors', ['unknown']))}")
        lines.append("")

    lines.extend([
        "## 处置建议",
        "",
        "- 完全失败的股票（零源）：检查网络/代理，或该股票是否退市/停牌；可后续重跑本脚本单股补拉。",
        "- `dividend_yield` 全部为`获取失败`：astock 公开门面未暴露股息率字段，需走 `astock.dividend_history` 自行计算或新增门面函数（S104 已有 PS/PCF 补全先例）。",
        "- 部分失败的股票：对应源的数据源可能限流/熔断（em_get breaker），重跑通常可恢复。",
        "",
        f"> 报告由 `scripts/sync_real_data.py` 于 {TODAY} 自动生成。",
    ])
    return "\n".join(lines) + "\n"


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"[sync] 开始同步 {len(CODES)} 只股票，日期 {TODAY}")
    results: list[dict] = []

    for i, code in enumerate(CODES, 1):
        print(f"[{i}/{len(CODES)}] {code} 拉取中...")
        data = fetch_one(code)
        # 诊断输出
        for src in ["financials", "full_valuation", "valuation_percentile", "tencent_quote"]:
            if data.get(src):
                print(f"  ✅ {src}")
            else:
                print(f"  ❌ {src}: {data.get(f'{src}_err')}")

        # 写盘
        m_info = update_metrics(code, data)
        v_info = update_valuations(code, data)
        s_info = update_stock(code, data)
        results.append({"code": code, "data": data, "metrics": m_info, "valuations": v_info, "stock": s_info})
        print(f"  → metrics:{'ok' if m_info['ok'] else 'FAIL'}  valuations:{'ok' if v_info['ok'] else 'FAIL'}  stock:{'ok' if s_info['ok'] else 'FAIL'}")

    # 报告
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(build_report(results), encoding="utf-8")
    print(f"\n[sync] 报告已写入：{REPORT_PATH}")

    # 汇总
    fully_ok = sum(1 for r in results if all([r["data"].get("financials"), r["data"].get("full_valuation"), r["data"].get("valuation_percentile"), r["data"].get("tencent_quote")]))
    partial = sum(1 for r in results if any([r["data"].get("financials"), r["data"].get("full_valuation"), r["data"].get("valuation_percentile"), r["data"].get("tencent_quote")]) and not all([r["data"].get("financials"), r["data"].get("full_valuation"), r["data"].get("valuation_percentile"), r["data"].get("tencent_quote")]))
    failed = len(results) - fully_ok - partial
    print(f"[sync] 完成：完全成功 {fully_ok} / 部分成功 {partial} / 完全失败 {failed}（共 {len(results)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
