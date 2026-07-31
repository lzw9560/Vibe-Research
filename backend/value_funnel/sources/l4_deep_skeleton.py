"""S005 L4 四大师深度骨架：数据要点 + 引导问题清单，文字交用户 AI。

合规：系统只备数据骨架与引导问题，ai_text 留空（ai_pending=True）；
四大师方向结论由用户 AI 经 chat 产出（依赖 S001 修复后的 /api/chat）。
"""

from __future__ import annotations

from datetime import datetime

from .. import models


_MASTERS = [
    ("巴菲特", "经济护城河",
     ["10 年后这条护城河还在吗？什么能摧毁它？",
      "能否在不损失销量的情况下提价（定价权）？",
      "ROE 长期是否 >15% 且高且稳？"]),
    ("芒格", "反过来想",
     ["这家公司可能失败的所有路径是什么？",
      "聪明人为什么会不买/做空这家公司？",
      "我最可能在哪里犯错？"]),
    ("段永平", "对的生意 + 对的人",
     ["这是一门对的生意吗（轻资本、高 ROE、可复购）？",
      "管理层是否诚实、能干、股东利益一致？",
      "如果股市关闭 5 年，愿意以这个价格持有吗？"]),
    ("李录", "文明演进",
     ["站在 20 年后回看，这是'标准石油'还是昙花一现？",
      "所在行业是否处于文明级范式转移？",
      "公司在产业价值链中的位置是受益还是被替代？"]),
]


def build_deep_skeleton(code: str, name: str = "", data_summary: str = "") -> models.DeepAnalysisSkeleton:
    """构建四大师骨架。ai_text 留空，ai_pending=True。"""
    perspectives = [
        models.MasterPerspective(
            master=m,
            framework=f,
            data_skeleton=data_summary or f"{name or code} 客观数据要点（见 L2/L3）",
            key_questions=qs,
        )
        for m, f, qs in _MASTERS
    ]
    return models.DeepAnalysisSkeleton(
        code=code,
        name=name or code,
        perspectives=perspectives,
        as_of=datetime.now(),
        ai_pending=True,
    )
