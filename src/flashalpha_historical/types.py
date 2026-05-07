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

from typing import List, Literal, Optional, TypedDict


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
    #   positive_gamma | negative_gamma | unknown
    # ``unknown`` is returned when there's no usable options data.
    # Don't conflate with ``maxpain.signal`` (also bullish/bearish/neutral but
    # a separate field).
    regime: Literal["positive_gamma", "negative_gamma", "unknown"]
    exposures: ExposureSummaryExposures
    interpretation: ExposureSummaryInterpretation
    hedging_estimate: ExposureSummaryHedgingEstimate
    zero_dte: ExposureSummaryZeroDte


# ─── VRP (Variance Risk Premium) ─────────────────────────────────────────────
#
# Typed model for ``GET /v1/vrp/{symbol}?at=...`` (Alpha+).
#
# The Historical API returns the same shape as the live API with two
# differences in ``macro``:
#   - ``hy_spread`` is populated (live currently returns ``None``)
#   - ``fed_funds`` is ABSENT on historical (live includes it)
#
# This is THE classic nested-trap endpoint. Common silent-null patterns
# these types make impossible at the SDK boundary:
#
#   - ``response["z_score"]``  ✗  → use ``response["vrp"]["z_score"]``
#   - ``response["percentile"]`` ✗ → use ``response["vrp"]["percentile"]``
#   - ``response["put_vrp"]`` ✗ → use ``response["directional"]["downside_vrp"]``
#   - ``response["net_gex"]`` ✗ → use ``response["regime"]["net_gex"]``
#
# On historical responses with insufficient warm-up (``at`` near
# 2018-04-16), ``vrp.z_score``, ``vrp.percentile``, ``regime.vrp_regime``,
# ``strategy_scores``, and ``net_harvest_score`` are all ``None``.


class VrpCore(TypedDict, total=False):
    """Core VRP metrics block — the heart of the response.

    The variance risk premium is the spread between IMPLIED volatility
    (forward-looking, priced into options) and REALIZED volatility
    (backward-looking, observed from spot returns). Positive VRP = options
    are pricing more vol than the underlying actually moved → premium for
    selling vol. Negative VRP = options too cheap relative to realized →
    premium for buying vol.

    Nested under ``response["vrp"]`` — NOT top-level.
    """

    # At-the-money implied volatility (annualised, percentage points,
    # e.g. 18.5 = 18.5%). Pulled from the SVI fit at ``at``.
    atm_iv: Optional[float]
    # Realized volatility ladders — annualised %, computed from spot
    # log-returns over the trailing 5/10/20/30 trading days BEFORE ``at``
    # (no future leakage on historical responses).
    rv_5d: Optional[float]
    rv_10d: Optional[float]
    rv_20d: Optional[float]
    rv_30d: Optional[float]
    # Variance risk premia at each horizon: ``atm_iv - rv_Nd``. Positive =
    # IV richer than realised (premium for selling vol).
    vrp_5d: Optional[float]
    vrp_10d: Optional[float]
    vrp_20d: Optional[float]
    vrp_30d: Optional[float]
    # Z-score of the current 20-day VRP vs its trailing ``history_days``-
    # day window. ``None`` when ``at`` is close to the dataset start
    # (2018-04-16) and there's insufficient history. Use percentile or
    # raw vrp_20d in that case.
    z_score: Optional[float]
    # Percentile rank (0-100) of the current VRP within the trailing
    # window. ``None`` when ``history_days`` is too small.
    percentile: Optional[int]
    # Number of trading days in the trailing percentile/z-score window.
    # Scales with how far past 2018-04-16 the ``at`` timestamp is. When
    # this is small (<30), treat ``z_score`` and ``percentile`` as noise.
    history_days: Optional[int]


