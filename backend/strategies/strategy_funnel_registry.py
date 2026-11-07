# -*- coding: utf-8 -*-
"""strategy_funnel_registry.py —— re-export 兼容层（thin shim）。

原 940 行 god-module 已拆为 ``backend/strategies/funnel/`` 包（5 子模块）。
本文件 re-export 全部公共名，保证 ``import strategies.strategy_funnel_registry`` /
``from strategies.strategy_funnel_registry import X`` 的调用方零改可用。
"""
from __future__ import annotations

