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
    Transaction,
    TransferResponse,
    Wallet,
)
from paratro.version import VERSION

__version__ = VERSION

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
    "Transaction",
    "TransferResponse",
    "Wallet",
    "VERSION",
]