class VrpDirectional(TypedDict, total=False):
    """Directional VRP skew — separates upside-tail vs downside-tail premia.

    Splits the variance risk premium by direction: how much premium are
    options pricing on the DOWNSIDE (puts) vs the UPSIDE (calls). A large
    ``downside_vrp`` with small ``upside_vrp`` is the classic "expensive
    crash insurance" pattern — premium for selling puts in calm tape.

    The canonical field names are ``downside_vrp`` and ``upside_vrp``.
    Customers from other vendors often type ``put_vrp`` / ``call_vrp`` —
    those don't exist on this response.
    """

    put_wing_iv_25d: Optional[float]
    call_wing_iv_25d: Optional[float]
    downside_rv_20d: Optional[float]
    upside_rv_20d: Optional[float]
    # ``put_wing_iv_25d - downside_rv_20d``. Positive = downside crash
    # protection priced richer than actual downside RV.
    downside_vrp: Optional[float]
    # ``call_wing_iv_25d - upside_rv_20d``. Positive = upside calls rich.
    upside_vrp: Optional[float]


class VrpTermItem(TypedDict, total=False):
    """One row of the VRP term structure — an (DTE, IV, RV, VRP) tuple."""

    dte: Optional[int]
    iv: Optional[float]
    rv: Optional[float]
    vrp: Optional[float]


class VrpGexConditioned(TypedDict, total=False):
    """VRP harvest score conditioned on the prevailing dealer-gamma regime."""

    # Gamma regime at this snapshot. ``"positive_gamma"`` |
    # ``"negative_gamma"`` | ``"unknown"`` (when there's insufficient data
    # to classify).
    regime: Optional[Literal["positive_gamma", "negative_gamma", "unknown"]]
    # 0-100 composite. >70 = strong harvest signal; <30 = avoid.
    harvest_score: Optional[float]
    interpretation: Optional[str]


class VrpVannaConditioned(TypedDict, total=False):
    """VRP outlook conditioned on net dealer vanna exposure."""

    outlook: Optional[str]
    interpretation: Optional[str]


class VrpRegime(TypedDict, total=False):
    """Regime snapshot block.

    ``net_gex`` lives here, NOT at the top level.
    """

    # ``"positive_gamma"`` | ``"negative_gamma"`` | ``"unknown"``.
    gamma: Optional[Literal["positive_gamma", "negative_gamma", "unknown"]]
    # ``None`` on historical with insufficient warmup.
    vrp_regime: Optional[str]
    # Net dealer gamma exposure in dollars per 1% spot move.
    net_gex: Optional[float]
    gamma_flip: Optional[float]


class VrpStrategyScores(TypedDict, total=False):
    """0-100 suitability scores for canonical short-vol strategies.

    Each field can be ``None`` on historical when inputs are not
    computable for the given ``at`` timestamp.
    """

    short_put_spread: Optional[int]
    short_strangle: Optional[int]
    iron_condor: Optional[int]
    calendar_spread: Optional[int]


class VrpMacro(TypedDict, total=False):
    """Macro-context snapshot used to condition the VRP outlook.

    Note: ``fed_funds`` is intentionally absent on historical responses
    (it exists on the live SDK type only).
    """

    vix: Optional[float]
    vix_3m: Optional[float]
    # ``(vix_3m - vix) / vix * 100`` — % steepness. Positive = contango.
    vix_term_slope: Optional[float]
    # 10-year US Treasury yield (%, FRED ``DGS10``).
    dgs10: Optional[float]
    # ICE BofA US High Yield OAS. Populated on historical responses;
    # the live SDK currently returns ``None`` here (data gap).
    hy_spread: Optional[float]


