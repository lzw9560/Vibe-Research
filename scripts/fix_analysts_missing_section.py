#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补丁：为缺 `## 📋 覆盖领域` 段的 35 个边缘分析师补建该段并 LLM 填充。

这 35 个 coverage_count=0、coverage_stocks=[]，但"原文片段"含标的/机构信息，
LLM 从原文片段推断覆盖领域 + 风格特点。段插入 `## 来源` 之前（紧跟 info callout 之后），
与有段文件结构一致。段内带 `<!-- LLM 生成，待人工校验 -->` 注释，与 fill_entities_llm.py 口径一致。

幂等：已含 `## 📋 覆盖领域` 段的跳过。

用法：python3 scripts/fix_analysts_missing_section.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings()

REPO = Path("/Users/lizhiwei/project/code/stock/Vibe-Research")
ENV_FILE = REPO / "backend" / ".env"
VAULT = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing")
ANALYSTS_DIR = VAULT / "analysts"

ANNOTATION = "<!-- LLM 生成，待人工校验 -->"
SECTION_HEADER = "## 📋 覆盖领域"
INSERT_BEFORE = "## 来源"  # 无段文件的 callout 之后第一个 ## 段


def load_llm_config():
    load_dotenv(ENV_FILE)
    base = (os.environ.get("VR_LLM_BASE_URL", "") or "").strip()
    key = (os.environ.get("VR_LLM_API_KEY", "") or "").strip()
    model = (os.environ.get("VR_LLM_MODEL", "") or "").strip()
    if not all([base, key, model]):
        raise SystemExit(f"LLM 配置缺失")
    return base, key, model


def make_session():
    s = requests.Session()
    s.trust_env = False
    return s


def call_llm(session, base, key, model, prompt, timeout=120, retries=3):
    """调百炼 LLM，返回正文或 None。带 retries 次重试（应对并发瞬时空返回）。"""
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4096}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last_err = None
    for attempt in range(retries):
        try:
            r = session.post(f"{base}/chat/completions", json=payload, headers=headers, verify=False, timeout=timeout)
        except requests.RequestException as e:
            last_err = f"RequestException: {e}"
            time.sleep(2)
            continue
        if r.status_code != 200:
            last_err = f"HTTP {r.status_code}"
            time.sleep(2)
            continue
        try:
            data = r.json()
        except Exception:
            last_err = "json decode failed"
            time.sleep(2)
            continue
        try:
            content = (data["choices"][0].get("message") or {}).get("content") or ""
        except (KeyError, IndexError) as e:
            last_err = f"choices parse: {e}"
            time.sleep(2)
            continue
        content = content.strip().strip("`").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:\w+)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()
        if content:
            return content
        last_err = "empty content"
        time.sleep(2)
    print(f"    [call_llm] {retries} 次重试均失败: {last_err}")
    return None


def parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


PROMPT = """请为以下证券分析师生成简短描述。

姓名：{name}
所属机构：{org}
覆盖股票数：{coverage_count}
原文片段（含其参与的研报标题与标的，据此推断）：
{snippet}

要求（2 段，客观描述，从原文片段推断其覆盖领域，不臆造具体数据）：

【覆盖领域】从原文片段中出现的标的/行业推断其专注领域（1-2 句）
【风格特点】从研报标题风格推断其研究风格（保守/积极/精准/均衡，1 句）

格式：严格按下面两段输出，每段以【】标签开头，不要其他引导语：

【覆盖领域】...
【风格特点】...

直接输出正文，不要思考过程。"""


def process(f: Path, session, base, key, model) -> dict:
    stem = f.stem
    try:
        text = f.read_text(encoding="utf-8")
    except Exception as e:
        return {"code": stem, "status": "error", "reason": f"读文件失败: {e}"}

    # 幂等：已有段则跳过
    if SECTION_HEADER in text:
        return {"code": stem, "status": "skip", "reason": "已有覆盖领域段"}

    fm = parse_frontmatter(text)
    name = fm.get("name", stem)
    org = fm.get("org", "未知")
    cc = fm.get("coverage_count", "0")

    # 抽取"## 原文片段"段内容作为 snippet（截断防 prompt 过长）
    snippet = ""
    i = text.find("## 原文片段")
    if i >= 0:
        # 段到文件尾或下一个 ## （原文片段通常是末段）
        rest = text[i:]
        snippet = rest[:800]
    if not snippet:
        snippet = "（无原文片段信息）"

    prompt = PROMPT.format(name=name, org=org, coverage_count=cc, snippet=snippet)
    llm_text = call_llm(session, base, key, model, prompt)
    if not llm_text:
        return {"code": stem, "status": "failed", "name": name, "reason": "LLM 返回空"}

    # 解析两段
    cov = style = ""
    cur = None
    buf: list[str] = []
    for line in llm_text.splitlines():
        m = re.match(r"【(覆盖领域|风格特点)】(.*)", line)
        if m:
            if cur == "覆盖领域":
                cov = "\n".join(b for b in buf if b.strip()).strip()
            elif cur == "风格特点":
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
        return {"code": stem, "status": "failed", "name": name, "reason": "LLM 输出解析失败"}

    new_body = f"{ANNOTATION}\n"
    if cov:
        new_body += f"**覆盖领域**：{cov}\n"
    if style:
        new_body += f"**风格特点**：{style}\n"
    new_section = f"{SECTION_HEADER}\n\n{new_body}\n"

    # 插入点：## 来源 之前；若无 ## 来源 则追加到 callout 之后（找 > **关联** 行后的空行）
    insert_idx = text.find(INSERT_BEFORE)
    if insert_idx < 0:
        # 兜底：找 "> **关联**" 行结尾
        i = text.find("> **关联**")
        if i < 0:
            return {"code": stem, "status": "skip", "reason": "无插入锚点"}
        # 跳到该行换行后
        nl = text.find("\n", i)
        insert_idx = nl + 1 if nl >= 0 else len(text)
    new_text = text[:insert_idx] + new_section + text[insert_idx:]
    try:
        f.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return {"code": stem, "status": "error", "reason": f"写文件失败: {e}"}

    return {"code": stem, "status": "ok", "name": org, "cov": cov[:60], "style": style[:60]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("-n", "--concurrency", type=int, default=8)
    args = ap.parse_args()

    base, key, model = load_llm_config()
    print(f"[配置] base={base}  model={model}  并发={args.concurrency}")

    files = sorted([f for f in ANALYSTS_DIR.glob("*.md") if f.stem != "index"])
    targets = [f for f in files if SECTION_HEADER not in f.read_text(encoding="utf-8")]
    print(f"[扫描] 缺覆盖领域段的 analysts: {len(targets)} 个")
    if args.limit:
        targets = targets[:args.limit]
        print(f"[limit] 仅处理前 {args.limit} 个")

    if args.dry_run:
        for f in targets:
            print(f"  [dry-run] {f.stem}")
        return

    session = make_session()
    ok = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(process, f, session, base, key, model): f for f in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"code": f.stem, "status": "error", "reason": f"异常: {e}"}
            if r["status"] == "ok":
                ok += 1
            elif r["status"] == "failed":
                fail += 1
            icon = {"ok": "✓", "failed": "✗", "error": "!", "skip": "-"}.get(r["status"], "?")
            print(f"  [{i:2d}/{len(targets)}] {icon} {r['code'][:24]:24s} ok={ok} fail={fail}  {time.time()-t0:.0f}s")
    print(f"\n[完成] ok={ok} fail={fail}  耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
