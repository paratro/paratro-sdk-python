"""Shared bootstrap for the examples: credentials and base URL come from the environment.

    export PARATRO_API_KEY=...        # required
    export PARATRO_API_SECRET=...     # required
    export PARATRO_BASE_URL=...       # required: https://<gateway-host> (Paratro cloud or your private gateway)
"""

from __future__ import annotations

import os
import sys

from paratro import Config, MPCClient


def make_client() -> MPCClient:
    api_key = os.environ.get("PARATRO_API_KEY", "")
    api_secret = os.environ.get("PARATRO_API_SECRET", "")
    base_url = os.environ.get("PARATRO_BASE_URL", "")
    if not api_key or not api_secret or not base_url:
        sys.exit("set PARATRO_API_KEY, PARATRO_API_SECRET and PARATRO_BASE_URL (https://<gateway-host>)")
    return MPCClient(api_key, api_secret, Config(base_url))


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)