class VrpResponse(TypedDict, total=False):
    """Variance Risk Premium dashboard from ``GET /v1/vrp/{symbol}?at=...``.

    Same shape as the live API with two macro-block diffs:
        - ``macro.hy_spread`` is populated here; live returns ``None``.
        - ``macro.fed_funds`` is absent here; live includes it.

    Common silent-null traps (now type-checked at the SDK boundary):
        - ``response.z_score``  → use ``response["vrp"]["z_score"]``
        - ``response.percentile`` → use ``response["vrp"]["percentile"]``
        - ``response.atm_iv`` → use ``response["vrp"]["atm_iv"]``
        - ``response.put_vrp`` → use ``response["directional"]["downside_vrp"]``
        - ``response.net_gex`` → use ``response["regime"]["net_gex"]``
        - ``response.harvest_score`` → use ``response["gex_conditioned"]["harvest_score"]``
          (``response["net_harvest_score"]`` is a SEPARATE composite.)

    Returns 403 ``tier_restricted`` for anything below Alpha plan.

    Historical-specific empty/null caveats:
        - ``vrp.z_score`` / ``vrp.percentile`` / ``regime.vrp_regime`` /
          ``strategy_scores`` / ``net_harvest_score`` are all ``None`` on
          early historical timestamps where there's insufficient
          back-window to compute percentiles. ``warnings`` will explain.
    """

    symbol: str
    underlying_price: Optional[float]
    as_of: str
    market_open: Optional[bool]
    vrp: VrpCore
    variance_risk_premium: Optional[float]
    convexity_premium: Optional[float]
    fair_vol: Optional[float]
    directional: VrpDirectional
    term_vrp: List[VrpTermItem]
    gex_conditioned: VrpGexConditioned
    vanna_conditioned: VrpVannaConditioned
    regime: VrpRegime
    # ``None`` on historical when warmup is too short.
    strategy_scores: Optional[VrpStrategyScores]
    # ``None`` on historical when warmup is too short.
    net_harvest_score: Optional[int]
    dealer_flow_risk: Optional[int]
    # Server-side warnings about data quality. Examples:
    # ``"insufficient_history_for_zscore"``. Always present (possibly empty).
    warnings: List[str]
    macro: VrpMacro


# ─── MaxPain ─────────────────────────────────────────────────────────────────
#
# Typed model for ``GET /v1/maxpain/{symbol}?at=...`` (Basic+).
#
# The historical version returns the same shape as the live API, with one
# operational difference: ``oi_by_strike.*.call_volume`` and ``put_volume``
# are always ``0`` on historical (the minute-resolution options table doesn't
# carry intraday volume). Use ``call_oi`` / ``put_oi`` for the historical
# positioning view; the volume fields are placeholders for shape parity.


class MaxPainDistance(TypedDict, total=False):
    """Distance from spot to the max-pain strike."""

    # Dollar distance: ``|underlying_price - max_pain_strike|``.
    absolute: Optional[float]
    # Percent of spot: ``absolute / underlying_price * 100``. Use this to
    # compare across symbols of different price levels.
    percent: Optional[float]
    # ``"above"`` (spot > max_pain), ``"below"`` (spot < max_pain), or
    # ``"at"`` (within rounding). The signal field uses this + a 5%
    # threshold to derive the bullish/bearish/neutral classification.
    direction: Optional[Literal["above", "below", "at"]]


class MaxPainCurveRow(TypedDict, total=False):
    """One row of the strike-by-strike pain curve.

    Each row is the dollar pain (intrinsic value × OI × 100 contract
    multiplier) summed across all expirations at that strike. The strike
    where ``total_pain`` is minimized is the max-pain strike.
    """

    strike: Optional[float]
    # Dollar intrinsic value of all calls at this strike summed across the
    # chain (when spot pins here, this is what call holders collectively win
    # vs the dealer side).
    call_pain: Optional[float]
    # Dollar intrinsic value of all puts at this strike. Mirror of
    # ``call_pain`` for the put side.
    put_pain: Optional[float]
    # ``call_pain + put_pain``. The pain curve's minimum identifies max pain.
    total_pain: Optional[float]


class MaxPainOiRow(TypedDict, total=False):
    """One row of the OI-by-strike breakdown.

    Per-strike open interest and volume by side. Lets you see where the
    OI is concentrated independent of the dollar-weighted pain calculation.

    Note: on the Historical API, ``call_volume`` and ``put_volume`` are
    always ``0`` (placeholder fields — the minute table doesn't carry
    intraday volume).
    """

    strike: Optional[float]
    call_oi: Optional[int]
    put_oi: Optional[int]
    total_oi: Optional[int]
    call_volume: Optional[int]
    put_volume: Optional[int]


