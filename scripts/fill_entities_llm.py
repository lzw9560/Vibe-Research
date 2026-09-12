#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 批量充实图谱实体正文（4 类实体）。

实体类型与产出：
  1. stocks/   (前 50 大盘股，按市值降序) → 在 `## 📊 核心业务` 段后追加：
       ### 行业地位 / ### 核心竞争力 / ### 风险提示（各 2-3 句）
  2. analysts/ (前 50，按 coverage_count 降序) → 替换 `## 📋 覆盖领域` 段：
       覆盖领域 + 风格特点（1-2 句）
  3. reports/  (前 50，按 publish_date 降序) → 填充 `## 💡 核心观点` 段：
       报告摘要 + 核心结论（2-3 句）
  4. concepts/ (前 30 热门概念，按成分股数降序) → 在 callout 后追加：
       ## 📖 题材逻辑（题材逻辑 + 催化因素）

每段标 `<!-- LLM 生成，待人工校验 -->`。幂等：已含该注释的段跳过。
并发 8 线程，max_tokens=4096（deepseek-v4-pro 推理模型）。

用法：
  python3 scripts/fill_entities_llm.py              # 全量 4 类
  python3 scripts/fill_entities_llm.py --only stocks
  python3 scripts/fill_entities_llm.py --only stocks,analysts
  python3 scripts/fill_entities_llm.py --dry-run
  python3 scripts/fill_entities_llm.py --limit 5    # 每类仅处理 5 个（测试）

合规：只生成客观描述，不臆造具体财务数据，不构成投资建议。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings()

# ── 路径 ────────────────────────────────────────────────────────────────────
REPO = Path("/Users/lizhiwei/project/code/stock/Vibe-Research")
ENV_FILE = REPO / "backend" / ".env"
DOCS = REPO / "docs"
VAULT = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing")
DIRS = {
    "stocks": VAULT / "stocks",
    "analysts": VAULT / "analysts",
    "reports": VAULT / "reports",
    "concepts": VAULT / "concepts",
}

ANNOTATION = "<!-- LLM 生成，待人工校验 -->"


# ── LLM 调用 ─────────────────────────────────────────────────────────────────
def load_llm_config() -> tuple[str, str, str]:
    load_dotenv(ENV_FILE)
    base = os.environ.get("VR_LLM_BASE_URL", "").strip()
    key = os.environ.get("VR_LLM_API_KEY", "").strip()
    model = os.environ.get("VR_LLM_MODEL", "").strip()
    if not all([base, key, model]):
        raise SystemExit(f"LLM 配置缺失: base={base!r} model={model!r} key={'有' if key else '无'}")
    return base, key, model


def make_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 绕全局代理（百炼走内网 Tailscale HTTPS 自签证书）
    return s


def call_llm(session: requests.Session, base: str, key: str, model: str,
             prompt: str, timeout: int = 120) -> str | None:
    """调百炼 LLM，返回正文或 None。max_tokens=4096（推理模型 reasoning 占 ~2000）。"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        r = session.post(
            f"{base}/chat/completions",
            json=payload, headers=headers,
            verify=False, timeout=timeout,
        )
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except json.JSONDecodeError:
        return None
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError):
        return None
    content = (choice.get("message") or {}).get("content") or ""
    content = content.strip().strip("`").strip()
    # 去除 LLM 可能加的 markdown 代码块包裹
    if content.startswith("```"):
        content = re.sub(r"^```(?:\w+)?\n?", "", content)
        content = re.sub(r"\n?```$", "", content).strip()
    return content or None


# ── 通用 frontmatter 解析 ───────────────────────────────────────────────────
def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm


def find_section(text: str, header: str) -> tuple[int, int] | None:
    """返回(段起始下标, 段结束下标)。段=header 行起到下一个 ## 标题或文件尾。"""
    idx = text.find(header)
    if idx < 0:
        return None
    next_m = re.search(r"^## ", text[idx + len(header):], re.MULTILINE)
    end = idx + len(header) + (next_m.start() if next_m else len(text) - idx - len(header))
    return idx, end


# ════════════════════════════════════════════════════════════════════════════
# 0. stocks/ frontmatter 空值修复（任务 1）
# ════════════════════════════════════════════════════════════════════════════
def _stock_load_tencent_quote(codes: list[str]) -> dict[str, dict]:
    """从 tencent_quote 批量拉行情（pe_ttm/pb/mcap_yi）。失败返回 {}。
    
    本地导入 backend 包，复用 astock 门面。codes 上限 50（API 安全）。"""
    try:
        import sys as _sys
        _backend = str(REPO / "backend")
        if _backend not in _sys.path:
            _sys.path.insert(0, _backend)
        from data.sources.tencent import fetch_raw as _tencent_quote
    except Exception:
        return {}
    out: dict[str, dict] = {}
    # 分批 50 一批（API 上限）
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        try:
            r = _tencent_quote(batch)
            if isinstance(r, dict):
                out.update(r)
        except Exception:
            pass
    return out


