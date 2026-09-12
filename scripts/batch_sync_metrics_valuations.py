#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_sync_metrics_valuations.py — 批量拉取 401 只股票的财务/估值/行情数据，
灌入 vault 的 metrics/ 与 valuations/。

数据源（import astock，与 sync_real_data.py 同源）：
  - astock.financials(code)          → 财务摘要（akshare，不封 IP）
  - astock.full_valuation(code)      → 完整估值（东财 em_get，限流）
  - astock.valuation_percentile(code)→ PE/PB 历史分位（百度股市通 近5年）
  - astock.tencent_quote([code])     → 实时行情（腾讯，不封 IP）

与 sync_real_data.py 区别：
  - 全量 401 只（从 stocks/ 目录扫描），而非 21 只硬编码；
  - 对缺失的 metrics/valuations 文件**从模板创建**再填充（sync 脚本只更新已有文件）；
  - 限流：每只 sleep 2s（em_get 防封底线），每 20 只批间 sleep 5s；
  - 断路器：full_valuation 连续 3 只失败 → 后续跳过 full_valuation 与
    valuation_percentile（均走 em_get 系东财源），只拉 financials + tencent_quote；
  - 失败字段标"获取失败"不崩溃；
  - 报告写 docs/metrics-valuation-batch-report.md。

用法：
    /Users/lizhiwei/project/code/stock/Vibe-Research/backend/.venv/bin/python \
        /Users/lizhiwei/project/code/stock/Vibe-Research/scripts/batch_sync_metrics_valuations.py

合规：本脚本只按代码拉客观数据写盘，不预置标的、不排名、不建议。
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from datetime import date
from pathlib import Path

# ── astock 导入 ────────────────────────────────────────────────────────────
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
TEMPLATE_METRIC = VAULT_DIR / "templates" / "metric.md"
TEMPLATE_VALUATION = VAULT_DIR / "templates" / "valuation.md"
REPORT_PATH = Path("/Users/lizhiwei/project/code/stock/Vibe-Research/docs/metrics-valuation-batch-report.md")

TODAY = date.today().isoformat()  # YYYY-MM-DD

# ── 限流参数 ────────────────────────────────────────────────────────────────
PER_STOCK_SLEEP = 2.0   # 每只之间 sleep（em_get 防封底线）
BATCH_SIZE = 20         # 每 20 只一批
BATCH_SLEEP = 5.0        # 批间 sleep
EM_FAIL_CIRCUIT = 3     # 连续 N 只东财源失败 → 断路

# ── frontmatter 解析/写回（与 sync_real_data.py 一致）─────────────────────
FM_RE = re.compile(r"\A---\n(.*?\n)---\n(.*)\Z", re.DOTALL)
KV_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


def parse_frontmatter(text: str) -> tuple[dict, str, list[tuple[str, str]]]:
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
    if value is None:
        return "待实时"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if s == "" or any(c in s for c in [":", "#", "\n", '"', "'"]) or s.lower() in ("true", "false", "null"):
        return json.dumps(s, ensure_ascii=False)
    return s


def set_field(kv_list: list[tuple[str, str]], key: str, value) -> bool:
    for i, (k, _) in enumerate(kv_list):
        if k == key:
            kv_list[i] = (key, _yaml_scalar(value))
            return True
    kv_list.append((key, _yaml_scalar(value)))
    return False


def render_frontmatter(kv_list: list[tuple[str, str]], body: str) -> str:
    fm_text = "\n".join(f"{k}: {v}" for k, v in kv_list)
    return f"---\n{fm_text}\n---\n{body}"


# ── 数值规范化 ────────────────────────────────────────────────────────────
def _strip_unit(v) -> str | None:
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


def _fmt_market_cap(mcap_yi) -> str:
    if mcap_yi is None:
        return "待实时"
    try:
        m = float(mcap_yi)
    except (TypeError, ValueError):
        return "待实时"
    if m >= 10000:
        return f"{m / 10000:.2f}T"
    return f"{m:.2f}亿"