class MaxPainByExpirationRow(TypedDict, total=False):
    """Per-expiry max-pain breakdown when no ``expiration`` filter is applied.

    Lets you see how max pain shifts across the term structure — useful for
    spotting cases where the front-week max pain differs sharply from the
    LEAP max pain (often a sign of where the dealer flow is most active).

    This list is ``None`` when the request specifies an ``expiration``
    filter — the response is then scoped to that single expiry and the
    multi-expiry view is suppressed.
    """

    # ``"yyyy-MM-dd"`` of this expiry.
    expiration: Optional[str]
    # Max-pain strike for this expiry's option chain alone.
    max_pain_strike: Optional[float]
    # Days to expiry (counting from ``as_of``).
    dte: Optional[int]
    # Sum of OI across all contracts at this expiry.
    total_oi: Optional[int]


class MaxPainDealerAlignment(TypedDict, total=False):
    """GEX-based dealer-alignment overlay on the max-pain view.

    Re-uses the same gamma-exposure inputs as ``/v1/exposure/levels`` and
    ``/v1/exposure/summary``. The headline ``alignment`` label tells you
    whether dealer hedging will REINFORCE the max-pain pin or fight it:

        - ``"converging"``: max pain near gamma flip and between the
          walls — dealer hedging supports the pin (strongest pin setup).
        - ``"moderate"``: max pain between the walls but far from flip.
        - ``"diverging"``: max pain outside the wall range — dealer
          hedging actively pushes spot away from max pain.
        - ``"unknown"``: insufficient data to classify.
    """

    alignment: Optional[Literal["converging", "moderate", "diverging", "unknown"]]
    # Plain-English explanation. Safe to surface verbatim.
    description: Optional[str]
    # Strike where net dealer gamma crosses zero. Same definition as
    # ``exposure_summary.gamma_flip``.
    gamma_flip: Optional[float]
    # Strike with highest absolute call GEX (dealer-side resistance).
    call_wall: Optional[float]
    # Strike with highest absolute put GEX (dealer-side support).
    put_wall: Optional[float]


class MaxPainExpectedMove(TypedDict, total=False):
    """Implied move from the ATM straddle, contextualized vs max pain.

    Tells you whether the max-pain strike is even reachable within the
    options-implied 1σ move. If ``max_pain_within_expected_range`` is
    ``False``, the pin is unlikely to play out by expiry under the current
    IV regime — the magnet exists but spot probably can't get there.
    """

    # ATM straddle mid in dollars. Rough proxy for the 1σ implied move.
    straddle_price: Optional[float]
    # ATM implied volatility (annualised %, e.g. 18.5 = 18.5%).
    atm_iv: Optional[float]
    # ``True`` when ``|spot - max_pain_strike| <= straddle_price``.
    max_pain_within_expected_range: Optional[bool]