def _stock_infer_industry_from_llm(session, base, key, model, name: str, code: str) -> str:
    """用 LLM 从股票名推断行业（仅 industry 为空时）。失败返"待核实"。"""
    prompt = (
        f"请为以下 A 股股票推断所属申万/中信一级行业分类（只给行业名，1-2 句不要解释）：\n"
        f"股票代码：{code}\n股票名称：{name}\n\n"
        f"格式：只输出行业名，例如「股份制与城商行」「电池材料」「半导体封测」，不要其他文字。"
    )
    txt = call_llm(session, base, key, model, prompt)
    if not txt:
        return "待核实"
    # 取第一行、去标点
    line = txt.splitlines()[0].strip()
    line = re.sub(r"[。.、，,]", "", line).strip()
    # 截断过长输出（防 LLM 失控）
    if len(line) > 20:
        line = line[:20]
    return line or "待核实"


def stock_fix_frontmatter(f: Path, session, base, key, model, quote_cache: dict) -> dict:
    """任务 1：修复单只股票 frontmatter 空值。
    
    - code/name 必填，空值标"待核实"（理论上不会空，兜底）
    - industry 空 → LLM 推断（失败标"待核实"）
    - pe_ttm/pb/market_cap 空 → tencent_quote 拉值（失败标"待实时"）
    幂等：只改空字段，不动有值字段。
    """
    code = f.stem
    try:
        text = f.read_text(encoding="utf-8")
    except Exception as e:
        return {"type": "stocks_fm", "code": code, "status": "error", "reason": f"读文件失败: {e}"}

    # 解析 frontmatter 原始文本块
    m = re.match(r"^(---\n)(.*?)(\n---\n)", text, re.DOTALL)
    if not m:
        return {"type": "stocks_fm", "code": code, "status": "skip", "reason": "无 frontmatter"}
    fm_text = m.group(2)
    # 当前字段值（去引号去首尾空格）
    fm = parse_frontmatter(text)

    name = fm.get("name", "")
    industry = fm.get("industry", "")
    pe_ttm = fm.get("pe_ttm", "")
    pb = fm.get("pb", "")
    market_cap = fm.get("market_cap", "")

    changed = False
    new_industry = industry
    new_pe = pe_ttm
    new_pb = pb
    new_mc = market_cap

    # industry 空 → LLM 推断
    if not industry:
        new_industry = _stock_infer_industry_from_llm(session, base, key, model, name, code)
        changed = True

    # pe_ttm/pb/market_cap 空 → tencent_quote
    if (not pe_ttm) or (not pb) or (not market_cap):
        q = quote_cache.get(code)
        if q is None:
            # 单票拉取（cache miss 时）
            q = _stock_load_tencent_quote([code]).get(code) or {}
        if q:
            if not pe_ttm and q.get("pe_ttm") is not None:
                v = q["pe_ttm"]
                # 保留原格式（float 直写，无多余 0）
                new_pe = f"{v:g}" if isinstance(v, (int, float)) else str(v)
                changed = True
            if not pb and q.get("pb") is not None:
                v = q["pb"]
                new_pb = f"{v:g}" if isinstance(v, (int, float)) else str(v)
                changed = True
            if not market_cap and q.get("mcap_yi") is not None:
                v = q["mcap_yi"]
                # mcap_yi 单位亿，与现有 "2267B" 同量级（亿≈B），取整
                if isinstance(v, (int, float)) and v > 0:
                    new_mc = f"{int(round(v))}B"
                    changed = True
        # 仍空的标"待实时"
        if not new_pe:
            new_pe = "待实时"
            changed = True
        if not new_pb:
            new_pb = "待实时"
            changed = True
        if not new_mc:
            new_mc = "待实时"
            changed = True

    # code/name 兜底（理论上不会空）
    if not fm.get("code", ""):
        new_code = code
        changed = True
    else:
        new_code = fm.get("code")
    if not name:
        new_name = "待核实"
        changed = True
    else:
        new_name = name

    if not changed:
        return {"type": "stocks_fm", "code": code, "status": "skip", "reason": "无空值"}

    # 重写 frontmatter（按原字段顺序，保留原结构）
    new_fm_lines = []
    for line in fm_text.splitlines():
        if line.startswith("code:"):
            new_fm_lines.append(f"code: {new_code}")
        elif line.startswith("name:"):
            new_fm_lines.append(f"name: {new_name}")
        elif line.startswith("industry:"):
            new_fm_lines.append(f"industry: {new_industry}")
        elif line.startswith("pe_ttm:"):
            new_fm_lines.append(f"pe_ttm: {new_pe}")
        elif line.startswith("pb:"):
            new_fm_lines.append(f"pb: {new_pb}")
        elif line.startswith("market_cap:"):
            new_fm_lines.append(f"market_cap: {new_mc}")
        else:
            new_fm_lines.append(line)
    new_fm = "\n".join(new_fm_lines)
    new_text = m.group(1) + new_fm + m.group(3) + text[m.end():]
    try:
        f.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return {"type": "stocks_fm", "code": code, "status": "error", "reason": f"写文件失败: {e}"}

    return {"type": "stocks_fm", "code": code, "status": "ok", "name": new_name,
            "industry": new_industry, "pe_ttm": new_pe, "pb": new_pb, "market_cap": new_mc}


def stocks_needing_fm_fix() -> list[Path]:
    """找出 frontmatter 有空值的股票（code/name/industry/pe_ttm/pb/market_cap 任一空）。"""
    files = sorted([f for f in DIRS["stocks"].glob("*.md") if f.stem != "index"])
    out = []
    for f in files:
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = parse_frontmatter(t)
        if not fm.get("code", "") or not fm.get("name", "") \
           or not fm.get("industry", "") or not fm.get("pe_ttm", "") \
           or not fm.get("pb", "") or not fm.get("market_cap", ""):
            out.append(f)
    return out


