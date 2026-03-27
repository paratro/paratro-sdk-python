"""Error types for the SDK."""

from __future__ import annotations


class APIError(Exception):
    """Error returned by the Paratro API."""

    def __init__(self, http_status: int, code: str, error_type: str, message: str) -> None:
        self.http_status = http_status
        self.code = code
        self.error_type = error_type
        self.message = message
        super().__init__(f"[{http_status}] {code}: {message}")


def is_not_found(err: BaseException) -> bool:
    """Check if the error is a 404 Not Found."""
    return isinstance(err, APIError) and err.http_status == 404


def is_rate_limited(err: BaseException) -> bool:
    """Check if the error is a 429 Rate Limited."""
    return isinstance(err, APIError) and err.http_status == 429


def is_auth_error(err: BaseException) -> bool:
    """Check if the error is a 401 or 403 auth error."""
    return isinstance(err, APIError) and err.http_status in (401, 403)