class MaxPainResponse(TypedDict, total=False):
    """Max pain dashboard from ``GET /v1/maxpain/{symbol}``.

    Returns the strike where total option-holder pain (intrinsic value × OI)
    is minimized, plus:

        - per-strike pain curve and OI breakdown
        - per-expiry calendar (when no ``expiration`` filter is set)
        - GEX-based dealer alignment overlay (call wall / put wall /
          gamma flip — same numbers as ``/v1/exposure/levels``)
        - expected move from the ATM straddle
        - 0-100 pin probability composite

    The endpoint accepts an optional ``expiration`` query filter
    (``yyyy-MM-dd``). When present, the response is scoped to that single
    expiry and ``max_pain_by_expiration`` is ``None``. When absent, the
    full-chain max pain is returned alongside the multi-expiry calendar.

    Returns 403 ``tier_restricted`` for Free-tier users; requires Basic+.
    """

    symbol: str
    underlying_price: Optional[float]
    as_of: str
    # The headline number. Strike where total chain pain is minimized.
    max_pain_strike: Optional[float]
    # Distance from spot to ``max_pain_strike`` (absolute, percent, direction).
    distance: MaxPainDistance
    # ``"bullish"`` (spot >= 5% below max_pain — pin attracts upside),
    # ``"bearish"`` (>= 5% above), or ``"neutral"`` (within 5%).
    signal: Optional[Literal["bullish", "bearish", "neutral"]]
    # Expiration this view is scoped to. When the request omits the
    # ``expiration`` filter, this field is the front-month expiry the
    # full-chain max pain happened to land on.
    expiration: Optional[str]
    # Total put OI / total call OI across the relevant chain. >1.0 means
    # put-heavy positioning. Often correlates with ``signal == "bullish"``
    # (puts are protection; heavy-put chains often have spot below max pain).
    put_call_oi_ratio: Optional[float]
    # Strike-by-strike pain curve. The minimum is at ``max_pain_strike``.
    pain_curve: List[MaxPainCurveRow]
    # Per-strike OI + volume breakdown. Same strike grid as ``pain_curve``.
    oi_by_strike: List[MaxPainOiRow]
    # Per-expiry calendar. ``None`` when the request specified an expiry.
    max_pain_by_expiration: Optional[List[MaxPainByExpirationRow]]
    # GEX-based dealer alignment overlay. See ``MaxPainDealerAlignment``.
    dealer_alignment: MaxPainDealerAlignment
    # Same gamma classification as on ``exposure_summary``:
    # positive_gamma | negative_gamma | unknown.
    regime: Optional[Literal["positive_gamma", "negative_gamma", "unknown"]]
    # Expected move from the ATM straddle, contextualized vs max pain.
    expected_move: MaxPainExpectedMove
    # 0-100 composite — likelihood of pinning to ``max_pain_strike``.
    # Inputs: OI concentration (30%), magnet proximity (25%), time
    # remaining (25%), gamma magnitude (20%). Most meaningful for near-term
    # expiries — for LEAPs this score will be low regardless of OI shape.
    pin_probability: Optional[int]


# ─── StockSummary ────────────────────────────────────────────────────────────
#
# Typed model for ``GET /v1/stock/{symbol}/summary?at=...``.
#
# Historical replay of FlashAlpha's "single best snapshot" endpoint —
# one round-trip returns the price quote, IV/HV/VRP, the 25-delta skew
# triangle, the IV term structure, options flow aggregates, the full
# dealer-exposure view, and the macro context AS OF the requested
# timestamp. Same shape as the live endpoint with two operational
# differences:
#
#   - ``at=`` is REQUIRED on every request (ISO8601 ET timestamp).
#   - ``as_of`` is SNAPPED to the nearest available minute in the
#     historical dataset (the request ``at`` is the target; the
#     response ``as_of`` is what was actually served).
#
# Hedging-estimate sign convention DIFFERS from /v1/exposure/zero-dte:
#   - On stock_summary, ``hedging_estimate.spot_*_1pct.dealer_shares``
#     is a MAGNITUDE; the ``direction`` field carries the sign.
#   - On zero-dte, ``dealer_shares_to_trade`` is signed.


class StockSummaryPrice(TypedDict, total=False):
    """Quote block — bid/ask/mid/last for the underlying.

    On historical, all four fields are minute-snapped to the prevailing
    NBBO at ``as_of`` — bid/ask reflect the quote regime at that minute,
    not a continuous live tick.
    """

    bid: Optional[float]
    ask: Optional[float]
    # ``(bid + ask) / 2``. Reference price for all dollarised numbers.
    mid: Optional[float]
    # Last printed trade at or before ``as_of``.
    last: Optional[float]
    # ET wall-clock timestamp of the underlying ``last`` print.
    last_update: Optional[str]


class StockSummarySkew25d(TypedDict, total=False):
    """25-delta skew snapshot at the front-month expiry as of ``at``."""

    expiry: Optional[str]
    days_to_expiry: Optional[int]
    put_25d_iv: Optional[float]
    atm_iv: Optional[float]
    call_25d_iv: Optional[float]
    # ``put_25d_iv - call_25d_iv``. Positive = puts richer (typical
    # equity-index regime).
    skew_25d: Optional[float]
    # ``(put_25d_iv + call_25d_iv) / (2 * atm_iv)``. ``> 1`` = wings
    # richer than ATM.
    smile_ratio: Optional[float]


class StockSummaryIvTermItem(TypedDict, total=False):
    """One row of the IV term structure — (expiry, IV, DTE)."""

    expiry: Optional[str]
    iv: Optional[float]
    days_to_expiry: Optional[int]