# ════════════════════════════════════════════════════════════════════════════
# 1. stocks/ 行业地位 / 核心竞争力 / 风险提示（任务 2）
# ════════════════════════════════════════════════════════════════════════════
STOCK_BIZ_HEADER = "## 📊 核心业务"


def stock_has_subsections(text: str) -> bool:
    """检查核心业务段是否已含三子段（幂等）。"""
    span = find_section(text, STOCK_BIZ_HEADER)
    if not span:
        return False
    section = text[span[0]:span[1]]
    return ("### 行业地位" in section
            and "### 核心竞争力" in section
            and "### 风险提示" in section)


def stock_rank_top50() -> list[Path]:
    """前 50 大盘股（PE 有值），按市值降序。"""
    files = sorted([f for f in DIRS["stocks"].glob("*.md") if f.stem != "index"])
    ranked = []
    for f in files:
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = parse_frontmatter(t)
        pe = fm.get("pe_ttm", "")
        mc = fm.get("market_cap", "")
        if not pe:
            continue
        # market_cap 解析为数值用于排序（"5927B" → 5927, "572.37亿" → 572.37）
        mc_num = 0.0
        m = re.match(r"([\d.]+)", mc)
        if m:
            mc_num = float(m.group(1))
            if "亿" in mc:
                mc_num *= 0.1  # 亿 → 折算成 B 量级（粗略）
        ranked.append((mc_num, f))
    ranked.sort(key=lambda x: -x[0])
    return [f for _, f in ranked[:50]]


def stock_rank_all() -> list[Path]:
    """全量剩余 stocks（无 ### 行业地位 段的），按文件名顺序。任务 2 用。"""
    files = sorted([f for f in DIRS["stocks"].glob("*.md") if f.stem != "index"])
    out = []
    for f in files:
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if not stock_has_subsections(t):
            out.append(f)
    return out


STOCK_PROMPT = """请为以下 A 股股票生成三段简短描述。

股票代码：{code}
股票名称：{name}
所属行业：{industry}
概念标签：{concept}
PE(TTM)：{pe_ttm}
PB：{pb}
市值：{market_cap}

要求（共 3 段，每段 2-3 句，客观描述不臆造具体财务数据，不构成投资建议）：

【行业地位】在所属行业中的排名/市占率/竞争格局（2 句）
【核心竞争力】护城河/壁垒（2-3 点，用 1. 2. 3. 列举）
【风险提示】主要风险因素（2-3 点，用 1. 2. 3. 列举）

格式：严格按下面三段输出，每段以【】标签开头，不要其他引导语：

【行业地位】...
【核心竞争力】
1. ...
2. ...
3. ...
【风险提示】
1. ...
2. ...
3. ...

直接输出正文，不要思考过程。"""


def stock_parse_llm(text: str) -> dict:
    """解析 LLM 三段输出为 dict。"""
    out = {"行业地位": "", "核心竞争力": "", "风险提示": ""}
    cur = None
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"【(行业地位|核心竞争力|风险提示)】(.*)", line)
        if m:
            if cur:
                out[cur] = "\n".join(b for b in buf if b.strip()).strip()
            cur = m.group(1)
            rest = m.group(2).strip()
            buf = [rest] if rest else []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(b for b in buf if b.strip()).strip()
    return out


def stock_process(f: Path, session, base, key, model) -> dict:
    code = f.stem
    try:
        text = f.read_text(encoding="utf-8")
    except Exception as e:
        return {"type": "stocks", "code": code, "status": "error", "reason": f"读文件失败: {e}"}

    if stock_has_subsections(text):
        return {"type": "stocks", "code": code, "status": "skip", "reason": "已含子段"}

    span = find_section(text, STOCK_BIZ_HEADER)
    if not span:
        return {"type": "stocks", "code": code, "status": "skip", "reason": "无核心业务段"}

    fm = parse_frontmatter(text)
    name = fm.get("name", code)
    industry = fm.get("industry", "待核实")
    concept = fm.get("concept", "")
    pe_ttm = fm.get("pe_ttm", "")
    pb = fm.get("pb", "")
    market_cap = fm.get("market_cap", "")

    prompt = STOCK_PROMPT.format(
        code=code, name=name, industry=industry,
        concept=concept or "（无）", pe_ttm=pe_ttm, pb=pb, market_cap=market_cap,
    )
    llm_text = call_llm(session, base, key, model, prompt)
    if not llm_text:
        return {"type": "stocks", "code": code, "status": "failed",
                "name": name, "reason": "LLM 返回空"}

    parsed = stock_parse_llm(llm_text)
    if not parsed["行业地位"] and not parsed["核心竞争力"] and not parsed["风险提示"]:
        return {"type": "stocks", "code": code, "status": "failed",
                "name": name, "reason": "LLM 输出解析失败"}

    # 在核心业务段末尾追加子段（段末通常是"- 所属指数"行或空行）
    start, end = span
    section = text[start:end]
    # 子段文本
    subs = []
    for title, key_name in [("行业地位", "行业地位"), ("核心竞争力", "核心竞争力"), ("风险提示", "风险提示")]:
        body = parsed[key_name]
        if not body:
            continue
        subs.append(f"\n### {title}\n\n{ANNOTATION}\n{body}\n")
    sub_block = "".join(subs)

    # 找到段内最后一个非空内容位置，在其后追加
    # 策略：在段末尾的连续空行前插入
    section_rstripped = section.rstrip()
    trailing_ws = section[len(section_rstripped):]
    new_section = section_rstripped + "\n" + sub_block + trailing_ws
    # 如果段末没有换行会粘连，补一个
    if not new_section.startswith(section_rstripped):
        pass  # 不会发生
    new_text = text[:start] + new_section + text[end:]
    try:
        f.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return {"type": "stocks", "code": code, "status": "error", "reason": f"写文件失败: {e}"}

    return {"type": "stocks", "code": code, "status": "ok", "name": name,
            "industry": industry, "subsections": [k for k, v in parsed.items() if v]}


