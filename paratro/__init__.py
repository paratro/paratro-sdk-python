"""Paratro MPC Wallet SDK for Python."""

from paratro.client import MPCClient
from paratro.config import Config
from paratro.errors import APIError, is_auth_error, is_not_found, is_rate_limited
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
    Transaction,
    TransferResponse,
    SecurityFactorItem,
    Wallet,
    WebhookEvent,
    WebhookEventType,
)
from paratro.webhook import verify_signature, parse_event
from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("paratro-sdk")

__all__ = [
    "MPCClient",
    "Config",
    "APIError",
    "is_auth_error",
    "is_not_found",
    "is_rate_limited",
    "Account",
    "Asset",
    "CreateAccountRequest",
    "CreateAssetRequest",
    "CreateTransferRequest",
    "CreateWalletRequest",
    "ListAccountsRequest",
    "ListAssetsRequest",
    "ListTransactionsRequest",
    "ListWalletsRequest",
    "ListSecurityFactorResponse",
    "Transaction",
    "TransferResponse",
    "SecurityFactorItem",
    "Wallet",
    "WebhookEvent",
    "WebhookEventType",
    "verify_signature",
    "parse_event",
    "__version__",
]