class StockSummaryVolatility(TypedDict, total=False):
    """Volatility block — ATM IV, HV ladders, VRP, skew, term structure.

    HV ladders are computed from spot returns over the trailing 20/60
    trading days BEFORE ``at`` (no future leakage on historical).
    """

    atm_iv: Optional[float]
    hv_20: Optional[float]
    hv_60: Optional[float]
    # ``atm_iv - hv_20`` at ``as_of``. Positive = options pricing more
    # vol than the underlying realised over the trailing 20d.
    vrp: Optional[float]
    skew_25d: StockSummarySkew25d
    iv_term_structure: List[StockSummaryIvTermItem]


class StockSummaryOptionsFlow(TypedDict, total=False):
    """Aggregated chain flow — total OI, volume, and put/call ratios.

    Note on historical: chain volume reflects what was traded between
    market open and ``as_of`` on the requested day; on snapshots before
    market open or on weekends/holidays, volume fields will be ``0``.
    """

    total_call_oi: Optional[int]
    total_put_oi: Optional[int]
    total_call_volume: Optional[int]
    total_put_volume: Optional[int]
    pc_ratio_oi: Optional[float]
    pc_ratio_volume: Optional[float]
    active_expirations: Optional[int]


class StockSummaryInterpretation(TypedDict, total=False):
    """Plain-English narrative for each Greek regime — safe verbatim."""

    gamma: Optional[str]
    vanna: Optional[str]
    charm: Optional[str]


class StockSummaryHedgingMove(TypedDict, total=False):
    """One side (up or down) of the dealer-hedging-flow estimate.

    NOTE — sign convention on stock_summary: ``dealer_shares`` is the
    absolute MAGNITUDE; ``direction`` carries the sign. This DIFFERS
    from the zero-dte endpoint, where ``dealer_shares_to_trade`` is
    signed.
    """

    # MAGNITUDE only — see parent docstring.
    dealer_shares: Optional[float]
    direction: Optional[Literal["buy", "sell"]]
    notional_usd: Optional[float]


class StockSummaryHedgingEstimate(TypedDict, total=False):
    """Estimated dealer hedging flow at +/- 1% spot moves."""

    spot_up_1pct: StockSummaryHedgingMove
    spot_down_1pct: StockSummaryHedgingMove


class StockSummaryZeroDte(TypedDict, total=False):
    """Same-day-expiration contribution to the chain totals at ``as_of``."""

    net_gex: Optional[float]
    pct_of_total: Optional[float]
    # ``"yyyy-MM-dd"`` of the same-day expiry; ``None`` on names without
    # a 0DTE on the requested date.
    expiration: Optional[str]


class StockSummaryTopStrike(TypedDict, total=False):
    """One row of the "top strikes by net GEX" leaderboard."""

    strike: Optional[float]
    net_gex: Optional[float]
    call_oi: Optional[int]
    put_oi: Optional[int]
    total_oi: Optional[int]


class StockSummaryExposure(TypedDict, total=False):
    """Full dealer-exposure block at ``as_of``.

    ``Optional[StockSummaryExposure]`` on the parent — the entire
    block is ``None`` on names with no usable options chain at the
    requested timestamp.
    """

    net_gex: Optional[float]
    net_dex: Optional[float]
    net_vex: Optional[float]
    net_chex: Optional[float]
    gamma_flip: Optional[float]
    call_wall: Optional[float]
    put_wall: Optional[float]
    max_pain: Optional[float]
    highest_oi_strike: Optional[float]
    regime: Optional[Literal["positive_gamma", "negative_gamma", "unknown"]]
    interpretation: StockSummaryInterpretation
    # NOTE: ``dealer_shares`` is MAGNITUDE; ``direction`` carries sign.
    hedging_estimate: StockSummaryHedgingEstimate
    zero_dte: StockSummaryZeroDte
    top_strikes: List[StockSummaryTopStrike]
    oi_weighted_dte: Optional[float]