# ════════════════════════════════════════════════════════════════════════════
# 2. analysts/ 覆盖领域 + 风格特点
# ════════════════════════════════════════════════════════════════════════════
ANALYST_COV_HEADER = "## 📋 覆盖领域"


def analyst_has_llm(text: str) -> bool:
    span = find_section(text, ANALYST_COV_HEADER)
    if not span:
        return False
    return ANNOTATION in text[span[0]:span[1]]


def analyst_rank_top50() -> list[Path]:
    files = sorted([f for f in DIRS["analysts"].glob("*.md") if f.stem != "index"])

    def cc(f):
        t = f.read_text(encoding="utf-8")
        m = re.search(r"^coverage_count:\s*(\d+)", t, re.M)
        return int(m.group(1)) if m else 0

    ranked = sorted(files, key=lambda f: (-cc(f), f.name))
    return ranked[:50]


def analyst_rank_all() -> list[Path]:
    """全量剩余 analysts（覆盖领域段无 LLM 注释的），按 coverage_count 降序。任务 3 用。"""
    files = sorted([f for f in DIRS["analysts"].glob("*.md") if f.stem != "index"])

    def cc(f):
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:
            return 0
        m = re.search(r"^coverage_count:\s*(\d+)", t, re.M)
        return int(m.group(1)) if m else 0

    out = []
    for f in files:
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if not analyst_has_llm(t):
            out.append(f)
    out.sort(key=lambda f: (-cc(f), f.name))
    return out


ANALYST_PROMPT = """请为以下证券分析师生成简短描述。

姓名：{name}
所属机构：{org}
覆盖股票数：{coverage_count}
覆盖股票代码：{coverage_stocks}
覆盖股票行业：{industries}

要求（2 段，客观描述）：

【覆盖领域】从覆盖的股票行业推断其专注领域（1-2 句）
【风格特点】从覆盖股票数和机构风格推断评级风格（保守/积极/精准/均衡，1 句）

格式：严格按下面两段输出，每段以【】标签开头，不要其他引导语：

【覆盖领域】...
【风格特点】...

直接输出正文，不要思考过程。"""


def analyst_process(f: Path, session, base, key, model) -> dict:
    name_key = f.stem
    try:
        text = f.read_text(encoding="utf-8")
    except Exception as e:
        return {"type": "analysts", "code": name_key, "status": "error", "reason": f"读文件失败: {e}"}

    if analyst_has_llm(text):
        return {"type": "analysts", "code": name_key, "status": "skip", "reason": "已含 LLM 段"}

    fm = parse_frontmatter(text)
    name = fm.get("name", name_key)
    org = fm.get("org", "未知")
    cc = fm.get("coverage_count", "0")
    stocks_raw = fm.get("coverage_stocks", "")

    # 把 coverage_stocks 里的代码转成行业
    stocks = re.findall(r"\d{6}", stocks_raw)
    industries = set()
    for code in stocks:
        sf = DIRS["stocks"] / f"{code}.md"
        if sf.exists():
            try:
                st = sf.read_text(encoding="utf-8")
                sfm = parse_frontmatter(st)
                ind = sfm.get("industry", "")
                if ind:
                    industries.add(ind)
            except Exception:
                pass

    prompt = ANALYST_PROMPT.format(
        name=name, org=org, coverage_count=cc,
        coverage_stocks=stocks_raw or "（无）",
        industries="、".join(sorted(industries)) if industries else "（待推断）",
    )
    llm_text = call_llm(session, base, key, model, prompt)
    if not llm_text:
        return {"type": "analysts", "code": name_key, "status": "failed",
                "name": name, "reason": "LLM 返回空"}

    # 解析两段
    cov = ""
    style = ""
    cur = None
    buf: list[str] = []
    for line in llm_text.splitlines():
        m = re.match(r"【(覆盖领域|风格特点)】(.*)", line)
        if m:
            if cur:
                if cur == "覆盖领域":
                    cov = "\n".join(b for b in buf if b.strip()).strip()
                else:
                    style = "\n".join(b for b in buf if b.strip()).strip()
            cur = m.group(1)
            rest = m.group(2).strip()
            buf = [rest] if rest else []
        elif cur:
            buf.append(line)
    if cur == "覆盖领域":
        cov = "\n".join(b for b in buf if b.strip()).strip()
    elif cur == "风格特点":
        style = "\n".join(b for b in buf if b.strip()).strip()

    if not cov and not style:
        return {"type": "analysts", "code": name_key, "status": "failed",
                "name": name, "reason": "LLM 输出解析失败"}

    span = find_section(text, ANALYST_COV_HEADER)
    if not span:
        return {"type": "analysts", "code": name_key, "status": "skip", "reason": "无覆盖领域段"}

    new_body = f"{ANNOTATION}\n"
    if cov:
        new_body += f"**覆盖领域**：{cov}\n"
    if style:
        new_body += f"**风格特点**：{style}\n"
    new_section = f"{ANALYST_COV_HEADER}\n\n{new_body}\n"
    new_text = text[:span[0]] + new_section + text[span[1]:]
    try:
        f.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return {"type": "analysts", "code": name_key, "status": "error", "reason": f"写文件失败: {e}"}

    return {"type": "analysts", "code": name_key, "status": "ok",
            "name": name, "org": org, "cov": cov[:60], "style": style[:60]}


