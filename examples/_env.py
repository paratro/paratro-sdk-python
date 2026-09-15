"""Shared bootstrap for the examples: credentials and base URL come from the environment.

    export PARATRO_API_KEY=...        # required
    export PARATRO_API_SECRET=...     # required
    export PARATRO_BASE_URL=...       # optional, default https://api-sandbox.paratro.com
"""

from __future__ import annotations

import os
import sys

from paratro import Config, MPCClient


def make_client() -> MPCClient:
    api_key = os.environ.get("PARATRO_API_KEY", "")
    api_secret = os.environ.get("PARATRO_API_SECRET", "")
    if not api_key or not api_secret:
        sys.exit("set PARATRO_API_KEY and PARATRO_API_SECRET")
    base_url = os.environ.get("PARATRO_BASE_URL", "")
    config = Config.custom(base_url) if base_url else Config.sandbox()
    return MPCClient(api_key, api_secret, config)


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)