class StockSummaryMacroIndex(TypedDict, total=False):
    """One macro index level (VIX, VVIX, SKEW, SPX, MOVE).

    Historical macro is sourced from FRED / CBOE end-of-day series;
    intraday minute snapshots use the most recent available daily
    close. All three fields can be ``None`` together on weekends or
    when the upstream feed didn't carry the index on the requested date.
    """

    value: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]


class StockSummaryVixTermLevels(TypedDict, total=False):
    """VIX term-structure levels: 9-day / 30-day / 3-month / 6-month."""

    vix9d: Optional[float]
    vix: Optional[float]
    vix3m: Optional[float]
    vix6m: Optional[float]


class StockSummaryVixTermStructure(TypedDict, total=False):
    """VIX term structure shape — levels, near slope, contango/backwardation."""

    levels: StockSummaryVixTermLevels
    near_slope_pct: Optional[float]
    structure: Optional[Literal["contango", "backwardation"]]


class StockSummaryVixFutures(TypedDict, total=False):
    """VIX futures basis — front-month vs spot VIX."""

    front_month: Optional[float]
    spot: Optional[float]
    spread: Optional[float]
    basis_pct: Optional[float]
    basis: Optional[Literal["contango", "backwardation"]]


class StockSummaryFearAndGreed(TypedDict, total=False):
    """CNN-style fear-and-greed composite."""

    score: Optional[int]
    rating: Optional[str]


class StockSummaryMacro(TypedDict, total=False):
    """Macro context block at ``as_of`` — VIX/VVIX/SKEW/SPX/MOVE.

    Block always present on a successful response; individual leaves
    can be ``None`` on dates outside the upstream macro feed's coverage.
    """

    vix: StockSummaryMacroIndex
    vvix: StockSummaryMacroIndex
    skew: StockSummaryMacroIndex
    spx: StockSummaryMacroIndex
    move: StockSummaryMacroIndex
    vix_term_structure: StockSummaryVixTermStructure
    vix_futures: StockSummaryVixFutures
    fear_and_greed: StockSummaryFearAndGreed


class StockSummaryResponse(TypedDict, total=False):
    """Historical replay of FlashAlpha's "single best snapshot" endpoint.

    Response from ``GET /v1/stock/{symbol}/summary?at=...``. Returns
    the full picture for a name as of the requested timestamp:
    price, IV/HV/VRP, 25-delta skew, IV term structure, options flow
    aggregates, full dealer exposure (Greeks, walls, gamma flip, max
    pain, hedging estimate, 0DTE attribution, top strikes), and macro
    context (VIX, VVIX, SKEW, SPX, MOVE, term structure, fear/greed).

    Historical-specific behaviour
    -----------------------------
    - **``at=`` is REQUIRED.** Pass an ISO8601 ET timestamp
      (``"YYYY-MM-DDTHH:MM:SS"``). The historical client raises
      ``InvalidAtError`` if it's missing or malformed.
    - **``as_of`` is SNAPPED.** The requested ``at`` is the target;
      the response ``as_of`` is the actual minute the historical
      dataset served — typically within ±1 minute, occasionally further
      around feed gaps. Always read ``as_of`` rather than echoing your
      request ``at`` for downstream timestamping.
    - On dates near the dataset start (2018-04-16), HV ladders may
      have insufficient warmup and individual fields will be ``None``.
      ``warnings``-style errors are surfaced via the response shape's
      ``Optional`` fields, not a separate warnings list on this
      endpoint.

    Hedging-estimate sign convention (IMPORTANT)
    --------------------------------------------
    On THIS endpoint, ``exposure.hedging_estimate.spot_*_1pct.dealer_shares``
    is a MAGNITUDE; ``direction`` (``"buy"``/``"sell"``) carries the
    sign. This DIFFERS from the zero-dte endpoint, where the
    ``dealer_shares_to_trade`` field is signed.
    """

    symbol: str
    # SNAPPED minute — read THIS, not your request ``at``.
    as_of: str
    # ``True`` if NYSE was open at ``as_of``.
    market_open: Optional[bool]
    price: StockSummaryPrice
    volatility: StockSummaryVolatility
    options_flow: StockSummaryOptionsFlow
    # ``None`` on names without a usable options chain at ``as_of``.
    exposure: Optional[StockSummaryExposure]
    # Block always present; individual leaves can be ``None``.
    macro: StockSummaryMacro