# ════════════════════════════════════════════════════════════════════════════
# 3. reports/ 报告摘要 + 核心结论
# ════════════════════════════════════════════════════════════════════════════
REPORT_VIEW_HEADER = "## 💡 核心观点"


def report_has_llm(text: str) -> bool:
    span = find_section(text, REPORT_VIEW_HEADER)
    if not span:
        return False
    return ANNOTATION in text[span[0]:span[1]]


def report_rank_top50() -> list[Path]:
    files = sorted([f for f in DIRS["reports"].glob("*.md") if f.stem != "index"])

    def pd(f):
        t = f.read_text(encoding="utf-8")
        m = re.search(r"^publish_date:\s*(\S+)", t, re.M)
        return m.group(1) if m else ""

    ranked = sorted(files, key=lambda f: (pd(f), f.name), reverse=True)
    return ranked[:50]


def report_rank_all() -> list[Path]:
    """全量剩余 reports（核心观点段无 LLM 注释的），按 publish_date 降序。任务 4 用。"""
    files = sorted([f for f in DIRS["reports"].glob("*.md") if f.stem != "index"])

    def pd(f):
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:
            return ""
        m = re.search(r"^publish_date:\s*(\S+)", t, re.M)
        return m.group(1) if m else ""

    out = []
    for f in files:
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if not report_has_llm(t):
            out.append(f)
    out.sort(key=lambda f: (pd(f), f.name), reverse=True)
    return out


REPORT_PROMPT = """请为以下证券研究报告生成简短摘要与核心结论。

标题：{title}
机构：{org}
评级：{report_type}
目标价：{target_price}
EPS 预测：{eps_forecast}
分析师：{researcher}
标的股票代码：{code}

要求（2 段，客观描述，从标题推断核心观点，不臆造具体数据）：

【报告摘要】从标题推断核心观点（1-2 句）
【核心结论】评级 + 目标价（如有）+ 关键逻辑（2-3 句）

格式：严格按下面两段输出，每段以【】标签开头，不要其他引导语：

【报告摘要】...
【核心结论】...

直接输出正文，不要思考过程。"""


def report_process(f: Path, session, base, key, model) -> dict:
    name_key = f.stem
    try:
        text = f.read_text(encoding="utf-8")
    except Exception as e:
        return {"type": "reports", "code": name_key, "status": "error", "reason": f"读文件失败: {e}"}

    if report_has_llm(text):
        return {"type": "reports", "code": name_key, "status": "skip", "reason": "已含 LLM 段"}

    fm = parse_frontmatter(text)
    title = fm.get("title", name_key)
    org = fm.get("org", "未知")
    report_type = fm.get("report_type", "未知")
    target_price = fm.get("target_price", "未提供")
    eps_forecast = fm.get("eps_forecast", "未提供")
    researcher = fm.get("researcher", "")
    code = fm.get("code", "")

    prompt = REPORT_PROMPT.format(
        title=title, org=org, report_type=report_type,
        target_price=target_price, eps_forecast=eps_forecast,
        researcher=researcher or "（未知）", code=code or "（未知）",
    )
    llm_text = call_llm(session, base, key, model, prompt)
    if not llm_text:
        return {"type": "reports", "code": name_key, "status": "failed",
                "title": title[:40], "reason": "LLM 返回空"}

    summary = ""
    conclusion = ""
    cur = None
    buf: list[str] = []
    for line in llm_text.splitlines():
        m = re.match(r"【(报告摘要|核心结论)】(.*)", line)
        if m:
            if cur:
                if cur == "报告摘要":
                    summary = "\n".join(b for b in buf if b.strip()).strip()
                else:
                    conclusion = "\n".join(b for b in buf if b.strip()).strip()
            cur = m.group(1)
            rest = m.group(2).strip()
            buf = [rest] if rest else []
        elif cur:
            buf.append(line)
    if cur == "报告摘要":
        summary = "\n".join(b for b in buf if b.strip()).strip()
    elif cur == "核心结论":
        conclusion = "\n".join(b for b in buf if b.strip()).strip()

    if not summary and not conclusion:
        return {"type": "reports", "code": name_key, "status": "failed",
                "title": title[:40], "reason": "LLM 输出解析失败"}

    span = find_section(text, REPORT_VIEW_HEADER)
    if not span:
        return {"type": "reports", "code": name_key, "status": "skip", "reason": "无核心观点段"}

    new_body = f"{ANNOTATION}\n"
    if summary:
        new_body += f"**报告摘要**：{summary}\n"
    if conclusion:
        new_body += f"**核心结论**：{conclusion}\n"
    new_section = f"{REPORT_VIEW_HEADER}\n\n{new_body}\n"
    new_text = text[:span[0]] + new_section + text[span[1]:]
    try:
        f.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return {"type": "reports", "code": name_key, "status": "error", "reason": f"写文件失败: {e}"}

    return {"type": "reports", "code": name_key, "status": "ok",
            "title": title[:40], "org": org,
            "summary": summary[:60], "conclusion": conclusion[:60]}


