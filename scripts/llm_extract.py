#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 实体抽取 pipeline——从研报/公告/新闻文本抽取实体和关系，灌入 inbox/。

抽取 Prompt 设计见本文件 EXTRACT_PROMPT（规则抽取 + LLM 抽取双模）。

两种模式：
  1. 规则抽取（默认）：正则匹配 6 位代码 / 行业 / 概念 / 财务指标，不调 LLM。
  2. LLM 抽取（--use-llm）：用 EXTRACT_PROMPT 调 Vibe-Research 的 chat.run_chat，
     解析 JSON 输出；LLM 不可用时自动降级用规则抽取。

用法：
  python3 scripts/llm_extract.py --text "贵州茅台(600519)属于白酒行业，2024年营收1709亿，分析师张三给予买入评级。"
  python3 scripts/llm_extract.py --file "report.txt"
  python3 scripts/llm_extract.py --code 600519            # 从 eastmoney_reports 拉研报抽取
  python3 scripts/llm_extract.py --code 600519 --use-llm  # LLM 模式

合规：只抽取文本中出现的客观数据，不臆造、不预置标的、不排名、不建议。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ── 路径 ────────────────────────────────────────────────────────────────────
VAULT = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing")
INBOX = VAULT / "inbox"

# ── astock 导入（方式 2：直接 import，对齐 scripts/sync_real_data.py）──────
BACKEND_DIR = "/Users/lizhiwei/project/code/stock/Vibe-Research/backend"
sys.path.insert(0, BACKEND_DIR)

# 抽取 prompt（对齐 docs/knowledge-graph-llm-pipeline.md 第 2 节「抽取 Prompt 设计」）
# 注意：prompt 含 JSON 示例，所有字面 {} 必须写成 {{ }} 才能安全 .format()；
#       唯一替换字段是 {text}。
EXTRACT_PROMPT = """你是一位投研知识图谱工程师。请从以下文本中抽取实体和关系。

## 约束
- 实体类型限定：stock / industry / concept / analyst / metric / event / report
- 关系类型限定：belongs_to / tagged / covered_by / has_metric / authored_by / affects / matches
- 股票优先用 6 位代码，不确定标 confidence: low
- 不臆造：文本没有的不要编
- 所有抽取结果标 source

## 输出格式（严格 JSON，不要 markdown 代码块）
{{
  "entities": [
    {{"type": "stock", "code": "600519", "name": "贵州茅台", "confidence": "high", "source": "report:xxx"}}
  ],
  "relations": [
    {{"from": "600519", "relation": "belongs_to", "to": "industry/白酒", "confidence": "high"}}
  ]
}}

## 输入文本
{text}
"""


# ── 模式 1：规则抽取 ────────────────────────────────────────────────────────
# 常见前缀动词/介词/连词——行业/概念名前的「属于/隶属/归属/…」要剔除，
# 否则贪婪正则会把「属于白酒行业」抓成「属于白酒」行业名。
_PREFIX_CHARS = set("属于在到从由和与及把将被让使靠属为是")
_PREFIX_WORDS = ("属于", "隶属", "归属", "所属", "叫做", "称为", "称作", "属于")


def _strip_prefix(s: str) -> str:
    """剔除行业/概念名前的前缀动词/介词（「属于白酒」→「白酒」）。"""
    while len(s) > 2 and s[0] in _PREFIX_CHARS:
        s = s[1:]
    for pfx in _PREFIX_WORDS:
        if s.startswith(pfx) and len(s) > len(pfx):
            s = s[len(pfx):]
    return s