# ── 股票列表读取 ──────────────────────────────────────────────────────────
def read_stock_codes() -> list[str]:
    """从 stocks/ 目录扫描全部 6 位代码（跳过 index/README/MOC 等非股票文件）。"""
    if not STOCKS_DIR.exists():
        print(f"[FATAL] stocks 目录不存在：{STOCKS_DIR}", file=sys.stderr)
        sys.exit(2)
    codes: list[str] = []
    for p in sorted(STOCKS_DIR.glob("*.md")):
        name = p.stem
        if name.lower() in ("index", "readme", "moc"):
            continue
        if re.fullmatch(r"\d{6}", name):
            codes.append(name)
    return codes


def read_stock_name(code: str) -> str:
    """从 stocks/{code}.md 的 frontmatter 读 name 字段（失败返回 code 占位）。"""
    path = STOCKS_DIR / f"{code}.md"
    if not path.exists():
        return code
    try:
        d, _, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        return d.get("name") or code
    except Exception:
        return code


# ── 模板渲染（从模板创建 metrics/valuations 文件）─────────────────────────
METRIC_BODY = """# 财务摘要

- 股票代码：`{code}`（链接 [[stocks/{code}]]）
- 名称：{name}
- 报告期：待实时
- 营收（亿）：待实时
- 归母净利（亿）：待实时
- EPS：待实时
- BVPS：待实时
- 每股经营现金流：待实时

# 盈利能力

- ROE：待实时%
- 毛利率：待实时%
- 净利率：待实时%

# 趋势

```dataview
TABLE period AS "周期", revenue AS "营收(亿)", net_profit AS "净利(亿)", roe AS "ROE%", gross_margin AS "毛利率%"
FROM "10_Reference/investing/metrics"
WHERE type = "metric" AND code = this.code
SORT period ASC
```

# 所属股票

```dataview
TABLE name AS "名称", industry AS "行业"
FROM "10_Reference/investing/stocks"
WHERE type = "stock" AND code = this.code
```
"""

VALUATION_BODY = """# 估值快照

- 股票代码：`{code}`（链接 [[stocks/{code}]]）
- 名称：{name}
- PE(TTM)：待实时
- PB：待实时
- PS(TTM)：待实时
- PCF(TTM)：待实时
- 股息率：待实时%
- PEG：待实时
- 远期 PE：待实时

# 历史分位

- PE 历史分位：待实时%
- PB 历史分位：待实时%

> 分位口径待统一（3 年/5 年/全上市以来）。建议在 `data-sources` 的估值源笔记里记录口径。

# 一致预期

- 一致预期 EPS：待实时

# 所属股票

```dataview
TABLE name AS "名称", industry AS "行业", market_cap AS "市值"
FROM "10_Reference/investing/stocks"
WHERE type = "stock" AND code = this.code
```

# 历史估值序列

```dataview
TABLE created AS "日期", pe_ttm AS "PE(TTM)", pb AS "PB", pe_percentile AS "PE分位%"
FROM "10_Reference/investing/valuations"
WHERE type = "valuation" AND code = this.code
SORT created DESC
```
"""


def create_metric_file(code: str, name: str) -> Path:
    """从模板创建 metrics/{code}-latest.md（若已存在则不覆盖）。"""
    path = METRICS_DIR / f"{code}-latest.md"
    if path.exists():
        return path
    fm_lines = [
        "---",
        f"type: metric",
        f"code: {code}",
        f"name: {name}",
        f"period: ",
        f"revenue: ",
        f"net_profit: ",
        f"roe: ",
        f"gross_margin: ",
        f"net_margin: ",
        f"eps: ",
        f"bvps: ",
        f"op_cf_ps: ",
        f"created: {TODAY}",
        "---",
        "",
    ]
    body = METRIC_BODY.format(code=code, name=name)
    path.write_text("\n".join(fm_lines) + body, encoding="utf-8")
    return path


