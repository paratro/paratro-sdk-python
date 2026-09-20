"""Client configuration."""

from __future__ import annotations

# Raised by ``MPCClient`` when ``Config.base_url`` is not usable. Same wording in the Go and Rust SDKs.
BASE_URL_ERROR = (
    "base URL must be an absolute http(s) URL, "
    "e.g. https://<gateway-host> (Paratro cloud or your private gateway)"
)


class Config:
    """Configuration for the MPC client.

    ``base_url`` is the gateway you were given. There is no default and no
    environment preset: the Paratro cloud endpoints and a private deployment
    are configured the same way::

        Config("https://<gateway-host>")

    A trailing slash is dropped. Building a ``Config`` never raises; the URL is
    validated when the :class:`~paratro.MPCClient` is created (it must start
    with ``http://`` or ``https://``), so a bad value fails there with
    :data:`BASE_URL_ERROR` instead of as a connection error on the first call.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = (base_url or "").rstrip("/")

    def __repr__(self) -> str:
        return f"Config(base_url={self.base_url!r})"


def validate_base_url(base_url: str) -> None:
    """Raise ``ValueError(BASE_URL_ERROR)`` unless ``base_url`` is an absolute http(s) URL."""
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise ValueError(BASE_URL_ERROR)
