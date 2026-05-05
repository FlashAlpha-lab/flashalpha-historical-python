"""Typed response models for the FlashAlpha Historical SDK.

These are ``TypedDict`` aliases — at runtime each is a plain ``dict``. Existing
code that does ``result["field"]`` keeps working unchanged. Static type
checkers (mypy/pyright) and IDEs see the field shape and provide autocomplete.

The Historical API returns the same response shapes as the live API — the
only difference is that every analytics endpoint requires an ``at=`` parameter.
The types defined here mirror the live SDK exactly; if a typed shape changes
on the live side, change it here too.

Currently typed:
    - ``ExposureSummaryResponse`` (full payload of GET /v1/exposure/summary/{symbol})

All numeric fields that the API can leave ``null`` are typed
``Optional[float]`` / ``Optional[int]``. For historical responses, several
fields are documented as always-null/zero ("backtest_mode" gaps) — those are
typed as their nullable form so callers don't write code assuming a value.
"""

from typing import Literal, Optional, TypedDict


# ─── ExposureSummary ─────────────────────────────────────────────────────────
#
# Typed model for ``GET /v1/exposure/summary/{symbol}?at=...``.
#
# Direction casing: /v1/exposure/summary/ and /v1/exposure/zero-dte/ both
# return lowercase "buy" / "sell". Docs and typed models use that casing
# consistently.


class ExposureSummaryExposures(TypedDict, total=False):
    # Field-level Optional matches C#/Go/Java (defensive — API may return null
    # under unobserved edge conditions even when the parent block is present).
    net_gex: Optional[float]
    net_dex: Optional[float]
    net_vex: Optional[float]
    net_chex: Optional[float]


class ExposureSummaryInterpretation(TypedDict, total=False):
    gamma: Optional[str]
    vanna: Optional[str]
    charm: Optional[str]


class ExposureSummaryHedgingMove(TypedDict, total=False):
    dealer_shares_to_trade: Optional[float]
    direction: Optional[Literal["buy", "sell"]]
    notional_usd: Optional[float]


class ExposureSummaryHedgingEstimate(TypedDict, total=False):
    spot_up_1pct: ExposureSummaryHedgingMove
    spot_down_1pct: ExposureSummaryHedgingMove


class ExposureSummaryZeroDte(TypedDict, total=False):
    net_gex: Optional[float]
    pct_of_total_gex: Optional[float]
    expiration: Optional[str]


class ExposureSummaryResponse(TypedDict, total=False):
    symbol: str
    underlying_price: Optional[float]
    as_of: str
    # Note: ``as_of_requested`` exists on /v1/exposure/{gex,dex,narrative} but
    # NOT on /v1/exposure/summary. Don't add it to this type even if it would
    # be defensive — the field genuinely isn't returned for this endpoint.
    gamma_flip: Optional[float]
    # Confirmed live values in tests across Py/JS/.NET/Go/Java:
    #   positive_gamma | negative_gamma | neutral
    # Documented fourth value: undetermined (when there's no usable options
    # data). `neutral` appears in edge cases where net_gex straddles zero.
    # Don't conflate with ``maxpain.signal`` (also bullish/bearish/neutral but
    # a separate field).
    regime: Literal["positive_gamma", "negative_gamma", "neutral", "undetermined"]
    exposures: ExposureSummaryExposures
    interpretation: ExposureSummaryInterpretation
    hedging_estimate: ExposureSummaryHedgingEstimate
    zero_dte: ExposureSummaryZeroDte