# ════════════════════════════════════════════════════════════════════════════
# 4. concepts/ 题材逻辑 + 催化因素
# ════════════════════════════════════════════════════════════════════════════
CONCEPT_LOGIC_HEADER = "## 📖 题材逻辑"


def concept_has_llm(text: str) -> bool:
    return CONCEPT_LOGIC_HEADER in text and ANNOTATION in text


def concept_rank_top30() -> list[Path]:
    files = sorted([f for f in DIRS["concepts"].glob("*.md") if f.stem != "index"])
    # 统计每个概念被多少股票 frontmatter 提及
    counts: dict[str, int] = {}
    for sf in DIRS["stocks"].glob("*.md"):
        if sf.stem == "index":
            continue
        try:
            t = sf.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"^concept:\s*(.+)", t, re.M)
        if not m:
            continue
        for c in [x.strip() for x in m.group(1).split(",") if x.strip()]:
            counts[c] = counts.get(c, 0) + 1
    ranked = sorted(files, key=lambda f: (-counts.get(f.stem, 0), f.name))
    return ranked[:30]


def concept_rank_all() -> list[Path]:
    """全量剩余 concepts（无 ## 📖 题材逻辑 段或段内无 LLM 注释的），按提及数降序。任务 5 用。"""
    files = sorted([f for f in DIRS["concepts"].glob("*.md") if f.stem != "index"])
    # 统计每个概念被多少股票 frontmatter 提及
    counts: dict[str, int] = {}
    for sf in DIRS["stocks"].glob("*.md"):
        if sf.stem == "index":
            continue
        try:
            t = sf.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"^concept:\s*(.+)", t, re.M)
        if not m:
            continue
        for c in [x.strip() for x in m.group(1).split(",") if x.strip()]:
            counts[c] = counts.get(c, 0) + 1
    out = [f for f in files if not concept_has_llm(f.read_text(encoding="utf-8"))]
    out.sort(key=lambda f: (-counts.get(f.stem, 0), f.name))
    return out


CONCEPT_PROMPT = """请为以下 A 股市场热门概念生成简短描述。

概念名称：{name}
成分股数量：{stock_count}

要求（2 段，客观描述，不臆造具体数据，不构成投资建议）：

【题材逻辑】为什么这个概念受市场关注（2-3 句）
【催化因素】什么事件会催化这个概念（1-2 句）

格式：严格按下面两段输出，每段以【】标签开头，不要其他引导语：

【题材逻辑】...
【催化因素】...

直接输出正文，不要思考过程。"""


def concept_process(f: Path, session, base, key, model) -> dict:
    name_key = f.stem
    try:
        text = f.read_text(encoding="utf-8")
    except Exception as e:
        return {"type": "concepts", "code": name_key, "status": "error", "reason": f"读文件失败: {e}"}

    if concept_has_llm(text):
        return {"type": "concepts", "code": name_key, "status": "skip", "reason": "已含 LLM 段"}

    fm = parse_frontmatter(text)
    name = fm.get("name", name_key)
    # 统计成分股数
    stock_count = 0
    for sf in DIRS["stocks"].glob("*.md"):
        if sf.stem == "index":
            continue
        try:
            t = sf.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"^concept:\s*(.+)", t, re.M)
        if not m:
            continue
        if name in [x.strip() for x in m.group(1).split(",")]:
            stock_count += 1

    prompt = CONCEPT_PROMPT.format(name=name, stock_count=stock_count)
    llm_text = call_llm(session, base, key, model, prompt)
    if not llm_text:
        return {"type": "concepts", "code": name_key, "status": "failed",
                "name": name, "reason": "LLM 返回空"}

    logic = ""
    catalyst = ""
    cur = None
    buf: list[str] = []
    for line in llm_text.splitlines():
        m = re.match(r"【(题材逻辑|催化因素)】(.*)", line)
        if m:
            if cur:
                if cur == "题材逻辑":
                    logic = "\n".join(b for b in buf if b.strip()).strip()
                else:
                    catalyst = "\n".join(b for b in buf if b.strip()).strip()
            cur = m.group(1)
            rest = m.group(2).strip()
            buf = [rest] if rest else []
        elif cur:
            buf.append(line)
    if cur == "题材逻辑":
        logic = "\n".join(b for b in buf if b.strip()).strip()
    elif cur == "催化因素":
        catalyst = "\n".join(b for b in buf if b.strip()).strip()

    if not logic and not catalyst:
        return {"type": "concepts", "code": name_key, "status": "failed",
                "name": name, "reason": "LLM 输出解析失败"}

    new_body = f"{ANNOTATION}\n"
    if logic:
        new_body += f"**题材逻辑**：{logic}\n"
    if catalyst:
        new_body += f"**催化因素**：{catalyst}\n"
    new_section = f"{CONCEPT_LOGIC_HEADER}\n\n{new_body}\n"

    # 插入位置：在 `## 🏢 成分股` 段之前；若无则追加到末尾
    comp_idx = text.find("## 🏢 成分股")
    if comp_idx >= 0:
        new_text = text[:comp_idx] + new_section + text[comp_idx:]
    else:
        new_text = text.rstrip() + "\n\n" + new_section
    try:
        f.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return {"type": "concepts", "code": name_key, "status": "error", "reason": f"写文件失败: {e}"}

    return {"type": "concepts", "code": name_key, "status": "ok",
            "name": name, "logic": logic[:60], "catalyst": catalyst[:60]}


