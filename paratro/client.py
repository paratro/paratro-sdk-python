"""Paratro MPC Wallet SDK client."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Type, TypeVar

import requests

from paratro.config import Config
from paratro.errors import APIError
from paratro.models import (
    Account,
    Asset,
    CreateAccountRequest,
    CreateAssetRequest,
    CreateTransferRequest,
    CreateWalletRequest,
    ListAccountsRequest,
    ListAssetsRequest,
    ListTransactionsRequest,
    ListWalletsRequest,
    ListSecurityFactorResponse,
    PaginatedResponse,
    Transaction,
    TransferResponse,
    SecurityFactorItem,
    Wallet,
)
from importlib.metadata import version as _pkg_version

VERSION = _pkg_version("paratro-sdk")

T = TypeVar("T")

_TOKEN_REFRESH_BUFFER = 120  # Refresh 2 minutes before expiration
_HTTP_TIMEOUT = 30


class MPCClient:
    """Client for the Paratro MPC Wallet API.

    Usage::

        from paratro import MPCClient, Config

        client = MPCClient("api_key", "api_secret", Config.sandbox())

        # Create a wallet
        wallet = client.create_wallet(CreateWalletRequest(wallet_name="My Wallet"))

    """

    def __init__(self, api_key: str, api_secret: str, config: Config) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not api_secret:
            raise ValueError("api_secret is required")
        if config is None:
            raise ValueError("config is required")

        self._config = config
        self._api_key = api_key
        self._api_secret = api_secret
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": f"paratro-sdk-python/{VERSION}",
            "Content-Type": "application/json",
        })

        # Token management
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._token_lock = threading.Lock()

    # ── Authentication ──

    def _ensure_token(self) -> str:
        """Get a valid JWT token, refreshing if necessary."""
        with self._token_lock:
            if self._token and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER:
                return self._token

            resp = self._session.post(
                f"{self._config.base_url}/api/v1/auth/token",
                headers={"X-API-Key": self._api_key, "X-API-Secret": self._api_secret},
                timeout=_HTTP_TIMEOUT,
            )
            self._raise_for_error(resp)
            data = resp.json()
            self._token = data["token"]
            self._token_expires_at = time.time() + data.get("expires_in", 900)
            return self._token  # type: ignore[return-value]

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

    # ── Transaction ──

    def get_transaction(self, tx_id: str) -> Transaction:
        """Get a transaction by ID."""
        data = self._request("GET", f"/api/v1/transactions/{tx_id}")
        return _from_dict(Transaction, data)

    def list_transactions(self, req: Optional[ListTransactionsRequest] = None) -> PaginatedResponse[Transaction]:
        """List transactions with pagination."""
        params: Dict[str, str] = {}
        if req:
            if req.wallet_id:
                params["wallet_id"] = req.wallet_id
            if req.account_id:
                params["account_id"] = req.account_id
            if req.chain:
                params["chain"] = req.chain
            params.update(_pagination_params(req.page, req.page_size))
        data = self._request("GET", "/api/v1/transactions", params=params)
        return _paginated(Transaction, data)

    # ── Transfer ──

    def create_transfer(self, req: CreateTransferRequest) -> TransferResponse:
        """Create a new transfer."""
        data = self._request("POST", "/api/v1/transfer", body=_to_body(req))
        return _from_dict(TransferResponse, data)

    # ── Security Factors ──

    def list_security_factors(self, chain: Optional[str] = None) -> ListSecurityFactorResponse:
        """List security factors.

        Args:
            chain: Optional chain filter (e.g. "ETH", "BTC").

        Returns:
            ListSecurityFactorResponse with items and total count.
        """
        params: Dict[str, str] = {}
        if chain:
            params["chain"] = chain
        data = self._request("GET", "/api/v1/client/security-factors", params=params)
        items = [_from_dict(SecurityFactorItem, item) for item in data.get("items", [])]
        return ListSecurityFactorResponse(items=items, total=data.get("total", 0))

    def add_security_factor(
        self,
        chain: str,
        address: str,
        mfa_code: str,
        label: str = "",
    ) -> SecurityFactorItem:
        """Add a security factor.

        Args:
            chain: Blockchain network (e.g. "ETH", "BTC").
            address: The address to add.
            mfa_code: MFA / 2FA verification code.
            label: Optional human-readable label.

        Returns:
            The created SecurityFactorItem.
        """
        body: Dict[str, Any] = {"chain": chain, "address": address, "mfa_code": mfa_code}
        if label:
            body["label"] = label
        data = self._request("POST", "/api/v1/client/security-factors", body=body)
        return _from_dict(SecurityFactorItem, data)

    def delete_security_factor(self, factor_id: str, mfa_code: str) -> None:
        """Remove a security factor.

        Args:
            factor_id: ID of the security factor to remove.
            mfa_code: MFA / 2FA verification code.
        """
        self._request(
            "DELETE",
            f"/api/v1/client/security-factors/{factor_id}",
            body={"mfa_code": mfa_code},
        )

    def set_security_factor_status(self, factor_id: str, status: str, mfa_code: str) -> SecurityFactorItem:
        """Update the status of a security factor.

        Args:
            factor_id: ID of the security factor.
            status: New status value.
            mfa_code: MFA / 2FA verification code.

        Returns:
            The updated SecurityFactorItem.
        """
        body: Dict[str, Any] = {"status": status, "mfa_code": mfa_code}
        data = self._request("PUT", f"/api/v1/client/security-factors/{factor_id}/status", body=body)
        return _from_dict(SecurityFactorItem, data)

    # ── Internal ──

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> Any:
        token = self._ensure_token()
        url = f"{self._config.base_url}{path}"
        resp = self._session.request(
            method,
            url,
            json=body,
            params=params or None,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HTTP_TIMEOUT,
        )
        self._raise_for_error(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    @staticmethod
    def _raise_for_error(resp: requests.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            data = resp.json()
            raise APIError(
                http_status=resp.status_code,
                code=data.get("code", "unknown"),
                error_type=data.get("type", "unknown"),
                message=data.get("message", resp.text),
            )
        except (ValueError, KeyError):
            raise APIError(
                http_status=resp.status_code,
                code="unknown",
                error_type="unknown",
                message=resp.text,
            )


# ── Helpers ──


def _to_body(obj: Any) -> Dict[str, Any]:
    """Convert a dataclass to a JSON-serializable dict, omitting empty/None values."""
    raw = asdict(obj)
    return {k: v for k, v in raw.items() if v is not None and v != "" and v != 0}


def _from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
    """Create a dataclass instance from a dict, ignoring unknown keys."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in data.items() if k in fields}
    return cls(**filtered)  # type: ignore[call-arg]


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
