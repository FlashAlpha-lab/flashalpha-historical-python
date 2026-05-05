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

    regime: Optional[str]
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

    gamma: Optional[str]
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
