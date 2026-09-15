"""Paratro MPC Wallet SDK client."""

from __future__ import annotations

import dataclasses
import threading
import time
from typing import Any, Dict, Optional, Tuple, Type, TypeVar

import requests

from paratro.config import Config
from paratro.errors import APIError, ErrorCode
from paratro.models import (
    Account,
    Asset,
    CreateAccountRequest,
    CreateAssetRequest,
    CreateTransactionResponse,
    CreateWalletRequest,
    ListAccountsRequest,
    ListAssetsRequest,
    ListTransactionsRequest,
    ListWalletsRequest,
    PaginatedResponse,
    Transaction,
    TransferRequest,
    Wallet,
)
from paratro.transactions import TransactionsService
from paratro.x402 import X402Service
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    VERSION = _pkg_version("paratro-sdk")
except PackageNotFoundError:  # running from a source checkout that is not installed
    VERSION = "0.0.0"

T = TypeVar("T")

# Refresh this many seconds before ``expires_in`` runs out. The gateway sets
# ``expires_in`` from its own config (capped at 900 s in conf.GetJWTExpireSeconds);
# never hard-code the lifetime on the client side.
_TOKEN_REFRESH_BUFFER = 120
# Used only if the token response carries no ``expires_in``.
_DEFAULT_TOKEN_TTL = 900
# Default HTTP timeout in seconds (``MPCClient(..., timeout=...)``), applied to
# every exchange including ``POST /api/v1/auth/token``.
#
# PROGRAM_CALL / CONTRACT_CALL are synchronous: the gateway keeps the connection
# open while the signing engine signs and broadcasts. The gateway's own ceilings
# (develop, main.go / internal/client / internal/service):
#
#   engine budget                      120 s  (service.DefaultEngineTimeoutSeconds)
#   wait for the engine before a 202   150 s  (budget + SyncSettleClientMargin 30 s)
#   server WriteTimeout                180 s  (the connection is closed after this)
#
# The default sits above the WriteTimeout so the gateway, not the SDK, is the side
# that gives up: a slow engine then ends in a 202 with a ``tx_id``, and past 180 s
# the gateway closes the connection itself. A client-side timeout on that call
# has no ``tx_id`` while the row already exists under your ``reference_id`` (and
# ``GET /transactions`` cannot filter by ``reference_id``). 150 s would not do —
# it is exactly how long the gateway waits for the engine before answering 202,
# and the SDK's timer starts earlier than the gateway's. Same value as
# ``paratro.DefaultTimeout`` in the Go SDK and ``config::DEFAULT_TIMEOUT`` in Rust.
_HTTP_TIMEOUT = 200
DEFAULT_TIMEOUT = _HTTP_TIMEOUT


