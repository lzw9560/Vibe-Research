# -*- coding: utf-8 -*-
"""S188 · stoke skill 作为系统补充数据源。

stoke（~/stoke，symlink ~/.claude/skills/stoke）聚合 mootdx+akshare+腾讯三源，14 接口。
项目已有 mootdx_src/akshare_src/tencent 覆盖 K 线/实时五档/涨停池——**stoke 不重复这些**，
只接项目缺失的补充接口：研报/个股新闻/财联社电报/强势涨停归因/指数PE/全市场PB/概念行业板块。

调用方式（stoke 走自己 venv，项目 venv 无 stoke 依赖）：
  subprocess 调 ~/stoke/.venv/bin/python + STOKE_HOME=~/stoke
  或项目若装 stoke（pip install -e ~/stoke）则可直接 import。

设计：薄适配层，返 DataFrame → dict/list，消费者零改动。限流遵守 stoke SKILL.md（akshare 5s/腾讯 3s/mootdx 不限）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

STOKE_HOME = Path(os.getenv("STOKE_HOME", str(Path.home() / "stoke")))
STOKE_PYTHON = STOKE_HOME / ".venv" / "bin" / "python"

# stoke 接口 → 项目缺失的补充能力（不重复 K 线/实时五档/涨停池）
_STOKE_SCRIPT = r"""
import os, json
os.environ.setdefault("STOKE_HOME", "{home}")
import sys
sys.path.insert(0, "{home}")
from stoke import Stoke
s = Stoke()
{body}
"""


def _run_stoke(body: str, timeout: int = 60, retries: int = 0) -> Any:
    """跑 stoke venv 子进程，返 JSON 解码结果。stoke 不可用返 {error}。

    timeout/retries 可调（cls_telegraph akshare 财联社接口慢，用更长 timeout + retry）。
    """
    if not STOKE_PYTHON.exists():
        return {"error": f"stoke venv 不存在（{STOKE_PYTHON}），先 cd ~/stoke && uv sync"}
    script = _STOKE_SCRIPT.format(home=str(STOKE_HOME), body=body)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(
                [str(STOKE_PYTHON), "-c", script],
                capture_output=True, text=True, timeout=timeout,
            )
            if r.returncode != 0:
                last_err = RuntimeError(f"stoke 子进程失败: {r.stderr[:300]}")
                continue
            out = r.stdout.strip()
            return json.loads(out) if out else {"error": "stoke 返空"}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            last_err = e
            continue
    return {"error": f"stoke 调用异常（{attempt + 1} 次重试后）: {last_err}"}


def research_report(code: str) -> list[dict]:
    """东财研报（含 PDF + 盈利预测）。项目缺失接口。返 [{报告名称, 机构, 东财评级, 日期, ...}]。"""
    return _run_stoke(f"""
import pandas as pd
df = s.research("{code}")
print(df.to_json(orient="records", force_ascii=False))
""")


def news(code: str) -> list[dict]:
    """个股新闻（akshare 东财）。返 [{标题, 内容, 时间, 来源}]。"""
    return _run_stoke(f"""
df = s.news("{code}")
print(df.to_json(orient="records", force_ascii=False))
""")


def cls_telegraph() -> list[dict]:
    """全球电报/快讯（分钟级）。返 [{标题, 内容, 时间}]。

    RB-10b（2026-09-13）：akshare 财联社 stock_info_global_cls 接口 404 废弃 → 换东财快讯
    stock_info_global_em（200 条，最全；同花顺 ths 20 条/新浪 sina 20 条作备选）。
    akshare-direct（非 em_get 限流通道），但 daily_full_pull 单日单次调用低频，IP 封风险极低
    （同原 cls_telegraph 的 akshare-direct 风险）。要严格 em_get 通道后续按需加 astock.em_telegraph。
    """
    r = _run_stoke("""
import akshare as ak
df = ak.stock_info_global_em()
df = df[["标题", "摘要", "发布时间"]].rename(columns={"摘要": "内容", "发布时间": "时间"})
print(df.to_json(orient="records", force_ascii=False))
""", timeout=60, retries=1)
    if isinstance(r, list):
        return r
    # r 是 {error} dict —— 失败容错返空 list（daily_full_pull 会 logger.warning 暴露原因）
    return []


def strong_stocks(date: str | None = None) -> list[dict]:
    """强势涨停含题材归因（akshare）。项目 zt_history 只有 code/name，stoke 多「入选理由/所属行业」归因。
    date=None 取当日。返 [{代码, 名称, 涨跌幅, 入选理由, 所属行业}]。
    """
    arg = f'"{date}"' if date else "None"
    return _run_stoke(f"""
df = s.strong_stocks({arg})
print(df.to_json(orient="records", force_ascii=False))
""")


def index_pe(name: str = "上证50") -> list[dict]:
    """指数 PE 历史（腾讯）。项目估值层弱。返 [{date, pe}]。"""
    return _run_stoke(f"""
df = s.index_pe("{name}")
print(df.to_json(orient="records", force_ascii=False))
""")


def market_pb() -> list[dict]:
    """全市场 PB 历史（腾讯）。返 [{date, pb}]。"""
    return _run_stoke("""
df = s.market_pb()
print(df.to_json(orient="records", force_ascii=False))
""")


def concept_list() -> list[dict]:
    """概念板块列表（akshare）。返 [{板块名, 成分数}]。"""
    return _run_stoke("""
df = s.concept_list() if hasattr(s, "concept_list") else s.akshare.get_concept_list()
print(df.to_json(orient="records", force_ascii=False))
""")


def industry_list() -> list[dict]:
    """行业板块列表（akshare）。返 [{板块名, 成分数}]。"""
    return _run_stoke("""
df = s.industry_list() if hasattr(s, "industry_list") else s.akshare.get_industry_list()
print(df.to_json(orient="records", force_ascii=False))
""")


__all__ = [
    "research_report", "news", "cls_telegraph", "strong_stocks",
    "index_pe", "market_pb", "concept_list", "industry_list",
]
