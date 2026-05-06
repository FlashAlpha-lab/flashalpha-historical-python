"""FlashAlpha Historical Python SDK.

Point-in-time replay of every live FlashAlpha analytics endpoint. SPY
2018-04-16 → present, extended forward as new data is published; more symbols
added on demand.

Quickstart
----------
>>> from flashalpha_historical import FlashAlphaHistorical
>>> hx = FlashAlphaHistorical("YOUR_API_KEY")
>>>
>>> # one snapshot
>>> hx.exposure_summary("SPY", at="2020-03-16T15:30:00")
>>>
>>> # backtest loop
>>> from flashalpha_historical.replay import Backtester, iter_days
>>> bt = Backtester(hx, method="stock_summary", symbol="SPY")
>>> def strat(at, snap):
...     return {"signal": "short_vol" if snap["volatility"]["vrp"] > 5 else None}
>>> results = bt.run(iter_days("2024-01-02", "2024-03-29"), strat)
"""

from .client import FlashAlphaHistorical, BASE_URL
from .exceptions import (
    AuthenticationError,
    FlashAlphaHistoricalError,
    InsufficientDataError,
    InvalidAtError,
    NoCoverageError,
    NoDataError,
    RateLimitError,
    ServerError,
    SymbolNotFoundError,
    TierRestrictedError,
)
from .replay import (
    Backtester,
    BacktestResult,
    is_trading_day,
    iter_days,
    iter_minutes,
    replay,
)
from .types import (
    ExposureSummaryExposures,
    ExposureSummaryHedgingEstimate,
    ExposureSummaryHedgingMove,
    ExposureSummaryInterpretation,
    ExposureSummaryResponse,
    ExposureSummaryZeroDte,
    VrpCore,
    VrpDirectional,
    VrpGexConditioned,
    VrpMacro,
    VrpRegime,
    VrpResponse,
    VrpStrategyScores,
    VrpTermItem,
    VrpVannaConditioned,
    MaxPainResponse,
    MaxPainDistance,
    MaxPainCurveRow,
    MaxPainOiRow,
    MaxPainByExpirationRow,
    MaxPainDealerAlignment,
    MaxPainExpectedMove,
)

__version__ = "0.4.0rc1"
__all__ = [
    "FlashAlphaHistorical",
    "BASE_URL",
    # exceptions
    "FlashAlphaHistoricalError",
    "AuthenticationError",
    "TierRestrictedError",
    "InvalidAtError",
    "NoCoverageError",
    "NoDataError",
    "SymbolNotFoundError",
    "InsufficientDataError",
    "RateLimitError",
    "ServerError",
    # replay
    "Backtester",
    "BacktestResult",
    "iter_days",
    "iter_minutes",
    "is_trading_day",
    "replay",
    # ── ExposureSummary typed models ──
    "ExposureSummaryResponse",
    "ExposureSummaryExposures",
    "ExposureSummaryInterpretation",
    "ExposureSummaryHedgingEstimate",
    "ExposureSummaryHedgingMove",
    "ExposureSummaryZeroDte",
    # ── VRP ──
    "VrpResponse",
    "VrpCore",
    "VrpDirectional",
    "VrpTermItem",
    "VrpGexConditioned",
    "VrpVannaConditioned",
    "VrpRegime",
    "VrpStrategyScores",
    "VrpMacro",
    # ── MaxPain ──
    "MaxPainResponse",
    "MaxPainDistance",
    "MaxPainCurveRow",
    "MaxPainOiRow",
    "MaxPainByExpirationRow",
    "MaxPainDealerAlignment",
    "MaxPainExpectedMove",
]
