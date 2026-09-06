# -*- coding: utf-8 -*-
"""S163 数据质量层：源边界 schema 校验（R1）+ 轻量血缘（R2）。

- :mod:`data_quality.schema_validator`：5 源 schema 校验，bad data 拒绝进 §44 verifier。
- :mod:`data_quality.lineage`：artifact 血缘（script+commit+as_of+io hash），write-once/append-only。
"""