def create_valuation_file(code: str, name: str) -> Path:
    """从模板创建 valuations/{code}-latest.md（若已存在则不覆盖）。"""
    path = VALUATIONS_DIR / f"{code}-latest.md"
    if path.exists():
        return path
    fm_lines = [
        "---",
        f"type: valuation",
        f"code: {code}",
        f"pe_ttm: ",
        f"pb: ",
        f"ps_ttm: ",
        f"pcf_ttm: ",
        f"dividend_yield: ",
        f"peg: ",
        f"forward_pe: ",
        f"consensus_eps: ",
        f"pe_percentile: ",
        f"pb_percentile: ",
        f"created: {TODAY}",
        "---",
        "",
    ]
    body = VALUATION_BODY.format(code=code, name=name)
    path.write_text("\n".join(fm_lines) + body, encoding="utf-8")
    return path


# ── 单股数据拉取（带断路器开关）──────────────────────────────────────────
def fetch_one(code: str, skip_em: bool = False) -> dict:
    """拉一只股票数据。skip_em=True 时跳过东财源（full_valuation + valuation_percentile）。"""
    result: dict = {"code": code}

    # 1) 财务摘要（akshare，不封 IP）
    try:
        fin = astock.financials(code)
        result["financials"] = fin if fin else None
        result["financials_err"] = None if fin else "empty_result"
    except Exception as e:
        result["financials"] = None
        result["financials_err"] = f"{type(e).__name__}: {e}"

    # 2) 完整估值（东财 em_get，限流）—— 受断路器控制
    if skip_em:
        result["full_valuation"] = None
        result["full_valuation_err"] = "circuit_open"
        result["valuation_percentile"] = None
        result["valuation_percentile_err"] = "circuit_open"
    else:
        try:
            val = astock.full_valuation(code)
            result["full_valuation"] = val if val else None
            result["full_valuation_err"] = None if val else "empty_result"
        except Exception as e:
            result["full_valuation"] = None
            result["full_valuation_err"] = f"{type(e).__name__}: {e}"

        # 3) 估值分位（百度股市通，独立于东财但同样易限流）—— 受断路器控制
        try:
            pct = astock.valuation_percentile(code)
            result["valuation_percentile"] = pct if pct else None
            result["valuation_percentile_err"] = None if pct else "empty_result"
        except Exception as e:
            result["valuation_percentile"] = None
            result["valuation_percentile_err"] = f"{type(e).__name__}: {e}"

    # 4) 实时行情（腾讯，不封 IP，可批量但此处单只）
    try:
        q = astock.tencent_quote([code])
        result["tencent_quote"] = q.get(code) if q else None
        result["tencent_quote_err"] = None if (q and q.get(code)) else "empty_result"
    except Exception as e:
        result["tencent_quote"] = None
        result["tencent_quote_err"] = f"{type(e).__name__}: {e}"

    return result


