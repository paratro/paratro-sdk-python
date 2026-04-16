"""Request and response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, List, Optional, TypeVar

T = TypeVar("T")


# ── Wallet ──


@dataclass
class CreateWalletRequest:
    wallet_name: str
    description: str = ""


@dataclass
class Wallet:
    wallet_id: str = ""
    client_id: str = ""
    wallet_name: str = ""
    description: str = ""
    status: str = ""
    key_status: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ListWalletsRequest:
    page: int = 0
    page_size: int = 0


# ── Account ──


@dataclass
class CreateAccountRequest:
    wallet_id: str = ""
    chain: str = ""
    account_type: Optional[str] = None
    label: Optional[str] = None


@dataclass
class Account:
    account_id: str = ""
    wallet_id: str = ""
    client_id: str = ""
    address: str = ""
    network: str = ""
    address_type: str = ""
    label: str = ""
    status: str = ""
    created_at: str = ""


@dataclass
class ListAccountsRequest:
    wallet_id: str = ""
    page: int = 0
    page_size: int = 0


# ── Asset ──


@dataclass
class CreateAssetRequest:
    account_id: str = ""
    symbol: str = ""
    chain: Optional[str] = None


@dataclass
class Asset:
    asset_id: str = ""
    account_id: str = ""
    wallet_id: str = ""
    client_id: str = ""
    chain: str = ""
    network: str = ""
    symbol: str = ""
    name: str = ""
    contract_address: str = ""
    decimals: int = 0
    asset_type: str = ""
    balance: str = "0"
    locked_balance: str = "0"
    is_active: bool = False
    created_at: str = ""


@dataclass
class ListAssetsRequest:
    account_id: str = ""
    page: int = 0
    page_size: int = 0


# ── Transaction ──


@dataclass
class Transaction:
    tx_id: str = ""
    wallet_id: str = ""
    client_id: str = ""
    chain: str = ""
    transaction_type: str = ""
    from_address: str = ""
    to_address: str = ""
    token_symbol: str = ""
    amount: str = "0"
    status: str = ""  # CONFIRMING, CONFIRMED, FAILED, PENDING, SIGNED, BROADCAST
    direction: str = ""  # INBOUND, OUTBOUND
    tx_hash: str = ""
    block_number: int = 0
    confirmations: int = 0
    created_at: str = ""


@dataclass
class ListTransactionsRequest:
    wallet_id: str = ""
    account_id: str = ""
    chain: str = ""
    page: int = 0
    page_size: int = 0


# ── Transfer ──


@dataclass
class CreateTransferRequest:
    from_address: str = ""
    to_address: str = ""
    chain: str = ""
    token_symbol: str = ""
    amount: str = "0"
    memo: str = ""


@dataclass
class TransferResponse:
    tx_id: str = ""
    status: str = ""
    message: str = ""


# ── Paginated Response ──


@dataclass
class PaginatedResponse(Generic[T]):
    items: List[T] = field(default_factory=list)
    total: int = 0
    has_more: bool = False


# ── Webhook ──


class WebhookEventType:
    """Webhook event type constants."""
    TRANSACTION_CONFIRMING = "transaction.confirming"
    TRANSACTION_CONFIRMED = "transaction.confirmed"
    TRANSACTION_FAILED = "transaction.failed"


@dataclass
class WebhookEvent:
    """Parsed webhook event payload (v2 schema, 26 fields)."""
    event_id: str = ""
    event_type: str = ""  # See WebhookEventType
    event_time: str = ""
    source_id: str = ""
    wallet_id: str = ""
    account_id: str = ""
    status: str = ""  # CONFIRMING, CONFIRMED, FAILED
    transaction_type: str = ""  # INBOUND, OUTBOUND, SWEEP, GAS_REFUEL
    chain: str = ""
    network: str = ""
    txhash: str = ""
    block_number: int = 0
    from_addr: str = ""  # "from" in JSON (reserved word in Python)
    to_addr: str = ""    # "to" in JSON, renamed for consistency
    symbol: str = ""
    contract_address: str = ""
    amount: str = "0"
    decimals: int = 0
    confirmations: int = 0
    required_confirmations: int = 0
    created_at: str = ""
    confirmed_at: Optional[str] = None
    risk_checked: bool = False
    risk_score: float = 0.0
    risk_level: str = ""
    data: str = ""


# ── Whitelist ──


@dataclass
class TransferWhitelistItem:
    """A whitelisted transfer address."""
    whitelist_id: str = ""
    chain: str = ""
    address: str = ""
    label: str = ""
    added_by: str = ""
    created_at: str = ""


@dataclass
class ListWhitelistResponse:
    """Response for listing whitelisted addresses."""
    items: List[TransferWhitelistItem] = field(default_factory=list)
    total: int = 0