class MPCClient:
    """Client for the Paratro MPC Wallet API.

    Usage::

        from paratro import MPCClient, Config, TransferRequest

        client = MPCClient("api_key", "api_secret", Config.sandbox())

        result = client.transactions.create(TransferRequest(
            from_address="0xYourVault...",
            to_address="0xRecipient...",
            chain="ethereum",
            token_symbol="USDC",
            amount="10.5",
            reference_id="order-1001",
        ))

    Authentication is automatic: the first call exchanges the API key/secret for
    a JWT at ``POST /api/v1/auth/token``; the token is refreshed before
    ``expires_in`` runs out, and a ``401 token_expired`` answer triggers exactly
    one re-authentication and one retry of the failed request.

    ``timeout`` (seconds) bounds every HTTP exchange and defaults to
    ``DEFAULT_TIMEOUT`` (200). Do not lower it for a client that sends
    ``PROGRAM_CALL`` / ``CONTRACT_CALL`` — those calls are synchronous on the
    gateway side (it waits up to 150 s for the engine before answering 202 and
    closes the connection at its 180 s write timeout); shorter values are fine
    for a client that only reads or sends ``TRANSFER``.
    """

    def __init__(self, api_key: str, api_secret: str, config: Config, timeout: float = _HTTP_TIMEOUT) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not api_secret:
            raise ValueError("api_secret is required")
        if config is None:
            raise ValueError("config is required")

        self._config = config
        self._api_key = api_key
        self._api_secret = api_secret
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": f"paratro-sdk-python/{VERSION}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        # Token management
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._token_lock = threading.Lock()

        # Services
        self.transactions = TransactionsService(self)
        self.x402 = X402Service(self)

    # ── Authentication ──

    def _ensure_token(self, force: bool = False) -> str:
        """Get a valid JWT token, refreshing if necessary.

        ``POST /api/v1/auth/token`` with ``X-API-Key`` / ``X-API-Secret`` headers
        returns ``{"token", "expires_in", "token_type", "client": {...}}`` (no envelope).
        """
        with self._token_lock:
            if (
                not force
                and self._token
                and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER
            ):
                return self._token

            resp = self._session.post(
                f"{self._config.base_url}/api/v1/auth/token",
                headers={"X-API-Key": self._api_key, "X-API-Secret": self._api_secret},
                timeout=self._timeout,
                allow_redirects=False,
            )
            self._raise_for_error(resp)
            data = resp.json()
            token = str(data.get("token") or "")
            if not token:
                raise APIError(resp.status_code, "unknown", "unknown", "Token response has no token")
            self._token = token
            expires_in = data.get("expires_in") or _DEFAULT_TOKEN_TTL
            self._token_expires_at = time.time() + float(expires_in)
            return token

    # ── Wallet ──

    def create_wallet(self, req: CreateWalletRequest) -> Wallet:
        """Create a new MPC wallet."""
        data = self._request("POST", "/api/v1/wallets", body=_to_body(req))
        return _from_dict(Wallet, data)

    def get_wallet(self, wallet_id: str) -> Wallet:
        """Get a wallet by ID."""
        data = self._request("GET", f"/api/v1/wallets/{wallet_id}")
        return _from_dict(Wallet, data)

    def list_wallets(self, req: Optional[ListWalletsRequest] = None) -> PaginatedResponse[Wallet]:
        """List wallets with pagination."""
        params = _pagination_params(req.page if req else 0, req.page_size if req else 0)
        data = self._request("GET", "/api/v1/wallets", params=params)
        return _paginated(Wallet, data)

    # ── Account ──

    def create_account(self, req: CreateAccountRequest) -> Account:
        """Create a new blockchain account under a wallet."""
        data = self._request("POST", "/api/v1/accounts", body=_to_body(req))
        return _from_dict(Account, data)

    def get_account(self, account_id: str) -> Account:
        """Get an account by ID."""
        data = self._request("GET", f"/api/v1/accounts/{account_id}")
        return _from_dict(Account, data)

    def list_accounts(self, req: Optional[ListAccountsRequest] = None) -> PaginatedResponse[Account]:
        """List accounts with pagination."""
        params: Dict[str, str] = {}
        if req:
            if req.wallet_id:
                params["wallet_id"] = req.wallet_id
            params.update(_pagination_params(req.page, req.page_size))
        data = self._request("GET", "/api/v1/accounts", params=params)
        return _paginated(Account, data)

    # ── Asset ──

    def create_asset(self, req: CreateAssetRequest) -> Asset:
        """Add an asset (token) to an account."""
        data = self._request("POST", "/api/v1/assets", body=_to_body(req))
        return _from_dict(Asset, data)

    def get_asset(self, asset_id: str) -> Asset:
        """Get an asset by ID."""
        data = self._request("GET", f"/api/v1/assets/{asset_id}")
        return _from_dict(Asset, data)

    def list_assets(self, req: Optional[ListAssetsRequest] = None) -> PaginatedResponse[Asset]:
        """List assets with pagination."""
        params: Dict[str, str] = {}
        if req:
            if req.account_id:
                params["account_id"] = req.account_id
            params.update(_pagination_params(req.page, req.page_size))
        data = self._request("GET", "/api/v1/assets", params=params)
        return _paginated(Asset, data)

    # ── Transaction (pre-1.8 method names; delegate to client.transactions) ──

    def get_transaction(self, tx_id: str) -> Transaction:
        """Get a transaction by ID. Same as ``client.transactions.get``."""
        return self.transactions.get(tx_id)

    def list_transactions(self, req: Optional[ListTransactionsRequest] = None) -> PaginatedResponse[Transaction]:
        """List transactions with pagination. Same as ``client.transactions.list``."""
        return self.transactions.list(req)

    def create_transfer(self, req: TransferRequest) -> CreateTransactionResponse:
        """Create a transfer (pre-1.8 compatibility wrapper).

        ``POST /api/v1/transfer`` was retired by the gateway (HTTP 410). This
        method now sends ``POST /api/v1/transactions`` with ``operation=TRANSFER``
        — identical to ``client.transactions.create(TransferRequest(...))``.
        """
        if not isinstance(req, TransferRequest):
            raise TypeError("create_transfer expects a TransferRequest (alias CreateTransferRequest)")
        return self.transactions.create(req)

    # ── Internal ──

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        _, data = self._request_with_status(method, path, body=body, params=params, headers=headers)
        return data

    def _request_with_status(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Any]:
        """Send an authenticated request; return ``(http_status, parsed_json)``.

        A ``401 token_expired`` answer re-authenticates once and retries once.
        """
        url = f"{self._config.base_url}{path}"
        token = self._ensure_token()
        resp = self._send(method, url, token, body, params, headers)
        if resp.status_code == 401 and _error_code(resp) == ErrorCode.TOKEN_EXPIRED:
            token = self._ensure_token(force=True)
            resp = self._send(method, url, token, body, params, headers)
        self._raise_for_error(resp)
        if resp.status_code == 204 or not resp.content:
            return resp.status_code, {}
        return resp.status_code, resp.json()

    def _send(
        self,
        method: str,
        url: str,
        token: str,
        body: Optional[Dict[str, Any]],
        params: Optional[Dict[str, str]],
        headers: Optional[Dict[str, str]],
    ) -> requests.Response:
        request_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            request_headers.update(headers)
        return self._session.request(
            method,
            url,
            json=body,
            params=params or None,
            headers=request_headers,
            timeout=self._timeout,
            allow_redirects=False,
        )

    @staticmethod
    def _raise_for_error(resp: requests.Response) -> None:
        if resp.status_code < 300:
            return
        if 300 <= resp.status_code < 400:
            # Never follow a redirect with credentials or a signed body attached.
            raise APIError(
                resp.status_code, "unexpected_redirect", "client_error",
                "Unexpected redirect from the gateway; check Config.base_url",
            )
        body: Optional[Dict[str, Any]]
        try:
            parsed = resp.json()
            body = parsed if isinstance(parsed, dict) else None
        except ValueError:
            body = None
        raise APIError.from_response(resp.status_code, body, resp.text)


# ── Helpers ──


def _error_code(resp: requests.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return ""
    if isinstance(data, dict):
        return str(data.get("code", ""))
    return ""


def _to_body(obj: Any) -> Dict[str, Any]:
    """Convert a dataclass to a JSON-serializable dict, omitting empty/None values."""
    raw = dataclasses.asdict(obj)
    return {k: v for k, v in raw.items() if v is not None and v != "" and v != 0}


def _from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
    """Create a dataclass instance from a dict, ignoring unknown keys."""
    fields = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    filtered = {k: v for k, v in data.items() if k in fields}
    return cls(**filtered)


def _pagination_params(page: int, page_size: int) -> Dict[str, str]:
    params: Dict[str, str] = {}
    if page > 0:
        params["page"] = str(page)
    if page_size > 0:
        params["page_size"] = str(page_size)
    return params


def _paginated(cls: Type[T], data: Any) -> PaginatedResponse[T]:
    items = [_from_dict(cls, item) for item in data.get("data", [])]
    return PaginatedResponse(
        items=items,
        total=data.get("total", 0),
        has_more=data.get("has_more", False),
    )
