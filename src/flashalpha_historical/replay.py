"""Backtesting helpers — point-in-time replay loops over the Historical API.

These are thin orchestration utilities that turn a single endpoint into an
iterator over a date / minute range, with leak-free guarantees:

- ``iter_minutes``  — generate ET wall-clock timestamps inside RTH (9:30-16:00)
- ``iter_days``     — generate session-close timestamps for trade days
- ``replay``        — call any client method across a date range, yielding
                      ``(at, response)`` tuples
- ``Backtester``    — convenience wrapper that runs a strategy callback against
                      ``stock_summary`` / ``exposure_summary`` / any endpoint,
                      collecting results and skipping known gap days.

Calendar handling is deliberately simple: NYSE trading days = weekdays minus
US market holidays. That's good enough for SPY backtests covering 2018+ — the
Historical API itself returns ``no_data`` on holidays, and ``Backtester``
tolerates that by default. If you need a more rigorous calendar (early
closes, exchange holidays for non-US listings), pass your own ``trade_days``
iterable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from .client import AtLike, FlashAlphaHistorical, _format_at
from .exceptions import (
    FlashAlphaHistoricalError,
    InsufficientDataError,
    NoDataError,
    SymbolNotFoundError,
)

# US market holidays (subset that always closes the full session). Pulled
# from NYSE-published calendars, 2018-2026. Early-close days (1pm) are NOT in
# this list — the API returns minute-level data for them up to the actual
# close, so they don't need to be skipped.
_FULL_CLOSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2018
        date(2018, 1, 1), date(2018, 1, 15), date(2018, 2, 19), date(2018, 3, 30),
        date(2018, 5, 28), date(2018, 7, 4), date(2018, 9, 3), date(2018, 11, 22),
        date(2018, 12, 5), date(2018, 12, 25),
        # 2019
        date(2019, 1, 1), date(2019, 1, 21), date(2019, 2, 18), date(2019, 4, 19),
        date(2019, 5, 27), date(2019, 7, 4), date(2019, 9, 2), date(2019, 11, 28),
        date(2019, 12, 25),
        # 2020
        date(2020, 1, 1), date(2020, 1, 20), date(2020, 2, 17), date(2020, 4, 10),
        date(2020, 5, 25), date(2020, 7, 3), date(2020, 9, 7), date(2020, 11, 26),
        date(2020, 12, 25),
        # 2021
        date(2021, 1, 1), date(2021, 1, 18), date(2021, 2, 15), date(2021, 4, 2),
        date(2021, 5, 31), date(2021, 7, 5), date(2021, 9, 6), date(2021, 11, 25),
        date(2021, 12, 24),
        # 2022
        date(2022, 1, 17), date(2022, 2, 21), date(2022, 4, 15), date(2022, 5, 30),
        date(2022, 6, 20), date(2022, 7, 4), date(2022, 9, 5), date(2022, 11, 24),
        date(2022, 12, 26),
        # 2023
        date(2023, 1, 2), date(2023, 1, 16), date(2023, 2, 20), date(2023, 4, 7),
        date(2023, 5, 29), date(2023, 6, 19), date(2023, 7, 4), date(2023, 9, 4),
        date(2023, 11, 23), date(2023, 12, 25),
        # 2024
        date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 3, 29),
        date(2024, 5, 27), date(2024, 6, 19), date(2024, 7, 4), date(2024, 9, 2),
        date(2024, 11, 28), date(2024, 12, 25),
        # 2025
        date(2025, 1, 1), date(2025, 1, 9), date(2025, 1, 20), date(2025, 2, 17),
        date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4),
        date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25),
        # 2026
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
        date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
        date(2026, 11, 26), date(2026, 12, 25),
    }
)


def _coerce_date(d: str | date | datetime) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return datetime.strptime(d, "%Y-%m-%d").date()


def is_trading_day(d: date) -> bool:
    """Best-effort NYSE trading-day check: weekday and not a known holiday."""
    if d.weekday() >= 5:
        return False
    return d not in _FULL_CLOSE_HOLIDAYS


def iter_days(
    start: str | date,
    end: str | date,
    *,
    close_time: time = time(16, 0),
    trade_days: Iterable[date] | None = None,
) -> Iterator[datetime]:
    """Yield one datetime per trading day in ``[start, end]`` inclusive,
    stamped at ``close_time`` (default 16:00 ET — same as passing ``date`` to
    the API).

    Pass ``trade_days`` to override the default holiday calendar.
    """
    s, e = _coerce_date(start), _coerce_date(end)
    if trade_days is not None:
        days = sorted({d for d in (_coerce_date(x) for x in trade_days) if s <= d <= e})
    else:
        days = []
        d = s
        while d <= e:
            if is_trading_day(d):
                days.append(d)
            d += timedelta(days=1)
    for d in days:
        yield datetime.combine(d, close_time)


def iter_minutes(
    start: str | date,
    end: str | date,
    *,
    open_time: time = time(9, 30),
    close_time: time = time(16, 0),
    step_minutes: int = 1,
    trade_days: Iterable[date] | None = None,
) -> Iterator[datetime]:
    """Yield ET wall-clock minute timestamps inside RTH for every trading day
    in ``[start, end]``.

    Default cadence is 1 minute. Use ``step_minutes=5`` (or 15, 30) for coarser
    backtests — Historical API quota is shared with live, so spamming 390 calls
    per day per analytic burns through it fast.
    """
    if step_minutes <= 0:
        raise ValueError("step_minutes must be positive")
    for day_close in iter_days(start, end, close_time=close_time, trade_days=trade_days):
        d = day_close.date()
        cur = datetime.combine(d, open_time)
        end_of_session = datetime.combine(d, close_time)
        while cur <= end_of_session:
            yield cur
            cur += timedelta(minutes=step_minutes)


# Endpoint method names that take an ``at`` parameter — used by ``replay``.
_AT_METHODS: frozenset[str] = frozenset(
    {
        "stock_quote",
        "option_quote",
        "surface",
        "gex",
        "dex",
        "vex",
        "chex",
        "exposure_summary",
        "exposure_levels",
        "narrative",
        "zero_dte",
        "max_pain",
        "stock_summary",
        "volatility",
        "adv_volatility",
        "vrp",
    }
)


def replay(
    client: FlashAlphaHistorical,
    method: str,
    symbol: str,
    timestamps: Iterable[AtLike],
    *,
    skip_missing: bool = True,
    on_error: Callable[[datetime | str | date, Exception], None] | None = None,
    **kwargs: Any,
) -> Iterator[tuple[str, Any]]:
    """Replay a single endpoint across an iterable of timestamps.

    Parameters
    ----------
    client : FlashAlphaHistorical
        The client instance.
    method : str
        Name of the client method to call (e.g. ``"exposure_summary"``,
        ``"stock_summary"``, ``"vrp"``). Must accept an ``at=`` keyword.
    symbol : str
        Underlying symbol passed as the first positional arg to ``method``.
    timestamps : iterable of (str | datetime | date)
        Each value is fed to the method as ``at=...``. Use ``iter_days`` /
        ``iter_minutes`` to generate them.
    skip_missing : bool, default True
        If True, ``NoDataError``, ``SymbolNotFoundError``, and
        ``InsufficientDataError`` (the three "this minute / day has no usable
        data" failures) are silently skipped — common across known coverage
        gaps, holidays, and pre-2022 0DTE-less days. Other errors still
        raise.
    on_error : callable, optional
        Hook ``(at, exception) -> None`` invoked when ``skip_missing`` swallows
        an error. Useful for logging gaps without aborting the loop.
    **kwargs
        Forwarded to the endpoint method (``expiration``, ``min_oi``,
        ``strike_range``, ``expiry``, ``strike``, ``type``).

    Yields
    ------
    (at_str, response) tuples — ``at_str`` is the formatted ET wall-clock
    string (so it round-trips into JSON / DataFrames cleanly).

    Examples
    --------
    >>> from flashalpha_historical import FlashAlphaHistorical
    >>> from flashalpha_historical.replay import replay, iter_days
    >>> hx = FlashAlphaHistorical("YOUR_API_KEY")
    >>> for at, snap in replay(hx, "exposure_summary", "SPY",
    ...                        iter_days("2024-01-02", "2024-01-31")):
    ...     print(at, snap["regime"], snap["exposures"]["net_gex"])
    """
    if method not in _AT_METHODS:
        raise ValueError(
            f"replay() expects a method that takes `at`. Got {method!r}. "
            f"Allowed: {sorted(_AT_METHODS)}"
        )

    fn = getattr(client, method)
    skip_excs: tuple[type[Exception], ...] = (
        NoDataError,
        SymbolNotFoundError,
        InsufficientDataError,
    )

    for ts in timestamps:
        at_str = _format_at(ts)
        try:
            yield at_str, fn(symbol, at=ts, **kwargs)
        except skip_excs as exc:
            if not skip_missing:
                raise
            if on_error is not None:
                on_error(ts, exc)
            continue


# ── Backtester ──────────────────────────────────────────────────────────────


@dataclass
class BacktestResult:
    """One step of a backtest run.

    Holds the timestamp, the API snapshot the strategy saw, and whatever the
    strategy callback returned (typically a dict — signal, position size, P&L).
    """

    at: str
    snapshot: Any
    output: Any = None


@dataclass
class Backtester:
    """Run a strategy callback against the historical API across a date range.

    The pattern is intentionally minimal — pull a snapshot from one endpoint
    each step, feed it to your callback, collect the output. No order-routing,
    no fill simulation, no portfolio accounting: that's strategy-specific and
    belongs in your code, not the SDK.

    Parameters
    ----------
    client : FlashAlphaHistorical
    method : str, default ``"stock_summary"``
        Endpoint to pull each step.
    symbol : str, default ``"SPY"``
    skip_missing : bool, default True
        Silently skip days/minutes with no data.
    method_kwargs : dict, optional
        Forwarded to the endpoint method on every call.

    Examples
    --------
    >>> def vrp_harvester(at, snap):
    ...     vrp = snap["volatility"]["vrp"]
    ...     return {"signal": "short_strangle" if vrp > 5 else None}
    >>> bt = Backtester(hx, method="stock_summary")
    >>> results = bt.run(iter_days("2024-01-02", "2024-01-31"), vrp_harvester)
    >>> short_days = sum(1 for r in results if r.output["signal"])
    """

    client: FlashAlphaHistorical
    method: str = "stock_summary"
    symbol: str = "SPY"
    skip_missing: bool = True
    method_kwargs: dict[str, Any] = field(default_factory=dict)

    def run(
        self,
        timestamps: Iterable[AtLike],
        strategy: Callable[[str, Any], Any],
        *,
        on_error: Callable[[AtLike, Exception], None] | None = None,
    ) -> list[BacktestResult]:
        """Iterate ``timestamps``, call the endpoint, pass each snapshot to
        ``strategy(at, snapshot)``, and collect the results.

        ``strategy`` is called once per snapshot. Whatever it returns is stored
        in ``BacktestResult.output``. Exceptions raised inside ``strategy``
        propagate (treat strategy errors as bugs, not data gaps).
        """
        results: list[BacktestResult] = []
        for at_str, snap in replay(
            self.client,
            self.method,
            self.symbol,
            timestamps,
            skip_missing=self.skip_missing,
            on_error=on_error,
            **self.method_kwargs,
        ):
            output = strategy(at_str, snap)
            results.append(BacktestResult(at=at_str, snapshot=snap, output=output))
        return results

    def to_records(self, results: list[BacktestResult]) -> list[dict[str, Any]]:
        """Flatten ``BacktestResult`` list to plain dicts — ready for
        ``pandas.DataFrame.from_records``. Pulls a few common analytic fields
        out of the snapshot for convenience and merges in whatever
        ``strategy.output`` was (assuming it's a dict).
        """
        rows: list[dict[str, Any]] = []
        for r in results:
            row: dict[str, Any] = {"at": r.at}
            snap = r.snapshot if isinstance(r.snapshot, dict) else {}
            # Best-effort field extraction — covers stock_summary / exposure_summary / vrp.
            if "underlying_price" in snap:
                row["underlying_price"] = snap["underlying_price"]
            elif "price" in snap and isinstance(snap["price"], dict):
                row["underlying_price"] = snap["price"].get("mid")
            if "regime" in snap:
                row["regime"] = snap["regime"] if isinstance(snap["regime"], str) else None
            if "gamma_flip" in snap:
                row["gamma_flip"] = snap["gamma_flip"]
            if "exposures" in snap and isinstance(snap["exposures"], dict):
                row["net_gex"] = snap["exposures"].get("net_gex")
                row["net_dex"] = snap["exposures"].get("net_dex")
            if "vrp" in snap and isinstance(snap["vrp"], dict):
                row["vrp_20d"] = snap["vrp"].get("vrp_20d")
                row["vrp_z"] = snap["vrp"].get("z_score")

            if isinstance(r.output, dict):
                for k, v in r.output.items():
                    if k not in row:
                        row[k] = v
            else:
                row["output"] = r.output
            rows.append(row)
        return rows
