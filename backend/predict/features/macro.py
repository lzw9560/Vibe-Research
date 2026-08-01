"""Macro feature specs — S018 §4.6 / S019 Fred API slice / T15 batch2.

DXY / US 10Y yield sourced from Fred API (independent channel, NOT em_get).
T15 批次2追加：Fed 实际基金利率(DFF)、10Y-2Y 利差(T10Y2Y)、人民币汇率
(DEXCHUS)、WTI 原油(DCOILWTICO)、LME 铜(PCOPPUSDM)——均为 FRED 原生日频。
Per S017-T0b: East Money push2 candidate secids for these are empty.
Per S019 spec: features registered but NOT added to any HEAD_FEATURE_SUBSET
until Fred key is wired + live smoke passes ("未补前不入短线头").

Pure parser is testable; live fetch is a stub (TODO S008/key-on-hand).
"""

from __future__ import annotations

import os
from pathlib import Path

from predict.features.registry import FeatureSpec, Registry
from vr_paths import resolve_data_dir

# ── Module-level immutable spec declarations ────────────────────────

MACRO_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="us_10y_yield",
        source="fred_api",
        category="macro",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="美债10Y收益率(DGS10)，日频，T开盘前(S2)可得，走Fred独立通道",
    ),
    FeatureSpec(
        name="dxy",
        source="fred_api",
        category="macro",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="贸易加权美元指数(DTWEXBGS，Fred广义美元指数；DTWEXB 已于2019废止，改用后继DTWEXBGS)，日频，T开盘前(S2)可得，走Fred独立通道",
    ),
    FeatureSpec(
        name="us_fed_funds_eff",
        source="fred_api",
        category="macro",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="有效联邦基金利率(DFF，日频实际值；注意：非Fed funds期货隐含路径，后者FRED不提供)",
    ),
    FeatureSpec(
        name="us_10y2y_spread",
        source="fred_api",
        category="macro",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="美债10Y-2Y利差(T10Y2Y，FRED官方合成)，日频，走Fred独立通道",
    ),
    FeatureSpec(
        name="usd_cny",
        source="fred_api",
        category="macro",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="人民币兑美元现汇(DEXCHUS，CNY/USD，FRED原生)，日频，走Fred独立通道",
    ),
    FeatureSpec(
        name="wti_crude",
        source="fred_api",
        category="macro",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="WTI原油即期(DCOILWTICO，FRED原生)，日频，走Fred独立通道",
    ),
    FeatureSpec(
        name="lme_copper",
        source="fred_api",
        category="macro",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="LME铜价(PCOPPUSDM，FRED原生)，日频，走Fred独立通道",
    ),
)

# Fred series_id 映射（固定，可复算）
# 注：DTWEXB 于 2019-12-31 废止，dxy 改用后继 DTWEXBGS（Broad, Goods & Services）。
# T15 batch2 追加：DFF/T10Y2Y/DEXCHUS/DCOILWTICO/PCOPPUSDM 均为 FRED 原生日频。
FRED_SERIES = {
    "us_10y_yield": "DGS10",
    "dxy": "DTWEXBGS",
    "us_fed_funds_eff": "DFF",
    "us_10y2y_spread": "T10Y2Y",
    "usd_cny": "DEXCHUS",
    "wti_crude": "DCOILWTICO",
    "lme_copper": "PCOPPUSDM",
}


# ── Registration ────────────────────────────────────────────────────


def register_macro(registry: Registry) -> None:
    """Register macro FeatureSpecs into the given Registry.

    Note: these features are NOT added to any HEAD_FEATURE_SUBSET until the
    Fred API key is wired and a live smoke test passes (per S019 R5).
    """
    for spec in MACRO_SPECS:
        registry.register(spec)


# ── Fred API key reader (VR_DATA_DIR isolated, never logged) ────────


def get_fred_api_key() -> str | None:
    """Read Fred API key from ``$VR_DATA_DIR/fred_api_key``.

    Returns ``None`` if the env var is unset or the file is absent.
    The key is never printed or logged. 默认项目内 .vibe-research/
    （vr_paths，gitignored；旧版 ~/.vibe-research/）。
    """
    key_file = resolve_data_dir() / "fred_api_key"
    if not key_file.is_file():
        return None
    try:
        return key_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# ── Pure parser (no I/O, testable) ──────────────────────────────────


def parse_fred_observations(resp: dict | None) -> list[dict]:
    """Parse a Fred observations response into ``[{date, value}]``.

    Parameters
    ----------
    resp:
        Fred API JSON dict, expected shape
        ``{"observations": [{"date": "YYYY-MM-DD", "value": "1.23"}, ...]}``.
        ``value == "."`` denotes a missing observation → ``None``.

    Returns
    -------
    list[dict]
        Each item ``{"date": str, "value": float | None}``. Empty list on
        ``None``/missing ``observations`` key.
    """
    if not isinstance(resp, dict):
        return []
    observations = resp.get("observations")
    if not isinstance(observations, list):
        return []

    out: list[dict] = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        date = obs.get("date")
        if not isinstance(date, str):
            continue
        raw_value = obs.get("value")
        if raw_value == "." or raw_value is None:
            value: float | None = None
        else:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = None
        out.append({"date": date, "value": value})
    return out


# ── Live fetcher (independent channel, NOT em_get) ───────────────────


def fetch_fred_series(series_id: str, api_key: str | None, proxy: str | None = None) -> dict | None:
    """Fetch a Fred series observations JSON via an independent requests channel.

    Uses ``requests`` directly (NOT ``astock.em_get``) — Fred is a foreign
    source on its own channel per CLAUDE.md §3. Optional ``proxy`` (else
    ``$VR_HTTP_PROXY`` env). Returns ``None`` on no key / non-200 / any error
    so callers fall back gracefully.

    Parameters
    ----------
    series_id:
        Fred series id, e.g. ``"DGS10"`` / ``"DTWEXB"``.
    api_key:
        Fred API key (read via :func:`get_fred_api_key`). ``None`` → return None.
    proxy:
        Optional ``http(s)://host:port`` proxy. If ``None``, falls back to
        the ``VR_HTTP_PROXY`` env var; absent → direct connection.
    """
    if not api_key:
        return None
    resolved_proxy = proxy if proxy is not None else os.environ.get("VR_HTTP_PROXY")
    proxies = {"http": resolved_proxy, "https": resolved_proxy} if resolved_proxy else None
    try:
        import requests

        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series_id, "api_key": api_key, "file_type": "json"},
            proxies=proxies,
            timeout=15,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None