# ── 调度 ────────────────────────────────────────────────────────────────────
TASKS_TOPN = {
    "stocks": (stock_rank_top50, stock_process),
    "analysts": (analyst_rank_top50, analyst_process),
    "reports": (report_rank_top50, report_process),
    "concepts": (concept_rank_top30, concept_process),
}
TASKS_ALL = {
    "stocks": (stock_rank_all, stock_process),
    "analysts": (analyst_rank_all, analyst_process),
    "reports": (report_rank_all, report_process),
    "concepts": (concept_rank_all, concept_process),
}


def run_one_type(type_name: str, files: list[Path], session, base, key, model,
                  concurrency: int, limit: int, dry_run: bool,
                  results: list[dict], batch_size: int = 50,
                  batch_sleep: float = 5.0) -> tuple[int, int]:
    proc_fn = TASKS_TOPN[type_name][1]
    pool_files = files[:limit] if limit > 0 else files
    ok = fail = 0
    if dry_run:
        for f in pool_files:
            results.append({"type": type_name, "code": f.stem, "status": "dry-run"})
        return 0, 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(proc_fn, f, session, base, key, model): f for f in pool_files}
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"type": type_name, "code": f.stem, "status": "error",
                     "reason": f"异常: {e}"}
            results.append(r)
            if r["status"] == "ok":
                ok += 1
            elif r["status"] == "failed":
                fail += 1
            elapsed = time.time() - t0
            icon = {"ok": "✓", "failed": "✗", "error": "!", "skip": "-"}.get(r["status"], "?")
            nm = r.get("name", r.get("title", ""))[:12]
            print(f"  [{type_name[:5]:>5} {i:2d}/{len(pool_files)}] {icon} {r['code'][:16]:16s} {nm:<12}  "
                  f"ok={ok} fail={fail}  {elapsed:.0f}s")
            # 每批 batch_size 个完成，sleep batch_sleep 秒（限流）
            if batch_size > 0 and i % batch_size == 0 and i < len(pool_files):
                print(f"  [限流] 已完成 {i}/{len(pool_files)}，sleep {batch_sleep}s ...")
                time.sleep(batch_sleep)
    return ok, fail


def run_frontmatter_fix(files: list[Path], session, base, key, model,
                        concurrency: int, limit: int, dry_run: bool,
                        results: list[dict]) -> tuple[int, int]:
    """任务 1 专用调度：tencent_quote 批量预取 + 并发修 frontmatter。"""
    pool_files = files[:limit] if limit > 0 else files
    ok = fail = 0
    if dry_run:
        for f in pool_files:
            results.append({"type": "stocks_fm", "code": f.stem, "status": "dry-run"})
        return 0, 0
    if not pool_files:
        return 0, 0
    t0 = time.time()
    # 先批量拉 tencent_quote（pe_ttm/pb/mcap_yi）——按代码顺序去重，分批 50
    codes = [f.stem for f in pool_files]
    print(f"  [frontmatter] 预取 tencent_quote（{len(codes)} 只）...")
    quote_cache: dict[str, dict] = {}
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        try:
            r = _stock_load_tencent_quote(batch)
            if isinstance(r, dict):
                quote_cache.update(r)
        except Exception:
            pass
        if i + 50 < len(codes):
            time.sleep(1)
    print(f"  [frontmatter] 预取完成，cache 命中 {len(quote_cache)} 只")

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(stock_fix_frontmatter, f, session, base, key, model, quote_cache): f
                   for f in pool_files}
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"type": "stocks_fm", "code": f.stem, "status": "error",
                     "reason": f"异常: {e}"}
            results.append(r)
            if r["status"] == "ok":
                ok += 1
            elif r["status"] == "failed":
                fail += 1
            elapsed = time.time() - t0
            icon = {"ok": "✓", "failed": "✗", "error": "!", "skip": "-"}.get(r["status"], "?")
            nm = r.get("name", "")[:12]
            print(f"  [ fm   {i:2d}/{len(pool_files)}] {icon} {r['code'][:16]:16s} {nm:<12}  "
                  f"ok={ok} fail={fail}  {elapsed:.0f}s")
    return ok, fail


