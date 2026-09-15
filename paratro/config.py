"""Client configuration."""

from __future__ import annotations

_SANDBOX_URL = "https://api-sandbox.paratro.com"
_PRODUCTION_URL = "https://api.paratro.com"


class Config:
    """Configuration for the MPC client."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @classmethod
    def sandbox(cls) -> Config:
        """Sandbox environment."""
        return cls(_SANDBOX_URL)

    @classmethod
    def production(cls) -> Config:
        """Production environment."""
        return cls(_PRODUCTION_URL)

    @classmethod
    def custom(cls, base_url: str) -> Config:
        """Custom base URL."""
        return cls(base_url)