def extract_by_rules(text: str) -> dict:
    """规则抽取——正则匹配，不调 LLM。

    能识别：
    - 6 位股票代码 → stock
    - xx 行业 / xx 板块 → industry（剔除前缀动词/介词）
    - xx 概念 / xx 题材 → concept（同上）
    - 分析师 xxx / 研究员 xxx → analyst（在「给/评/认为/…」处停）
    - 营收 xx 亿 / 净利 xx 亿 / ROE xx% → metric
    """
    entities: list[dict] = []
    relations: list[dict] = []
    seen_keys: set[str] = set()  # 去重

    def _add(entity: dict) -> None:
        key = (entity.get("type", ""), entity.get("code", "") or entity.get("name", ""))
        if key in seen_keys:
            return
        seen_keys.add(key)
        entities.append(entity)

    # 6 位股票代码（排除日期 YYYY-MM-DD 里的连续数字：日期有连字符分隔，\b 边界匹配安全）
    codes = re.findall(r"(?<![\d-])(\d{6})(?!\d)", text)
    for code in set(codes):
        _add({
            "type": "stock", "code": code, "name": "",
            "confidence": "high", "source": "regex:code",
        })

    # 行业名（xx行业 / xx板块）——lazy + 剔前缀，防「属于白酒行业」抓成「属于白酒」
    for m in re.finditer(r"([\u4e00-\u9fa5]+?)(行业|板块)", text):
        name = _strip_prefix(m.group(1))
        if len(name) >= 2:
            _add({
                "type": "industry", "name": name,
                "confidence": "medium", "source": "regex:industry",
            })

    # 概念（xx概念 / xx题材）——同上
    for m in re.finditer(r"([\u4e00-\u9fa5]+?)(概念|题材)", text):
        name = _strip_prefix(m.group(1))
        if len(name) >= 2:
            _add({
                "type": "concept", "name": name,
                "confidence": "medium", "source": "regex:concept",
            })

    # 分析师（分析师/研究员 xxx，在「给/评/认为/…」处停，防抓到「张三给予」）
    _analyst_stop = r"(?=给|评|认为|指出|表示|建议|称|说|看|对|，|。|;|；)"
    for m in re.finditer(rf"(分析师|研究员)\s*([\u4e00-\u9fa5]{{2,4}}?){_analyst_stop}", text):
        _add({
            "type": "analyst", "name": m.group(2),
            "confidence": "medium", "source": "regex:analyst",
        })

    # 财务指标：营收xx亿 / 净利xx亿 / ROE xx%
    revenue = re.search(r"营收[约达]?([\d.]+)亿", text)
    if revenue:
        _add({
            "type": "metric", "name": "营收", "value": revenue.group(1) + "亿",
            "confidence": "high", "source": "regex:revenue",
        })
    net_profit = re.search(r"净利[约达]?([\d.]+)亿", text)
    if net_profit:
        _add({
            "type": "metric", "name": "净利", "value": net_profit.group(1) + "亿",
            "confidence": "high", "source": "regex:net_profit",
        })
    roe = re.search(r"ROE[约达\s]*([\d.]+)%", text)
    if roe:
        _add({
            "type": "metric", "name": "ROE", "value": roe.group(1) + "%",
            "confidence": "high", "source": "regex:roe",
        })

    # 建关系：股票 → 行业（confidence: low，因为文本未显式声明归属时是推断）
    for e in entities:
        if e["type"] == "stock" and e.get("code"):
            for ind in entities:
                if ind["type"] == "industry":
                    rel_key = (e["code"], "belongs_to", ind["name"])
                    if rel_key not in seen_keys:
                        seen_keys.add(rel_key)
                        relations.append({
                            "from": e["code"], "relation": "belongs_to",
                            "to": f"industry/{ind['name']}",
                            "confidence": "low", "source": "regex:inferred",
                        })

    return {"entities": entities, "relations": relations}


# ── 模式 2：LLM 抽取 ───────────────────────────────────────────────────────
def _parse_llm_json(content: str) -> dict | None:
    """从 LLM 输出里解析 JSON——容忍 ```json 代码块包装。"""
    if not content:
        return None
    text = content.strip()
    # 剥 markdown 代码块
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # 无代码块则抓第一个 { 到最后一个 }
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "entities" in data:
            return data
    except json.JSONDecodeError:
        pass
    return None


def extract_by_llm(text: str) -> dict:
    """LLM 抽取——调 chat.run_chat，失败降级规则抽取。"""
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(Path(BACKEND_DIR) / ".env")
        import chat  # type: ignore — backend 模块
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 导入 chat 失败（{e}），降级规则抽取", file=sys.stderr)
        return extract_by_rules(text)

    cfg = chat._get_env_llm_config()
    if not (cfg.get("baseURL") and cfg.get("apiKey") and cfg.get("model")):
        print("[WARN] LLM 未配置（VR_LLM_BASE_URL/API_KEY/MODEL），降级规则抽取", file=sys.stderr)
        return extract_by_rules(text)

    prompt = EXTRACT_PROMPT.format(text=text[:8000])  # 截断防超 token
    try:
        result = chat.run_chat(cfg, [{"role": "user", "content": prompt}])
        content = result.get("content", "")
        parsed = _parse_llm_json(content)
        if parsed is None:
            print("[WARN] LLM 输出非合法 JSON，降级规则抽取", file=sys.stderr)
            return extract_by_rules(text)
        # 补 source 字段（LLM 可能漏标）
        for e in parsed.get("entities", []):
            e.setdefault("source", "llm:extract")
            e.setdefault("confidence", "medium")
        for r in parsed.get("relations", []):
            r.setdefault("source", "llm:extract")
            r.setdefault("confidence", "medium")
        return parsed
    except Exception as e:  # noqa: BLE001 — LLM 失败降级
        print(f"[WARN] LLM 调用失败（{e}），降级规则抽取", file=sys.stderr)
        return extract_by_rules(text)