def write_report(results: list[dict], stats: dict, elapsed_total: float, concurrency: int, limit: int):
    DOCS.mkdir(parents=True, exist_ok=True)
    report_path = DOCS / "llm-content-enrichment-report.md"

    total_ok = sum(s["ok"] for s in stats.values())
    total_fail = sum(s["fail"] for s in stats.values())
    total_skip = sum(s["skip"] for s in stats.values())

    lines = [
        "# 图谱实体正文 LLM 批量充实报告",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 耗时：{elapsed_total:.0f} 秒（{elapsed_total/60:.1f} 分钟）",
        f"> 并发：{concurrency} 线程",
        f"> LLM：deepseek-v4-pro（max_tokens=4096）",
        "",
        "## 总览",
        "",
        "| 实体类型 | 待处理 | 成功 | 失败 | 跳过(已填充) |",
        "|---|---|---|---|---|",
    ]
    for t, s in stats.items():
        lines.append(f"| {t} | {s['total']} | {s['ok']} | {s['fail']} | {s['skip']} |")
    lines.append(f"| **合计** | **{sum(s['total'] for s in stats.values())}** | **{total_ok}** | **{total_fail}** | **{total_skip}** |")
    lines.append("")

    # 各类详情
    for type_name in ["stocks", "analysts", "reports", "concepts"]:
        type_results = [r for r in results if r.get("type") == type_name]
        oks = [r for r in type_results if r["status"] == "ok"]
        errs = [r for r in type_results if r["status"] in ("failed", "error")]
        lines.append(f"## {type_name}")
        lines.append("")
        lines.append(f"成功 {len(oks)} 条，失败 {len(errs)} 条。")
        lines.append("")
        if type_name == "stocks":
            lines.append("### 成功示例（前 5 条）")
            lines.append("")
            for r in oks[:5]:
                lines.append(f"#### {r['code']} {r.get('name','')}（{r.get('industry','')}）")
                lines.append(f"追加子段：{', '.join(r.get('subsections', []))}")
                lines.append("")
        elif type_name == "analysts":
            lines.append("### 成功示例（前 5 条）")
            lines.append("")
            for r in oks[:5]:
                lines.append(f"#### {r['code']}")
                lines.append(f"- 覆盖领域：{r.get('cov','')}")
                lines.append(f"- 风格特点：{r.get('style','')}")
                lines.append("")
        elif type_name == "reports":
            lines.append("### 成功示例（前 5 条）")
            lines.append("")
            for r in oks[:5]:
                lines.append(f"#### {r['code']}")
                lines.append(f"- 报告摘要：{r.get('summary','')}")
                lines.append(f"- 核心结论：{r.get('conclusion','')}")
                lines.append("")
        elif type_name == "concepts":
            lines.append("### 成功示例（前 5 条）")
            lines.append("")
            for r in oks[:5]:
                lines.append(f"#### {r['code']}")
                lines.append(f"- 题材逻辑：{r.get('logic','')}")
                lines.append(f"- 催化因素：{r.get('catalyst','')}")
                lines.append("")
        if errs:
            lines.append("### 失败/异常列表")
            lines.append("")
            lines.append("| 标识 | 状态 | 原因 |")
            lines.append("|---|---|---|")
            for r in errs:
                lines.append(f"| {r['code']} | {r['status']} | {r.get('reason','')} |")
            lines.append("")

    lines.extend([
        "## 说明",
        "",
        "- 所有充实段落均带 `<!-- LLM 生成，待人工校验 -->` 注释，需人工抽查校验。",
        "- 失败的段落未写文件，重跑本脚本会自动跳过已填充、只处理失败项（幂等）。",
        "- LLM 模型：`deepseek-v4-pro`（推理模型，reasoning 占 ~2000 tokens，max_tokens 设 4096）。",
        "- 不改 frontmatter，不改其他既有段（财务/估值/研报 dataview 等）。",
        "- 合规：只生成客观描述，不臆造具体财务数据，不构成投资建议。",
        "",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[报告] 已生成 {report_path}")


def main():
    ap = argparse.ArgumentParser(description="LLM 批量充实 4 类图谱实体正文")
    ap.add_argument("-n", "--concurrency", type=int, default=8, help="并发线程数（默认 8）")
    ap.add_argument("--only", default="stocks,analysts,reports,concepts",
                    help="只处理指定类型（逗号分隔，默认全部）")
    ap.add_argument("--limit", type=int, default=0, help="每类仅处理 N 个（测试用，0=全部）")
    ap.add_argument("--dry-run", action="store_true", help="只扫描不调 LLM 不写文件")
    args = ap.parse_args()

    base, key, model = load_llm_config()
    print(f"[配置] base={base}  model={model}  并发={args.concurrency}  limit={args.limit or '全量'}")

    types = [t.strip() for t in args.only.split(",") if t.strip()]
    print(f"[范围] 处理类型：{', '.join(types)}")

    session = make_session()
    results: list[dict] = []
    stats: dict[str, dict] = {}
    t0 = time.time()

    # 用 TASKS_ALL：处理全量剩余实体（幂等，已含 LLM 注释的自动跳过）
    for type_name in types:
        if type_name not in TASKS_ALL:
            print(f"[警告] 未知类型 {type_name}，跳过")
            continue
        rank_fn, _ = TASKS_ALL[type_name]
        files = rank_fn()
        print(f"\n=== {type_name}（{len(files)} 个候选）===")
        ok, fail = run_one_type(type_name, files, session, base, key, model,
                                 args.concurrency, args.limit, args.dry_run, results)
        skip = sum(1 for r in results if r.get("type") == type_name and r["status"] == "skip")
        stats[type_name] = {"total": len(files), "ok": ok, "fail": fail, "skip": skip}

    elapsed_total = time.time() - t0
    print(f"\n[完成] 总耗时 {elapsed_total:.0f}s")
    for t, s in stats.items():
        print(f"  {t}: total={s['total']} ok={s['ok']} fail={s['fail']} skip={s['skip']}")

    if not args.dry_run:
        write_report(results, stats, elapsed_total, args.concurrency, args.limit)


if __name__ == "__main__":
    main()