# ── 更新 metrics frontmatter + body ──────────────────────────────────────
def update_metrics(code: str, name: str, data: dict) -> dict:
    path = METRICS_DIR / f"{code}-latest.md"
    info: dict = {"ok": False, "path": str(path), "fields_updated": [], "errors": []}
    if not path.exists():
        info["errors"].append("文件不存在")
        return info
    text = path.read_text(encoding="utf-8")
    _, body, kv_list = parse_frontmatter(text)

    # 确保 name 字段存在（模板创建时已写，但旧文件可能无）
    set_field(kv_list, "name", name)

    fin = data.get("financials")
    if not fin:
        info["errors"].append(f"financials 拉取失败：{data.get('financials_err')}")
        for k in ["period", "revenue", "net_profit", "roe", "gross_margin", "net_margin", "eps", "bvps", "op_cf_ps"]:
            set_field(kv_list, k, "获取失败")
        info["fields_updated"].append("(financials 失败，字段标获取失败)")
    else:
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

    # body 同步（替换"待实时"占位）
    # ratio 值（roe/gross_margin/net_margin）astock 返回带"%"，统一规整为单个"%"
    def _ratio(v):
        s = _strip_unit(v)
        if s is None:
            return "获取失败"
        return s.rstrip("%")  # 后续拼接统一加一个"%"
    new_body = body
    if fin:
        replacements = {
            "报告期：待实时": f"报告期：{_strip_unit(fin.get('period')) or '获取失败'}",
            "营收（亿）：待实时": f"营收（亿）：{_strip_unit(fin.get('revenue')) or '获取失败'}",
            "归母净利（亿）：待实时": f"归母净利（亿）：{_strip_unit(fin.get('net_profit')) or '获取失败'}",
            "EPS：待实时": f"EPS：{_strip_unit(fin.get('eps')) or '获取失败'}",
            "BVPS：待实时": f"BVPS：{_strip_unit(fin.get('bvps')) or '获取失败'}",
            "每股经营现金流：待实时": f"每股经营现金流：{_strip_unit(fin.get('op_cf_ps')) or '获取失败'}",
            "ROE：待实时%": f"ROE：{_ratio(fin.get('roe'))}%",
            "毛利率：待实时%": f"毛利率：{_ratio(fin.get('gross_margin'))}%",
            "净利率：待实时%": f"净利率：{_ratio(fin.get('net_margin'))}%",
        }
        for old, new in replacements.items():
            new_body = new_body.replace(old, new)
    else:
        fail_repl = {
            "报告期：待实时": "报告期：获取失败",
            "营收（亿）：待实时": "营收（亿）：获取失败",
            "归母净利（亿）：待实时": "归母净利（亿）：获取失败",
            "EPS：待实时": "EPS：获取失败",
            "BVPS：待实时": "BVPS：获取失败",
            "每股经营现金流：待实时": "每股经营现金流：获取失败",
            "ROE：待实时%": "ROE：获取失败%",
            "毛利率：待实时%": "毛利率：获取失败%",
            "净利率：待实时%": "净利率：获取失败%",
        }
        for old, new in fail_repl.items():
            new_body = new_body.replace(old, new)

    path.write_text(render_frontmatter(kv_list, new_body), encoding="utf-8")
    info["ok"] = True
    return info


