"""Request and response models.

Field names match the gateway JSON exactly (``paratro-mpc-gateway/api/dto``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


# ── Wallet ──


@dataclass
class CreateWalletRequest:
    """``POST /api/v1/wallets`` (gateway ``dto.CreateWalletRequest``).

    ``threshold`` / ``total_shares`` are the k-of-n signing quorum; both
    optional, the gateway defaults to 2-of-3 and answers ``400`` when
    ``threshold > total_shares``. ``signing_party_ids`` optionally pins the hot
    signer node IDs (length must equal ``threshold``, values unique); when
    omitted the engine picks them at keygen. ``None`` fields are not sent.
    """

    wallet_name: str
    description: str = ""
    threshold: Optional[int] = None
    total_shares: Optional[int] = None
    signing_party_ids: Optional[List[str]] = None


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
    account_type: Optional[str] = None  # INBOUND | OUTBOUND
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


# ── Transactions: unified entry POST /api/v1/transactions ──


class Operation:
    """Values of the ``operation`` field (gateway ``dto.Operation*``)."""

    TRANSFER = "TRANSFER"
    PROGRAM_CALL = "PROGRAM_CALL"
    CONTRACT_CALL = "CONTRACT_CALL"


class TransactionStatus:
    """``status`` values seen in create responses and ``GET /transactions``.

    ``GET /transactions`` returns ``pto_transactions.status`` verbatim, and that
    column is also written by the portal (``paratro-mpc-webapi``) and the
    chain-watcher (``paratro-mpc-message``), so the list is **not closed**:
    poll with ``is_in_flight`` (``PENDING`` / ``SIGNED`` / ``PENDING_APPROVAL``)
    rather than switching on an exhaustive set of "done" values.

    * API create path: ``PENDING`` (TRANSFER, or 202) → ``SIGNED`` →
      ``BROADCAST`` → ``CONFIRMING`` → ``CONFIRMED`` | ``FAILED``
    * Portal-created rows (same client, same list): ``PENDING_APPROVAL``,
      ``REJECTED``, ``CANCELLED``
    * Inbound rows held by compliance: ``COMPLIANCE_BLOCKED``
    """

    PENDING = "PENDING"
    SIGNED = "SIGNED"
    BROADCAST = "BROADCAST"
    CONFIRMING = "CONFIRMING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    # Written by paratro-mpc-webapi (portal approval flow) / paratro-mpc-message.
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLIANCE_BLOCKED = "COMPLIANCE_BLOCKED"

    # Statuses in which the engine (or a portal approver) has not decided yet.
    IN_FLIGHT = frozenset({PENDING, SIGNED, PENDING_APPROVAL})

    @classmethod
    def is_in_flight(cls, status: str) -> bool:
        """True while the outcome is still open — keep polling.

        Stops on ``BROADCAST`` (the 202 question "did it reach the chain?" is
        answered; on-chain finality then comes via ``CONFIRMING`` →
        ``CONFIRMED`` / ``FAILED`` or the webhooks) and on every unknown value,
        so a status this SDK does not list never spins a poll loop.
        """
        return status in cls.IN_FLIGHT


def _put(body: Dict[str, Any], key: str, value: Any) -> None:
    """Add ``key`` when the optional value is set (non-empty string / non-None)."""
    if value is None:
        return
    if isinstance(value, str) and value == "":
        return
    body[key] = value


def _require(name: str, value: Any) -> None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ValueError(f"{name} is required")


@dataclass
class TransferRequest:
    """``operation=TRANSFER`` — asynchronous transfer signed by the MPC engine.

    ``amount`` is a human-readable decimal string (e.g. ``"10.5"``), at most 18
    decimal places. The gateway resolves the asset from ``chain`` + ``token_symbol``.
    """

    from_address: str = ""
    to_address: str = ""
    chain: str = ""
    token_symbol: str = ""
    amount: str = ""
    memo: str = ""
    reference_id: str = ""

    operation: str = field(default=Operation.TRANSFER, init=False, repr=False)

    def to_body(self) -> Dict[str, Any]:
        _require("from_address", self.from_address)
        _require("to_address", self.to_address)
        _require("chain", self.chain)
        _require("token_symbol", self.token_symbol)
        _require("amount", self.amount)
        body: Dict[str, Any] = {"operation": Operation.TRANSFER}
        _put(body, "reference_id", self.reference_id)
        body["from_address"] = self.from_address
        body["to_address"] = self.to_address
        body["chain"] = self.chain
        body["token_symbol"] = self.token_symbol
        body["amount"] = self.amount
        _put(body, "memo", self.memo)
        return body


# Pre-1.8 name. Same class, so ``CreateTransferRequest(...)`` keeps working.
CreateTransferRequest = TransferRequest


@dataclass
class ProgramCallRequest:
    """``operation=PROGRAM_CALL`` — co-sign a partially signed Solana transaction.

    ``signed_transaction`` is the counterparty-signed transaction, base64 or
    0x-hex. ``receive_address`` is our receiving wallet; defaults to
    ``from_address`` on the gateway when omitted.
    """

    from_address: str = ""
    chain: str = ""
    signed_transaction: str = ""
    receive_address: str = ""
    reference_id: str = ""
    memo: str = ""

    operation: str = field(default=Operation.PROGRAM_CALL, init=False, repr=False)

    def to_body(self) -> Dict[str, Any]:
        _require("from_address", self.from_address)
        _require("chain", self.chain)
        _require("signed_transaction", self.signed_transaction)
        body: Dict[str, Any] = {"operation": Operation.PROGRAM_CALL}
        _put(body, "reference_id", self.reference_id)
        body["from_address"] = self.from_address
        body["chain"] = self.chain
        _put(body, "receive_address", self.receive_address)
        body["signed_transaction"] = self.signed_transaction
        _put(body, "memo", self.memo)
        return body


@dataclass
class ContractCallIncomingLeg:
    """Our side pays the counterparty. Amount is a smallest-unit integer string."""

    to: str = ""
    token: str = ""
    amount: str = ""

    def to_body(self) -> Dict[str, Any]:
        _require("contract_call.incoming.to", self.to)
        _require("contract_call.incoming.token", self.token)
        _require("contract_call.incoming.amount", self.amount)
        return {"to": self.to, "token": self.token, "amount": self.amount}


@dataclass
class ContractCallOutgoingLeg:
    """The counterparty pays us. Amount is a smallest-unit integer string."""

    from_: str = ""  # "from" in JSON (reserved word in Python)
    to: str = ""
    token: str = ""
    amount: str = ""

    def to_body(self) -> Dict[str, Any]:
        _require("contract_call.outgoing.from", self.from_)
        _require("contract_call.outgoing.to", self.to)
        _require("contract_call.outgoing.token", self.token)
        _require("contract_call.outgoing.amount", self.amount)
        return {"from": self.from_, "to": self.to, "token": self.token, "amount": self.amount}


@dataclass
class ContractCall:
    """The counterparty's ``executeSwap`` quote, forwarded as-is.

    * ``quote_id``: bytes32 hex (``0x`` prefix allowed).
    * ``expiration``: unix seconds; must be in the future.
    * ``counterparty_signature``: the counterparty's EIP-712 signature (hex);
      verified by the contract, not by the gateway.
    * ``permit_deadline``: optional unix seconds; gateway default is
      ``now + min(fee_limits.max_permit_lifetime_seconds, 300)``.

    The contract address is **not** a request field — the gateway takes it from
    the OPERATION_RULES policy (``call_rules.allowed_contracts[chain]``).
    """

    quote_id: str = ""
    expiration: int = 0
    incoming: ContractCallIncomingLeg = field(default_factory=ContractCallIncomingLeg)
    outgoing: ContractCallOutgoingLeg = field(default_factory=ContractCallOutgoingLeg)
    counterparty_signature: str = ""
    permit_deadline: Optional[int] = None

    def to_body(self) -> Dict[str, Any]:
        _require("contract_call.quote_id", self.quote_id)
        if not self.expiration:
            raise ValueError("contract_call.expiration is required")
        _require("contract_call.counterparty_signature", self.counterparty_signature)
        body: Dict[str, Any] = {
            "quote_id": self.quote_id,
            "expiration": int(self.expiration),
            "incoming": self.incoming.to_body(),
            "outgoing": self.outgoing.to_body(),
            "counterparty_signature": self.counterparty_signature,
        }
        if self.permit_deadline is not None:
            body["permit_deadline"] = int(self.permit_deadline)
        return body


@dataclass
class ContractCallRequest:
    """``operation=CONTRACT_CALL`` — EVM ``executeSwap`` with an EIP-2612 permit.

    ``from_address`` is our paying wallet (= ``incoming`` payer = permit owner =
    tx sender); ``receive_address`` is our receiving wallet (= ``outgoing.to``),
    defaults to ``from_address``. Native value is always 0.
    """

    from_address: str = ""
    chain: str = ""
    contract_call: ContractCall = field(default_factory=ContractCall)
    receive_address: str = ""
    reference_id: str = ""
    memo: str = ""

    operation: str = field(default=Operation.CONTRACT_CALL, init=False, repr=False)

    def to_body(self) -> Dict[str, Any]:
        _require("from_address", self.from_address)
        _require("chain", self.chain)
        body: Dict[str, Any] = {"operation": Operation.CONTRACT_CALL}
        _put(body, "reference_id", self.reference_id)
        body["from_address"] = self.from_address
        body["chain"] = self.chain
        _put(body, "receive_address", self.receive_address)
        _put(body, "memo", self.memo)
        body["contract_call"] = self.contract_call.to_body()
        return body


@dataclass
class CreateTransactionResponse:
    """Result of ``POST /api/v1/transactions`` (gateway ``dto.TransferResponse``).

    * TRANSFER → HTTP 200, ``status="PENDING"``: the engine signs asynchronously;
      ``tx_hash`` is empty. Poll ``get`` or wait for the webhook.
    * PROGRAM_CALL / CONTRACT_CALL → HTTP 200, ``status="BROADCAST"`` with ``tx_hash``.
    * PROGRAM_CALL / CONTRACT_CALL → HTTP 202, ``status="PENDING"`` (``accepted``
      is True): the signing engine did not answer in time and the outcome is
      unknown. Poll ``GET /api/v1/transactions/{tx_id}``; **do not resubmit with
      the same ``reference_id``** — it would hit the uniqueness constraint.

    ``operation`` is the ``operation`` of the request this response answers. The
    gateway does not echo it; ``TransactionsService.create`` fills it in so that
    ``accepted`` can recognise an ``Idempotency-Key`` replay of a 202 (which the
    gateway serves as HTTP 200 with the same ``PENDING`` body).
    """

    tx_id: str = ""
    status: str = ""
    message: str = ""
    tx_hash: str = ""
    http_status: int = 200
    operation: str = ""

    @property
    def accepted(self) -> bool:
        """True when the outcome of a PROGRAM_CALL / CONTRACT_CALL is unknown.

        The gateway signals it with HTTP 202. An ``Idempotency-Key`` replay of
        that answer arrives as HTTP 200 with the same body (``status="PENDING"``,
        no ``tx_hash``), so this is also True for a PROGRAM_CALL / CONTRACT_CALL
        whose ``status`` is ``PENDING`` — those operations never answer PENDING
        otherwise. A TRANSFER's normal ``200 PENDING`` is not "accepted". Same
        rule as ``Accepted()`` in the Go SDK. Poll by ``tx_id``; never resubmit
        with the same ``reference_id``.
        """
        if self.http_status == 202:
            return True
        return bool(self.operation) and self.operation != Operation.TRANSFER \
            and self.status == TransactionStatus.PENDING

    @property
    def broadcast(self) -> bool:
        """True when the transaction was broadcast synchronously (``tx_hash`` is set)."""
        return self.status == TransactionStatus.BROADCAST


# Pre-1.8 name for the create response.
TransferResponse = CreateTransactionResponse


@dataclass
class Transaction:
    """One row of ``GET /api/v1/transactions`` (gateway ``dto.TransactionResponse``)."""

    tx_id: str = ""
    wallet_id: str = ""
    client_id: str = ""
    chain: str = ""
    transaction_type: str = ""
    from_address: str = ""
    to_address: str = ""
    token_symbol: str = ""
    amount: str = "0"
    status: str = ""  # See TransactionStatus
    tx_hash: str = ""
    risk_score: str = ""
    risk_level: str = ""
    created_at: str = ""


@dataclass
class ListTransactionsRequest:
    wallet_id: str = ""
    account_id: str = ""
    chain: str = ""
    page: int = 0
    page_size: int = 0


# ── Paginated Response ──


@dataclass
class PaginatedResponse(Generic[T]):
    items: List[T] = field(default_factory=list)
    total: int = 0
    has_more: bool = False


# ── x402 facilitator ──


@dataclass
class X402VerifyResponse:
    """``POST /api/v1/x402/verify`` (gateway ``dto.X402VerifyResponse``)."""

    is_valid: bool = False  # "isValid"
    invalid_reason: Optional[str] = None  # "invalidReason"
    payer: str = ""


@dataclass
class X402SettleResponse:
    """``POST /api/v1/x402/settle`` (gateway ``dto.X402SettleResponse``)."""

    success: bool = False
    tx_id: str = ""  # "txId"
    transaction: str = ""
    error_reason: Optional[str] = None  # "errorReason"
    payer: str = ""
    network: str = ""


@dataclass
class X402SettleStatusResponse:
    """``GET /api/v1/x402/settle/{tx_id}`` (gateway ``dto.X402SettleStatusResponse``)."""

    success: bool = False
    tx_id: str = ""  # "txId"
    status: str = ""
    tx_hash: str = ""  # "txHash"
    network: str = ""


@dataclass
class X402Settlement:
    """One row of ``GET /api/v1/x402/settlements`` (gateway ``dto.X402SettlementResponse``)."""

    tx_id: str = ""
    chain: str = ""
    from_address: str = ""
    to_address: str = ""
    amount: str = ""
    status: str = ""
    valid_before: int = 0
    signature_v: Optional[int] = None
    signature_r: Optional[str] = None
    signature_s: Optional[str] = None
    created_at: str = ""


@dataclass
class ListX402SettlementsRequest:
    status: str = ""  # PENDING | PROCESSING | X402_SIGNED | SETTLED | CANCELLED | FAILED | EXPIRED
    page: int = 0
    page_size: int = 0


# ── Webhook ──


class WebhookEventType:
    """Webhook event types emitted by paratro-mpc-message."""

    TRANSACTION_CONFIRMING = "transaction.confirming"
    TRANSACTION_CONFIRMED = "transaction.confirmed"
    TRANSACTION_FAILED = "transaction.failed"
    # Credit of an internal (Paratro-to-Paratro) transfer to the receiving
    # account. Deliberately distinct from transaction.confirmed so existing
    # deposit handlers do not pick it up by accident; transaction_type=INTERNAL.
    TRANSFER_CREDITED = "transfer.credited"
    # Recipient side of an x402 settlement (client.x402.settle) once the
    # settlement is confirmed on-chain and credited: status=CONFIRMED,
    # transaction_type=INBOUND (paratro-mpc-message dispatcher/x402_credit.go).
    X402_SETTLEMENT_CONFIRMED = "x402.settlement.confirmed"


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
    transaction_type: str = ""  # INBOUND, OUTBOUND, INTERNAL, ...
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
