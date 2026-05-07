"""FlashAlpha Historical API client.

Point-in-time replay of every live analytics endpoint. Every analytics method
takes a required ``at`` parameter — the as-of timestamp returned data should
reflect — and returns the same response shape as the live API.

Base URL: ``https://historical.flashalpha.com``
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import requests

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

if TYPE_CHECKING:
    from .types import (
        ExposureLevelsResponse,
        ExposureSummaryResponse,
        MaxPainResponse,
        NarrativeResponse,
        StockSummaryResponse,
        VrpResponse,
    )

BASE_URL = "https://historical.flashalpha.com"

AtLike = str | datetime | date


def _seg(s: str) -> str:
    """URL-escape a single path segment."""
    return quote(s, safe="")


def _format_at(at: AtLike) -> str:
    """Coerce ``at`` to the ET wall-clock string the API expects.

    Accepts:
        - ``"2026-03-05T15:30:00"`` — minute-level
        - ``"2026-03-05"``          — defaults to 16:00 ET (session close)
        - ``datetime``              — formatted as ``yyyy-MM-ddTHH:mm:ss``
        - ``date``                  — formatted as ``yyyy-MM-dd``
    """
    if isinstance(at, str):
        return at
    if isinstance(at, datetime):
        return at.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(at, date):
        return at.strftime("%Y-%m-%d")
    raise TypeError(f"`at` must be str, datetime, or date — got {type(at).__name__}")


class FlashAlphaHistorical:
    """Thin wrapper around the FlashAlpha Historical REST API.

    Every analytics method takes an ``at`` parameter (string, ``datetime``, or
    ``date``) and returns the same response shape as the live API at that
    moment in history.

    Parameters
    ----------
    api_key : str
        Your FlashAlpha API key from https://flashalpha.com — the same key you
        use for the live API.
    base_url : str, optional
        Override the API base URL (for testing).
    timeout : float, optional
        Request timeout in seconds. Default 60 — adv_volatility / stock_summary
        cold hits can take ~500-1500 ms; pick higher than the live SDK.

    Examples
    --------
    >>> from flashalpha_historical import FlashAlphaHistorical
    >>> hx = FlashAlphaHistorical("YOUR_API_KEY")
    >>> hx.exposure_summary("SPY", at="2020-03-16T15:30:00")
    {'symbol': 'SPY', 'underlying_price': 246.01, 'regime': 'negative_gamma', ...}
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 60,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["X-Api-Key"] = api_key

    # ── internal ────────────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, params=params, timeout=self.timeout)
        return self._handle(resp)

    def _handle(self, resp: requests.Response) -> Any:
        if resp.status_code == 200:
            return resp.json()

        try:
            body = resp.json()
        except ValueError:
            body = {"detail": resp.text}

        err_code = body.get("error") if isinstance(body, dict) else None
        msg = (
            body.get("message") if isinstance(body, dict) else None
        ) or (body.get("detail") if isinstance(body, dict) else None) or resp.text

        if resp.status_code == 400:
            if err_code == "invalid_at":
                raise InvalidAtError(msg, status_code=400, response=body)
            raise FlashAlphaHistoricalError(msg, status_code=400, response=body)

        if resp.status_code == 401:
            raise AuthenticationError(msg, status_code=401, response=body)

        if resp.status_code == 403:
            raise TierRestrictedError(
                msg,
                status_code=403,
                response=body,
                current_plan=body.get("current_plan") if isinstance(body, dict) else None,
                required_plan=body.get("required_plan") if isinstance(body, dict) else None,
            )

        if resp.status_code == 404:
            if err_code == "no_coverage":
                raise NoCoverageError(msg, status_code=404, response=body)
            if err_code == "symbol_not_found":
                raise SymbolNotFoundError(msg, status_code=404, response=body)
            if err_code == "insufficient_data":
                raise InsufficientDataError(msg, status_code=404, response=body)
            if err_code == "no_data":
                raise NoDataError(msg, status_code=404, response=body)
            # Some optionquote 404s ship a bare {"error": "<text>"} — surface as NoDataError.
            raise NoDataError(msg, status_code=404, response=body)

        if resp.status_code == 429:
            raise RateLimitError(
                msg,
                status_code=429,
                response=body,
                retry_after=int(resp.headers.get("Retry-After", 0)) or None,
            )

        if resp.status_code >= 500:
            raise ServerError(msg, status_code=resp.status_code, response=body)

        raise FlashAlphaHistoricalError(msg, status_code=resp.status_code, response=body)

    # ── Coverage & Support ──────────────────────────────────────────

    def tickers(self, *, symbol: str | None = None) -> dict:
        """List symbols with historical coverage.

        Without ``symbol``: returns the full coverage table — every covered
        symbol with its date range, healthy-day count, and gap breakdown.

        With ``symbol``: returns a single coverage object for that symbol.
        Raises ``NoCoverageError`` if the symbol is not in the historical
        dataset.
        """
        params = {"symbol": symbol} if symbol else None
        return self._get("/v1/tickers", params)

    # ── Market Data ─────────────────────────────────────────────────

    def stock_quote(self, ticker: str, *, at: AtLike) -> dict:
        """Stock bid/ask/mid/last at the requested minute."""
        return self._get(f"/v1/stockquote/{_seg(ticker)}", {"at": _format_at(at)})

    def option_quote(
        self,
        ticker: str,
        *,
        at: AtLike,
        expiry: str | None = None,
        strike: float | None = None,
        type: str | None = None,
    ) -> dict | list:
        """Option quote(s) + greeks + OI at the requested minute.

        With all three filters → single object. Otherwise → array.

        Notes
        -----
        Known gaps from the live endpoint:

        - ``bidSize`` / ``askSize`` are always ``0`` — minute table has no sizes
        - ``volume`` is always ``0`` — same reason
        - ``svi_vol`` is always ``null`` (``svi_vol_gated: "backtest_mode"``)
        """
        params: dict[str, Any] = {"at": _format_at(at)}
        if expiry:
            params["expiry"] = expiry
        if strike is not None:
            params["strike"] = strike
        if type:
            params["type"] = type
        return self._get(f"/v1/optionquote/{_seg(ticker)}", params)

    def surface(self, symbol: str, *, at: AtLike) -> dict:
        """50×50 implied-vol surface grid (tenor × log-moneyness).

        Raises ``InsufficientDataError`` for historical dates with too few
        OTM+liquid contracts to fill the grid.
        """
        return self._get(f"/v1/surface/{_seg(symbol)}", {"at": _format_at(at)})

    # ── Exposure Analytics ──────────────────────────────────────────

    def gex(
        self,
        symbol: str,
        *,
        at: AtLike,
        expiration: str | None = None,
        min_oi: int | None = None,
    ) -> dict:
        """Gamma exposure by strike.

        Notes
        -----
        ``call_volume`` / ``put_volume`` always ``0``; ``call_oi_change`` /
        ``put_oi_change`` always ``null`` — no prior-day OI join yet.
        """
        params: dict[str, Any] = {"at": _format_at(at)}
        if expiration:
            params["expiration"] = expiration
        if min_oi is not None:
            params["min_oi"] = min_oi
        return self._get(f"/v1/exposure/gex/{_seg(symbol)}", params)

    def dex(self, symbol: str, *, at: AtLike, expiration: str | None = None) -> dict:
        """Delta exposure by strike."""
        params: dict[str, Any] = {"at": _format_at(at)}
        if expiration:
            params["expiration"] = expiration
        return self._get(f"/v1/exposure/dex/{_seg(symbol)}", params)

    def vex(self, symbol: str, *, at: AtLike, expiration: str | None = None) -> dict:
        """Vanna exposure by strike."""
        params: dict[str, Any] = {"at": _format_at(at)}
        if expiration:
            params["expiration"] = expiration
        return self._get(f"/v1/exposure/vex/{_seg(symbol)}", params)

    def chex(self, symbol: str, *, at: AtLike, expiration: str | None = None) -> dict:
        """Charm exposure by strike."""
        params: dict[str, Any] = {"at": _format_at(at)}
        if expiration:
            params["expiration"] = expiration
        return self._get(f"/v1/exposure/chex/{_seg(symbol)}", params)

    def exposure_summary(self, symbol: str, *, at: AtLike) -> ExposureSummaryResponse:
        """Full composite dashboard — net GEX/DEX/VEX/CHEX, gamma flip, regime,
        ±1% hedging estimates, 0DTE contribution, interpretations."""
        return self._get(
            f"/v1/exposure/summary/{_seg(symbol)}", {"at": _format_at(at)}
        )

    def exposure_levels(self, symbol: str, *, at: AtLike) -> ExposureLevelsResponse:
        """Key technical levels — gamma flip, call/put walls, max +/- gamma,
        highest-OI strike, 0DTE magnet."""
        return self._get(
            f"/v1/exposure/levels/{_seg(symbol)}", {"at": _format_at(at)}
        )

    def narrative(self, symbol: str, *, at: AtLike) -> NarrativeResponse:
        """Verbal analysis + prior-day GEX comparison + VIX context.

        ``gex_change`` pulls the previous trading day's net GEX; ``vix`` is
        the closing value for the trading day of ``at``.

        Notes
        -----
        ``narrative.data.top_oi_changes`` is always an empty array on
        historical responses — prior-day per-strike OI diffs aren't yet
        available for replay.
        """
        return self._get(
            f"/v1/exposure/narrative/{_seg(symbol)}", {"at": _format_at(at)}
        )

    def zero_dte(
        self,
        symbol: str,
        *,
        at: AtLike,
        strike_range: float | None = None,
    ) -> dict:
        """0DTE-specific analytics — regime, expected move, pin risk, hedging,
        decay, flow, levels, strikes.

        ``time_to_close_hours`` is computed from ``at`` against 16:00 ET on the
        same day.

        Notes
        -----
        Intraday 0DTE greeks (delta/gamma/theta/iv) often arrive as ``0`` /
        ``null`` for very-near-expiry contracts at minute resolution. The
        chain is still listed for OI / strike-distribution analysis, but
        exposure totals collapse to zero.
        """
        params: dict[str, Any] = {"at": _format_at(at)}
        if strike_range is not None:
            params["strike_range"] = strike_range
        return self._get(f"/v1/exposure/zero-dte/{_seg(symbol)}", params)

    # ── Max Pain ────────────────────────────────────────────────────

    def max_pain(
        self,
        symbol: str,
        *,
        at: AtLike,
        expiration: str | None = None,
    ) -> MaxPainResponse:
        """Strike-by-strike pain curve, pin probability, dealer alignment."""
        params: dict[str, Any] = {"at": _format_at(at)}
        if expiration:
            params["expiration"] = expiration
        return self._get(f"/v1/maxpain/{_seg(symbol)}", params)

    # ── Stock Summary (Composite) ───────────────────────────────────

    def stock_summary(self, symbol: str, *, at: AtLike) -> StockSummaryResponse:
        """Full composite snapshot — price, vol (ATM IV, HV20, HV60, VRP, 25d
        skew, IV term), options flow, exposure block, macro context.

        Notes
        -----
        Known gaps from live:

        - ``options_flow.total_call_volume`` / ``total_put_volume`` /
          ``pc_ratio_volume`` — always ``0`` / ``null`` (no minute volume)
        - ``macro.vix_futures`` — always ``null`` (CME futures not historically
          reconstructible)
        - ``macro.fear_and_greed`` — always ``null`` (CNN index not archived)
        """
        return self._get(
            f"/v1/stock/{_seg(symbol)}/summary", {"at": _format_at(at)}
        )

    # ── Volatility Analytics ────────────────────────────────────────

    def volatility(self, symbol: str, *, at: AtLike) -> dict:
        """Comprehensive vol analysis — realized vol ladder (5/10/20/30/60d),
        IV-RV spreads, skew profiles, term structure, IV dispersion, GEX/theta
        by DTE bucket, put/call profile, OI concentration, multi-move
        hedging."""
        return self._get(f"/v1/volatility/{_seg(symbol)}", {"at": _format_at(at)})

    def adv_volatility(self, symbol: str, *, at: AtLike) -> dict:
        """Advanced volatility — SVI parameters, forward prices, total variance
        surface, arbitrage flags, variance swap fair values, greek surfaces
        (vanna, charm, volga, speed)."""
        return self._get(
            f"/v1/adv_volatility/{_seg(symbol)}", {"at": _format_at(at)}
        )

    # ── VRP ─────────────────────────────────────────────────────────

    def vrp(self, symbol: str, *, at: AtLike) -> VrpResponse:
        """Volatility Risk Premium dashboard.

        Percentile history is **date-bounded** — VRP percentile and z-score
        are computed from snapshots dated strictly before ``at``, so at any
        historical point the percentile reflects what was knowable at that
        moment (no future leakage).

        Notes
        -----
        ``macro.hy_spread`` is currently a fixed ``3.5`` on historical
        responses — the high-yield spread isn't yet served by the historical
        macro feed.
        """
        return self._get(f"/v1/vrp/{_seg(symbol)}", {"at": _format_at(at)})