# ─── ExposureNarrative ───────────────────────────────────────────────────────
#
# Typed model for ``GET /v1/exposure/narrative/{symbol}?at=...`` (Growth+).
#
# Historical replay of FlashAlpha's "LLM-friendly verbal output"
# endpoint — narrative strings safe verbatim, paired with the numeric
# data block that backs them.


class NarrativeOiChange(TypedDict, total=False):
    """One row of the "top OI changes vs prior session" leaderboard."""

    strike: Optional[float]
    type: Optional[Literal["call", "put"]]
    # Signed: positive = position added, negative = closed.
    oi_change: Optional[int]
    volume: Optional[int]


class NarrativeData(TypedDict, total=False):
    """Numeric data block backing the narrative strings at ``as_of``."""

    net_gex: Optional[float]
    # Net dealer GEX at the prior session's close (anchor for
    # ``net_gex_change_pct``).
    net_gex_prior: Optional[float]
    net_gex_change_pct: Optional[float]
    vix: Optional[float]
    gamma_flip: Optional[float]
    call_wall: Optional[float]
    put_wall: Optional[float]
    # Dealer-positioning regime classification. ``"positive_gamma"`` |
    # ``"negative_gamma"`` | ``"unknown"`` (same enum as
    # ``exposure_summary.regime``).
    regime: Optional[Literal["positive_gamma", "negative_gamma", "unknown"]]
    zero_dte_pct: Optional[float]
    top_oi_changes: List[NarrativeOiChange]


class Narrative(TypedDict, total=False):
    """Narrative strings + the data block that backs them.

    Every string field below is editorially safe to surface verbatim
    in customer-facing UIs / LLM tool-call outputs.
    """

    regime: Optional[str]
    gex_change: Optional[str]
    key_levels: Optional[str]
    flow: Optional[str]
    vanna: Optional[str]
    charm: Optional[str]
    zero_dte: Optional[str]
    outlook: Optional[str]
    data: NarrativeData


class NarrativeResponse(TypedDict, total=False):
    """FlashAlpha's "LLM-friendly verbal output" endpoint — historical replay.

    Response from ``GET /v1/exposure/narrative/{symbol}?at=...``
    (Growth+). Returns plain-English narrative strings paired with the
    numeric data block that backs them. Every string is editorially
    safe to surface verbatim in chat / newsletters / LLM outputs.

    ``at=`` is required; ``as_of`` is snapped to the nearest available
    minute. Tier requirement: Growth+ (returns 403 ``tier_restricted``).
    """

    symbol: str
    underlying_price: Optional[float]
    # Snapped minute — read THIS, not your request ``at``.
    as_of: str
    narrative: Narrative


# ─── ExposureLevels ──────────────────────────────────────────────────────────
#
# Typed model for ``GET /v1/exposure/levels/{symbol}?at=...``.


class ExposureLevels(TypedDict, total=False):
    """The seven canonical dealer-flow levels for a symbol at ``as_of``."""

    gamma_flip: Optional[float]
    max_positive_gamma: Optional[float]
    max_negative_gamma: Optional[float]
    call_wall: Optional[float]
    put_wall: Optional[float]
    highest_oi_strike: Optional[float]
    # ``None`` on dates where the symbol had no same-day expiry.
    zero_dte_magnet: Optional[float]


class ExposureLevelsResponse(TypedDict, total=False):
    """Dealer-flow levels from ``GET /v1/exposure/levels/{symbol}?at=...``.

    Pared-down view returning just the headline strikes — gamma flip,
    max ±gamma, call wall, put wall, highest OI strike, 0DTE magnet —
    as of the requested timestamp. Cheaper / smaller payload than
    ``/v1/exposure/summary``.

    ``at=`` is required; ``as_of`` is snapped to the nearest minute.
    """

    symbol: str
    underlying_price: Optional[float]
    # Snapped minute — read THIS, not your request ``at``.
    as_of: str
    levels: ExposureLevels