# ── 更新 valuations frontmatter + body ───────────────────────────────────
def update_valuations(code: str, name: str, data: dict) -> dict:
    path = VALUATIONS_DIR / f"{code}-latest.md"
    info: dict = {"ok": False, "path": str(path), "fields_updated": [], "errors": []}
    if not path.exists():
        info["errors"].append("文件不存在")
        return info
    text = path.read_text(encoding="utf-8")
    _, body, kv_list = parse_frontmatter(text)

    val = data.get("full_valuation")
    pct = data.get("valuation_percentile")
    q = data.get("tencent_quote")

    val_map = {
        "pe_ttm": None, "pb": None, "ps_ttm": None, "pcf_ttm": None,
        "peg": None, "forward_pe": None, "consensus_eps": None,
    }
    if val:
        val_map["pe_ttm"] = val.get("pe_ttm")
        val_map["pb"] = val.get("pb")
        val_map["ps_ttm"] = val.get("ps_ttm")
        val_map["pcf_ttm"] = val.get("pcf_ttm")
        val_map["peg"] = val.get("peg")
        val_map["forward_pe"] = val.get("pe_26e")
        val_map["consensus_eps"] = val.get("eps_26e")
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

    # 若 full_valuation 失败但 tencent_quote 有 pe_ttm/pb，作为降级值写入
    if (val_map["pe_ttm"] is None) and q:
        pe = q.get("pe_ttm")
        if pe is not None:
            pe_f = _to_float(pe)
            set_field(kv_list, "pe_ttm", pe_f if pe_f is not None else pe)
            info["fields_updated"].append(f"pe_ttm={pe}(降级:tencent_quote)")
    if (val_map["pb"] is None) and q:
        pb = q.get("pb")
        if pb is not None:
            pb_f = _to_float(pb)
            set_field(kv_list, "pb", pb_f if pb_f is not None else pb)
            info["fields_updated"].append(f"pb={pb}(降级:tencent_quote)")

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

    # dividend_yield: astock 公开门面未暴露，统一标获取失败
    set_field(kv_list, "dividend_yield", "获取失败")
    info["fields_updated"].append("dividend_yield=获取失败(astock未暴露)")

    set_field(kv_list, "source", "astock.full_valuation")
    set_field(kv_list, "last_synced", TODAY)

    # body 同步
    new_body = body
    if val:
        if val.get("pe_ttm") is not None:
            new_body = new_body.replace("- PE(TTM)：待实时", f"- PE(TTM)：`{val['pe_ttm']}`（astock.full_valuation）")
        if val.get("pb") is not None:
            new_body = new_body.replace("- PB：待实时", f"- PB：`{val['pb']}`（astock.full_valuation）")
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
    # 降级：用 tencent_quote 的 pe/pb 填 body
    if (not val or val.get("pe_ttm") is None) and q and q.get("pe_ttm") is not None:
        new_body = new_body.replace("- PE(TTM)：待实时", f"- PE(TTM)：`{q['pe_ttm']}`（tencent_quote 降级）")
    if (not val or val.get("pb") is None) and q and q.get("pb") is not None:
        new_body = new_body.replace("- PB：待实时", f"- PB：`{q['pb']}`（tencent_quote 降级）")

    # 股息率 + 缺失字段 body 同步
    new_body = new_body.replace("- 股息率：待实时%", "- 股息率：获取失败%（astock 未暴露，需 dividend_history 计算）")
    new_body = new_body.replace("- PS(TTM)：待实时", "- PS(TTM)：获取失败")
    new_body = new_body.replace("- PCF(TTM)：待实时", "- PCF(TTM)：获取失败")
    new_body = new_body.replace("- PEG：待实时", "- PEG：获取失败（无分析师覆盖/eps_26e 缺）")
    new_body = new_body.replace("- 远期 PE：待实时", "- 远期 PE：获取失败（无分析师覆盖）")
    new_body = new_body.replace("- 一致预期 EPS：待实时", "- 一致预期 EPS：获取失败（无分析师覆盖）")

    if pe_pct is not None:
        new_body = new_body.replace("- PE 历史分位：待实时%", f"- PE 历史分位：`{pe_pct}%`（百度股市通 近5年）")
    if pb_pct is not None:
        new_body = new_body.replace("- PB 历史分位：待实时%", f"- PB 历史分位：`{pb_pct}%`（百度股市通 近5年）")
    new_body = new_body.replace("- PE 历史分位：待实时%", "- PE 历史分位：获取失败%（百度股市通 无数据）")
    new_body = new_body.replace("- PB 历史分位：待实时%", "- PB 历史分位：获取失败%（百度股市通 无数据）")

    path.write_text(render_frontmatter(kv_list, new_body), encoding="utf-8")
    info["ok"] = True
    return info