# ── 从研报拉文本 ────────────────────────────────────────────────────────────
def fetch_report_text(code: str, limit: int = 5) -> str:
    """从 eastmoney_reports 拉研报标题/机构/EPS，拼成抽取用文本。"""
    try:
        from data.sources.eastmoney import eastmoney_reports
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] 导入 eastmoney_reports 失败：{e}", file=sys.stderr)
        return ""

    rows = eastmoney_reports(code, max_pages=1)[:limit]
    if not rows:
        print(f"[INFO] 代码 {code} 无研报数据", file=sys.stderr)
        return ""

    parts = [f"股票代码 {code} 近期研报："]
    for r in rows:
        title = r.get("title", "")
        org = r.get("orgSName", "")
        eps = r.get("predictNextYearEps", "")
        pe = r.get("predictNextYearPe", "")
        stock_name = r.get("stockName", "")
        researcher = r.get("researcher", "") or ""
        line = f"- 「{title}」 机构：{org}"
        if stock_name:
            line += f" 标的：{stock_name}({code})"
        # 研究员：拆分逗号分隔的多名，逐名以「研究员 {name}，」前缀呈现，
        # 使规则抽取的 analyst 正则（(分析师|研究员)\s*([\u4e00-\u9fa5]{2,4}?)）
        # 能逐个识别。数据来自 eastmoney_reports 的 researcher 字段，非臆造。
        if researcher:
            names = [n.strip() for n in researcher.replace("、", ",").split(",") if n.strip()]
            for nm in names:
                line += f" 研究员 {nm}，"
        if eps:
            line += f" 预测EPS：{eps}"
        if pe:
            line += f" 预测PE：{pe}"
        parts.append(line)
    return "\n".join(parts)


# ── quality_score 计算 ─────────────────────────────────────────────────────
def _quality_score(confidence: str) -> int:
    """confidence → quality_score（inbox/index.md 质量门）。"""
    return {"high": 80, "medium": 50, "low": 20}.get(confidence, 20)


def _safe_filename(name: str) -> str:
    """文件名安全化——去路径分隔符/特殊字符。"""
    safe = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", str(name))
    return safe.strip("_") or "entity"


# ── 写 inbox 文件 ──────────────────────────────────────────────────────────
def write_inbox_entities(extracted: dict, source_text: str, quiet: bool = False) -> list[Path]:
    """把抽取的实体写入 inbox/，返回写入文件列表。"""
    INBOX.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    today = datetime.now().strftime("%Y-%m-%d")
    written: list[Path] = []

    for i, entity in enumerate(extracted.get("entities", [])):
        entity_type = entity.get("type", "unknown")
        name = entity.get("name") or entity.get("code") or f"entity-{i}"
        confidence = entity.get("confidence", "low")
        source = entity.get("source", "unknown")
        qscore = _quality_score(confidence)
        safe_name = _safe_filename(name)
        filename = f"{timestamp}-{entity_type}-{safe_name}.md"
        filepath = INBOX / filename

        # 防重名（同一秒多个同名实体）
        counter = 1
        while filepath.exists():
            filepath = INBOX / f"{timestamp}-{entity_type}-{safe_name}-{counter}.md"
            counter += 1

        content = f"""---
type: inbox_item
entity_type: {entity_type}
name: {name}
code: {entity.get("code", "")}
confidence: {confidence}
source: {source}
quality_score: {qscore}
approved: false
created: {today}
---

# 待审实体：{name}

> 由 LLM 抽取 pipeline 生成，待人工审核。

## 来源
- {source}

## 抽取的属性
```json
{json.dumps(entity, ensure_ascii=False, indent=2)}
```

## 原文片段
{source_text[:500]}
"""
        filepath.write_text(content, encoding="utf-8")
        if quiet:
            print(filepath)
        else:
            print(f"✅ 写入: {filepath}")
        written.append(filepath)

    return written


# ── CLI ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="从文本抽取实体和关系，灌入 inbox/ 待审区",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="直接传入文本")
    src.add_argument("--file", help="从文件读文本")
    src.add_argument("--code", help="从 eastmoney_reports 拉研报抽取（6 位代码）")
    parser.add_argument("--use-llm", action="store_true", help="用 LLM 模式（默认规则抽取）")
    parser.add_argument("--limit", type=int, default=5, help="--code 模式拉取研报条数（默认 5）")
    parser.add_argument("--quiet", action="store_true", help="只输出写入文件的路径（批量用）")
    args = parser.parse_args()

    # 取文本
    if args.text:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:  # args.code
        if not re.fullmatch(r"\d{6}", args.code):
            print(f"[ERROR] --code 需 6 位数字代码，收到：{args.code}", file=sys.stderr)
            return 2
        text = fetch_report_text(args.code, limit=args.limit)
        if not text:
            return 1

    if not text.strip():
        print("[ERROR] 输入文本为空", file=sys.stderr)
        return 1

    # 抽取
    if args.use_llm:
        if not args.quiet:
            print("[MODE] LLM 抽取（不可用时降级规则）", file=sys.stderr)
        extracted = extract_by_llm(text)
    else:
        if not args.quiet:
            print("[MODE] 规则抽取", file=sys.stderr)
        extracted = extract_by_rules(text)

    # 汇报
    n_ent = len(extracted.get("entities", []))
    n_rel = len(extracted.get("relations", []))
    if not args.quiet:
        print(f"\n[RESULT] 实体 {n_ent} 个，关系 {n_rel} 条", file=sys.stderr)

    # 写 inbox
    written = write_inbox_entities(extracted, text, quiet=args.quiet)
    if not args.quiet:
        print(f"\n[DONE] 写入 inbox 文件 {len(written)} 个", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
