"""Prompt 包 —— 把「分析口径」从引擎里拆出来（移植自 vibe-astock@3c3b7c8 prompts.py）。

只移植纯文本风格字段（analyst_style / analyst_len / judge_requirements / chat_guidance），
砍 focus_model / focus_skeleton / render_focus 三件套（Vibe-Research 无结构化输出模型，
已验证全仓无 schemas.py / response_format 用法），砍 deepdive_style /
deepdive_requirements / verdict_model / verdict_skeleton / render_verdict（Vibe-Research
无个股深挖 agent）。本地包加载见 P4-T4（resolve_data_dir / prompts_local.py）。

默认 RESEARCH_PACK 保守（客观陈述 + 不给买卖点位），私人助理定位下用户可写本地包放宽
（spec §1.1 弱合规：chat.SYSTEM_PROMPT 措辞 S010 已放宽，PromptPack 默认保守是安全默认，
本地包可给方向性研判）。

# derived from vibe-astock@3c3b7c8 (github.com/lzw9560), Apache-2.0, modified
# Original author: Simon Lin (simonlin0423@gmail.com)
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from vr_paths import resolve_data_dir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptPack:
    """一套分析口径。引擎只认这个接口，不关心里面写了什么。

    只保留纯文本风格字段（spec §1.4：砍 focus/deepdive/verdict 三件套）。
    """

    name: str
    analyst_style: str            # 分析师的语气/尺度
    analyst_len: str              # 篇幅约束
    judge_requirements: str       # 复盘裁判产出要求（本期不接线，属复盘裁判链路）
    chat_guidance: str = (
        "个股问答：可给方向性研判、买卖时机研判、参与倾向与操作建议（研究参考性），"
        "但须基于工具查到的真实数据，讲清多空两面与风险，挂轻量风险提醒「历史统计特征，市场有风险，研究参考」，用户最终决策。"
        "不得承诺确定性保证（可给三情景概率/分位区间，不得说「必涨/必跌 X%」）。"
        "上面没覆盖的就说没覆盖，别编。"
    )


RESEARCH_PACK = PromptPack(
    name="research",
    analyst_style=(
        "基于数据讲清楚今天盘面发生了什么、为什么，把依据摆出来。"
        "可给方向性研判、买卖时机研判、操作建议（研究参考性，挂轻量风险提醒「历史统计特征，市场有风险」，用户最终决策），"
        "不承诺确定性保证（可给三情景概率/分位区间，不得说「必涨/必跌 X%」）。"
    ),
    analyst_len="控制在 350 字内。",
    judge_requirements=(
        "1. 判断当前市场情绪档位（冰点/修复/发酵/亢奋/退潮）。\n"
        "2. 梳理 2-5 个当前活跃的题材/板块方向，每个含：支撑依据、风险与证伪信号。\n"
        "3. 列出需警惕的风险信号。\n"
        "4. 给出你对市场所处阶段的判断。\n"
        "⚠️ 全程只做市场与板块层面的研判：不点名推荐个股、不给个股参与倾向、不给买卖点位。"
    ),
)


def _local_pack_path() -> Path | None:
    """本地 prompt 包路径：VR_PROMPTS_LOCAL 环境变量优先，其次 resolve_data_dir/prompts_local.py。"""
    env = os.environ.get("VR_PROMPTS_LOCAL", "").strip()
    if env.lower() in {"builtin", "default", "none"}:
        return None
    if env:
        return Path(env).expanduser()
    p = resolve_data_dir() / "prompts_local.py"
    return p if p.is_file() else None


def load_pack() -> PromptPack:
    """加载 prompt 包：有本地包用本地的，否则 RESEARCH_PACK。

    缺失/损坏 → 静默回落默认包并记日志。importlib 加载的是**可执行代码**（以进程
    权限执行），仅限可信文件；加载失败不能炸掉整个系统。
    """
    path = _local_pack_path()
    if path is None:
        return RESEARCH_PACK
    if not path.is_file():
        logger.warning("prompt 包不存在，回退默认包：%s", path)
        return RESEARCH_PACK
    logger.info("加载本地 prompt 包（以进程权限执行，仅限可信文件）：%s", path)
    mod_name = "vr_prompts_local"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(mod_name, None)
            raise
        pack = getattr(module, "PACK", None)
        if not isinstance(pack, PromptPack):
            raise TypeError(f"{path} 里的 PACK 不是 PromptPack 实例")
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(mod_name, None)
        logger.warning("prompt 包加载失败，回退默认包（%s: %s）", type(exc).__name__, exc)
        return RESEARCH_PACK
    logger.info("已加载本地 prompt 包：%s（%s）", pack.name, path)
    return pack


PACK = load_pack()
