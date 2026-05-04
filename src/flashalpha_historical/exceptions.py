"""FlashAlpha Historical API exceptions."""

from __future__ import annotations


class FlashAlphaHistoricalError(Exception):
    """Base exception for the FlashAlpha Historical SDK."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response: dict | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AuthenticationError(FlashAlphaHistoricalError):
    """Raised when the API key is invalid or missing (401)."""


class TierRestrictedError(FlashAlphaHistoricalError):
    """Raised when the user's tier is below Alpha (403). Every Historical
    endpoint requires an Alpha plan or higher."""

    def __init__(
        self,
        message: str,
        current_plan: str | None = None,
        required_plan: str | None = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.current_plan = current_plan
        self.required_plan = required_plan


class InvalidAtError(FlashAlphaHistoricalError):
    """Raised when the ``at`` parameter is missing or has an invalid format (400)."""


class NoDataError(FlashAlphaHistoricalError):
    """Raised when a specific (symbol, at) tuple has no data — the timestamp
    falls outside the coverage window or inside a known gap (404)."""


class NoCoverageError(FlashAlphaHistoricalError):
    """Raised by ``/v1/tickers?symbol=`` for a symbol that is not in the
    historical dataset (404)."""


class SymbolNotFoundError(FlashAlphaHistoricalError):
    """Raised when the symbol has no historical data at the requested ``at`` (404)."""


class InsufficientDataError(FlashAlphaHistoricalError):
    """Raised when the surface grid can't be built (too few OTM+liquid
    contracts) (404)."""


class RateLimitError(FlashAlphaHistoricalError):
    """Raised when the daily quota is exhausted (429). Quota is shared with
    the live API."""

    def __init__(self, message: str, retry_after: int | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(FlashAlphaHistoricalError):
    """Raised on 5xx server errors."""