# ── 报告生成 ──────────────────────────────────────────────────────────────
def build_report(results: list[dict], circuit_triggered: bool) -> str:
    total = len(results)
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

    fin_ok = sum(1 for r in results if r["data"].get("financials"))
    val_ok = sum(1 for r in results if r["data"].get("full_valuation"))
    pct_ok = sum(1 for r in results if r["data"].get("valuation_percentile"))
    qt_ok = sum(1 for r in results if r["data"].get("tencent_quote"))
    m_ok = sum(1 for r in results if r["metrics"].get("ok"))
    v_ok = sum(1 for r in results if r["valuations"].get("ok"))

    metrics_count = len(list(METRICS_DIR.glob("*-latest.md")))
    valuations_count = len(list(VALUATIONS_DIR.glob("*-latest.md")))

    lines = [
        "---",
        "type: report",
        "title: 财务/估值数据批量拉取报告",
        f"date: {TODAY}",
        f"total: {total}",
        f"success: {fully_ok}",
        f"partial: {partial}",
        f"failed: {failed}",
        "---",
        "",
        "# 财务/估值数据批量拉取报告",
        "",
        f"**同步日期**：{TODAY}",
        f"**股票总数**：{total}",
        f"**完全成功**（四源齐）：{fully_ok}",
        f"**部分成功**（1-3 源）：{partial}",
        f"**完全失败**（零源）：{failed}",
        f"**断路器触发**：{'是（东财源连续失败，后续跳过 full_valuation + valuation_percentile）' if circuit_triggered else '否'}",
        "",
        "## 各源成功率",
        "",
        f"| 数据源 | 成功 | 失败 | 成功率 |",
        f"|---|---|---|---|",
        f"| astock.financials（akshare） | {fin_ok} | {total - fin_ok} | {fin_ok/total*100:.1f}% |",
        f"| astock.full_valuation（东财 em_get） | {val_ok} | {total - val_ok} | {val_ok/total*100:.1f}% |",
        f"| astock.valuation_percentile（百度） | {pct_ok} | {total - pct_ok} | {pct_ok/total*100:.1f}% |",
        f"| astock.tencent_quote（腾讯） | {qt_ok} | {total - qt_ok} | {qt_ok/total*100:.1f}% |",
        "",
        "## vault 文件落盘统计",
        "",
        f"- metrics/ 总文件数：{metrics_count}（目标 401）",
        f"- valuations/ 总文件数：{valuations_count}（目标 401）",
        f"- metrics 文件成功更新：{m_ok}",
        f"- valuations 文件成功更新：{v_ok}",
        "",
        "## 数据源",
        "",
        "- `astock.financials(code)` → 财务摘要（akshare，不封 IP）",
        "- `astock.full_valuation(code)` → 完整估值（东财 em_get，限流）",
        "- `astock.valuation_percentile(code)` → PE/PB 历史分位（百度股市通 近5年）",
        "- `astock.tencent_quote([code])` → 实时行情（腾讯，不封 IP）",
        "",
        "## 限流与断路",
        "",
        f"- 每只之间 sleep {PER_STOCK_SLEEP}s（em_get 防封底线）",
        f"- 每 {BATCH_SIZE} 只批间 sleep {BATCH_SLEEP}s",
        f"- 东财源连续 {EM_FAIL_CIRCUIT} 只失败 → 触发断路，后续跳过 full_valuation + valuation_percentile，只拉 financials + tencent_quote",
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
                return "OK"
            err = d.get(f"{key}_err") or "empty"
            return f"FAIL({err})"
        errs = []
        for k in ["financials", "full_valuation", "valuation_percentile", "tencent_quote"]:
            if not d.get(k):
                errs.append(f"{k}: {d.get(f'{k}_err', 'empty')}")
        err_str = "; ".join(errs) if errs else "—"
        lines.append(f"| {code} | {mark('financials')} | {mark('full_valuation')} | {mark('valuation_percentile')} | {mark('tencent_quote')} | {err_str} |")

    lines.extend([
        "",
        "## 处置建议",
        "",
        "- 完全失败的股票（零源）：检查网络/代理，或该股票是否退市/停牌；可后续重跑本脚本单股补拉。",
        "- `dividend_yield` 全部为`获取失败`：astock 公开门面未暴露股息率字段，需走 `astock.dividend_history` 自行计算或新增门面函数。",
        "- 部分失败的股票：对应源的数据源可能限流/熔断（em_get breaker），重跑通常可恢复。",
        "- 断路器触发后跳过的 full_valuation/valuation_percentile 可在限流恢复后单独补拉（跑 sync_real_data.py 对应子集）。",
        "",
        f"> 报告由 `scripts/batch_sync_metrics_valuations.py` 于 {TODAY} 自动生成。",
    ])
    return "\n".join(lines) + "\n"


# ── 主流程 ────────────────────────────────────────────────────────────────
def main() -> int:
    codes = read_stock_codes()
    print(f"[batch] 扫描到 {len(codes)} 只股票，日期 {TODAY}")
    print(f"[batch] 限流：每只 sleep {PER_STOCK_SLEEP}s，每 {BATCH_SIZE} 只批间 sleep {BATCH_SLEEP}s")
    print(f"[batch] 断路阈值：东财源连续 {EM_FAIL_CIRCUIT} 只失败")

    # 预创建缺失的 metrics/valuations 文件（从模板）
    created_metrics = 0
    created_valuations = 0
    for code in codes:
        name = read_stock_name(code)
        if not (METRICS_DIR / f"{code}-latest.md").exists():
            create_metric_file(code, name)
            created_metrics += 1
        if not (VALUATIONS_DIR / f"{code}-latest.md").exists():
            create_valuation_file(code, name)
            created_valuations += 1
    print(f"[batch] 预创建 metrics 文件：{created_metrics}，valuations 文件：{created_valuations}")

    results: list[dict] = []
    em_consecutive_fail = 0  # 东财源连续失败计数
    circuit_triggered = False
    skip_em = False

    t0 = time.time()
    for i, code in enumerate(codes, 1):
        name = read_stock_name(code)
        elapsed = time.time() - t0
        print(f"[{i}/{len(codes)}] {code} {name} 拉取中... (已耗时 {elapsed:.0f}s)", flush=True)

        data = fetch_one(code, skip_em=skip_em)

        # 诊断输出
        for src in ["financials", "full_valuation", "valuation_percentile", "tencent_quote"]:
            if data.get(src):
                print(f"  OK {src}", flush=True)
            else:
                print(f"  FAIL {src}: {data.get(f'{src}_err')}", flush=True)

        # 断路器判定：东财源 = full_valuation（valuation_percentile 走百度，但同样易限流，一并计入）
        # 连续 EM_FAIL_CIRCUIT 只 full_valuation 失败 → 触发断路
        if not skip_em:
            if data.get("full_valuation"):
                em_consecutive_fail = 0
            else:
                em_consecutive_fail += 1
                if em_consecutive_fail >= EM_FAIL_CIRCUIT:
                    skip_em = True
                    circuit_triggered = True
                    print(f"  [BREAKER] 东财源连续 {em_consecutive_fail} 只失败，触发断路，后续跳过 full_valuation + valuation_percentile", flush=True)

        # 写盘
        m_info = update_metrics(code, name, data)
        v_info = update_valuations(code, name, data)
        results.append({"code": code, "name": name, "data": data, "metrics": m_info, "valuations": v_info})
        print(f"  -> metrics:{'ok' if m_info['ok'] else 'FAIL'}  valuations:{'ok' if v_info['ok'] else 'FAIL'}", flush=True)

        # 限流：非最后一只时 sleep
        if i < len(codes):
            time.sleep(PER_STOCK_SLEEP)
        # 批间额外 sleep
        if i % BATCH_SIZE == 0 and i < len(codes):
            print(f"[batch] 第 {i//BATCH_SIZE} 批完成，批间 sleep {BATCH_SLEEP}s...", flush=True)
            time.sleep(BATCH_SLEEP)

    # 报告
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(build_report(results, circuit_triggered), encoding="utf-8")
    print(f"\n[batch] 报告已写入：{REPORT_PATH}")

    # 汇总
    fully_ok = sum(1 for r in results if all([r["data"].get("financials"), r["data"].get("full_valuation"), r["data"].get("valuation_percentile"), r["data"].get("tencent_quote")]))
    partial = sum(1 for r in results if any([r["data"].get("financials"), r["data"].get("full_valuation"), r["data"].get("valuation_percentile"), r["data"].get("tencent_quote")]) and not all([r["data"].get("financials"), r["data"].get("full_valuation"), r["data"].get("valuation_percentile"), r["data"].get("tencent_quote")]))
    failed = len(results) - fully_ok - partial
    print(f"[batch] 完成：完全成功 {fully_ok} / 部分成功 {partial} / 完全失败 {failed}（共 {len(results)}）")
    print(f"[batch] 总耗时：{time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
