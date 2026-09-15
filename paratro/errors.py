"""Error types for the SDK.

Every non-2xx response from the gateway carries the same body::

    {"code": "<machine code>", "type": "<category>", "message": "<human text>"}

``APIError`` keeps those three fields verbatim (``code``, ``error_type``,
``message``) plus ``http_status``. ``APIError.from_response`` picks a typed
subclass by HTTP status so callers can ``except`` the situations that need
different handling (rejected, forbidden, not found, retired, unavailable).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


# ── Machine-readable codes / types returned by the gateway (common/errors.go) ──


class ErrorCode:
    """Values of the ``code`` field (gateway ``common/errors.go``)."""

    BAD_REQUEST = "bad_request"
    INVALID_PARAMETER = "invalid_parameter"
    VALIDATION_FAILED = "validation_failed"
    UNAUTHORIZED = "unauthorized"
    INVALID_TOKEN = "invalid_token"
    TOKEN_EXPIRED = "token_expired"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RESOURCE_NOT_FOUND = "resource_not_found"
    CONFLICT = "conflict"
    RESOURCE_EXISTS = "resource_exists"
    TOO_MANY_REQUESTS = "too_many_requests"
    INTERNAL_ERROR = "internal_error"
    DATABASE_ERROR = "database_error"
    CACHE_ERROR = "cache_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    BUSINESS_ERROR = "business_error"
    WALLET_LIMIT_REACHED = "wallet_limit_reached"
    ACCOUNT_LIMIT_REACHED = "account_limit_reached"
    CHAIN_NOT_ALLOWED = "chain_not_allowed"
    WITHDRAWAL_LIMIT_REACHED = "withdrawal_limit_reached"
    API_QUOTA_EXCEEDED = "api_quota_exceeded"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INVALID_ADDRESS = "invalid_address"
    TRANSACTION_FAILED = "transaction_failed"
    CONCURRENCY_ERROR = "concurrency_error"
    ASSET_ALREADY_EXISTS = "asset_already_exists"
    WALLET_NOT_ACTIVE = "wallet_not_active"
    ACCOUNT_NOT_ACTIVE = "account_not_active"
    ADDRESS_BLACKLISTED = "address_blacklisted"


class ErrorType:
    """Values of the ``type`` field (gateway ``common/errors.go``)."""

    INVALID_REQUEST = "invalid_request_error"
    AUTHENTICATION = "authentication_error"
    PERMISSION = "permission_error"
    NOT_FOUND = "not_found_error"
    CONFLICT = "conflict_error"
    RATE_LIMIT = "rate_limit_error"
    API = "api_error"
    BUSINESS = "business_error"
    # Emitted by handler.RetiredEndpoint together with HTTP 410 and code=invalid_parameter.
    ENDPOINT_RETIRED = "endpoint_retired"


class RejectionReason:
    """Machine-readable tags carried by ``400 "Rejected: <tag>: <detail>"`` and
    ``400 transaction_failed "<OPERATION> failed: <tag>"``.

    A PROGRAM_CALL / CONTRACT_CALL that is well-formed but not allowed is
    answered with HTTP 400, ``code=invalid_parameter`` and a message of the form
    ``"Rejected: <tag>: <detail>"`` (``CONTRACT_CALL_TAGS`` / ``PROGRAM_CALL_TAGS``).
    When the signing engine refuses after the row was created the gateway answers
    ``400 code=transaction_failed "<OPERATION> failed: <tag>"`` and forwards only
    the engine's leading tag (``ENGINE_FAILURE_TAGS``; free-text engine errors
    collapse to ``"engine rejected the transaction"``, no tag).
    ``APIError.reason_tag`` extracts ``<tag>`` from both shapes.

    Sources (all verified against code; gateway develop @ b8bbea5, engine develop @ 3d4a0ed):

    * CONTRACT_CALL verifier — ``paratro-common/xchange/execute_swap.go``
    * PROGRAM_CALL verifier — ``paratro-common/xchange/solana_verifier.go``
    * gateway pre-checks — ``paratro-mpc-gateway/internal/service/{operation_service,program_call,contract_call}.go``
    * engine settle / broadcast path — ``paratro-mpc-engine/mpc-engine/internal/syncsettle``
    * engine EIP-2612 permit step of a CONTRACT_CALL — ``mpc-engine/internal/syncsign/permit.go``

    The sets are the literals in that code at release time, **not a closed
    vocabulary**: a new gateway / engine release can add tags. Match on the tags
    you handle and treat an unknown tag as a rejection you have not seen yet.
    Same values as ``paratro_sdk::reason_tag`` in the Rust SDK and the ``Reason*``
    constants in the Go SDK.
    """

    # ── shared by both operations ──
    COUNTERPARTY_NOT_REGISTERED = "counterparty_not_registered"
    LIMIT_NOT_CONFIGURED = "limit_not_configured"
    LIMIT_PER_TRANSACTION = "limit_per_transaction"
    LIMIT_DAILY = "limit_daily"
    LIMIT_DECIMALS_AMBIGUOUS = "limit_decimals_ambiguous"

    # ── CONTRACT_CALL (EVM executeSwap) ──
    ABI = "abi"
    AMOUNT_NOT_POSITIVE = "amount_not_positive"
    CALLDATA = "calldata"
    CALLDATA_NOT_CANONICAL = "calldata_not_canonical"
    CONTRACT_ADDRESS = "contract_address"
    EXPIRATION = "expiration"
    EXPIRATION_PASSED = "expiration_passed"
    EXPIRATION_TOO_FAR = "expiration_too_far"
    INCOMING_FROM = "incoming_from"
    OUTGOING_TO = "outgoing_to"
    PAYMENT_TOKEN_NOT_REGISTERED = "payment_token_not_registered"
    PERMIT_DEADLINE = "permit_deadline"
    PERMIT_DEADLINE_PASSED = "permit_deadline_passed"
    PERMIT_DEADLINE_TOO_FAR = "permit_deadline_too_far"
    PERMIT_OWNER = "permit_owner"
    SELECTOR = "selector"
    TARGET_TOKEN_NOT_REGISTERED = "target_token_not_registered"
    VALUE_NOT_ZERO = "value_not_zero"

    # ── PROGRAM_CALL (Solana) ──
    # POLICY_INVALID: as a ``400 Rejected:`` tag the gateway emits it only for
    # PROGRAM_CALL (``program_call.go``, unparseable ``call_rules.allowed_programs``).
    # The engine also uses it as a ``transaction_failed`` tag for both operations
    # (``syncsettle/operation.go``, ``syncsign/permit.go``) — see ENGINE_FAILURE_TAGS.
    POLICY_INVALID = "policy_invalid"
    ACCOUNT_UNRESOLVABLE = "account_unresolvable"
    ALT_NOT_ALLOWED = "alt_not_allowed"
    ATA_DERIVATION = "ata_derivation"
    COUNTERPARTY_SIGNATURE_INVALID = "counterparty_signature_invalid"
    COUNTERPARTY_SIGNATURE_MISSING = "counterparty_signature_missing"
    FEE_PAYER = "fee_payer"
    INCOMING_DESTINATION = "incoming_destination"
    MALFORMED = "malformed"
    MINT_NOT_REGISTERED = "mint_not_registered"
    MINT_PROGRAM_UNKNOWN = "mint_program_unknown"
    OUTGOING_AUTHORITY = "outgoing_authority"
    OUTGOING_SOURCE = "outgoing_source"
    PAYER_SIGNATURE_PRESENT = "payer_signature_present"
    PROGRAM_NOT_ALLOWED = "program_not_allowed"
    PROGRAM_UNRESOLVABLE = "program_unresolvable"
    SHAPE = "shape"

    CONTRACT_CALL_TAGS = frozenset({
        "abi", "amount_not_positive", "calldata", "calldata_not_canonical",
        "contract_address", "counterparty_not_registered", "expiration",
        "expiration_passed", "expiration_too_far", "incoming_from",
        "limit_not_configured", "limit_per_transaction", "limit_daily",
        "limit_decimals_ambiguous", "outgoing_to", "payment_token_not_registered",
        "permit_deadline", "permit_deadline_passed", "permit_deadline_too_far",
        "permit_owner", "selector", "target_token_not_registered", "value_not_zero",
    })

    PROGRAM_CALL_TAGS = frozenset({
        "account_unresolvable", "alt_not_allowed", "ata_derivation",
        "counterparty_not_registered", "counterparty_signature_invalid",
        "counterparty_signature_missing", "fee_payer", "incoming_destination",
        "limit_daily", "limit_decimals_ambiguous", "limit_not_configured",
        "limit_per_transaction", "malformed", "mint_not_registered",
        "mint_program_unknown", "outgoing_authority", "outgoing_source",
        "payer_signature_present", "policy_invalid", "program_not_allowed",
        "program_unresolvable", "shape",
    })

    # ── engine verdicts, 400 transaction_failed "<OPERATION> failed: <tag>" ──
    # Every reject("…") literal in mpc-engine internal/syncsettle plus every
    # rejectPermit("…") literal in internal/syncsign/permit.go. The engine also
    # re-runs the paratro-common verifiers, so any tag above can appear here too.
    CALLDATA_INVALID = "calldata_invalid"
    CONTRACT_ADDRESS_INVALID = "contract_address_invalid"
    CONTRACT_NOT_REGISTERED = "contract_not_registered"
    COSIGNATURE_INVALID = "cosignature_invalid"
    DAILY_ALLOWANCE_MISSING = "daily_allowance_missing"
    DAILY_USAGE_UNAVAILABLE = "daily_usage_unavailable"
    INTERNAL = "internal"
    MINT_TOKEN_PROGRAM_UNRESOLVED = "mint_token_program_unresolved"
    PAYER_INVALID = "payer_invalid"
    PAYER_MISMATCH = "payer_mismatch"
    # syncsign/permit.go: the engine re-derives the EIP-2612 permit from the row
    # and the policy before signing and refuses when its view differs from the
    # gateway's request.
    PERMIT_DIGEST_MISMATCH = "permit_digest_mismatch"
    PERMIT_DIGEST_MISSING = "permit_digest_missing"
    PERMIT_DOMAIN_MISMATCH = "permit_domain_mismatch"
    PERMIT_DOMAIN_UNVERIFIED = "permit_domain_unverified"
    PERMIT_OWNER_MISMATCH = "permit_owner_mismatch"
    PERMIT_PARAMS_INVALID = "permit_params_invalid"
    PERMIT_SPENDER_MISMATCH = "permit_spender_mismatch"
    PERMIT_TOKEN_MISMATCH = "permit_token_mismatch"
    PERMIT_TOKEN_NOT_REGISTERED = "permit_token_not_registered"
    PERMIT_VALUE_MISMATCH = "permit_value_mismatch"
    POLICY_NOT_AUTHORIZED = "policy_not_authorized"
    RECEIVER_INVALID = "receiver_invalid"
    RECEIVER_LOOKUP_FAILED = "receiver_lookup_failed"
    RECEIVER_MISSING = "receiver_missing"
    RECEIVER_NOT_OURS = "receiver_not_ours"
    REQUEST_DIGEST_MISMATCH = "request_digest_mismatch"
    REQUEST_DIGEST_MISSING = "request_digest_missing"
    SIGNER_SLOT = "signer_slot"

    ENGINE_FAILURE_TAGS = frozenset({
        "alt_not_allowed", "amount_not_positive", "calldata_invalid",
        "contract_address_invalid", "contract_not_registered", "cosignature_invalid",
        "daily_allowance_missing", "daily_usage_unavailable", "internal", "limit_daily",
        "limit_not_configured", "limit_per_transaction", "malformed",
        "mint_token_program_unresolved", "payer_invalid", "payer_mismatch",
        "permit_deadline_passed", "permit_deadline_too_far", "permit_digest_mismatch",
        "permit_digest_missing", "permit_domain_mismatch", "permit_domain_unverified",
        "permit_owner_mismatch", "permit_params_invalid", "permit_spender_mismatch",
        "permit_token_mismatch", "permit_token_not_registered", "permit_value_mismatch",
        "policy_invalid", "policy_not_authorized", "program_not_allowed", "receiver_invalid",
        "receiver_lookup_failed", "receiver_missing", "receiver_not_ours",
        "request_digest_mismatch", "request_digest_missing", "signer_slot",
    })

    #: Tags a ``400 "Rejected: <tag>: …"`` can carry (raised by the gateway / verifiers).
    REJECTED_TAGS = CONTRACT_CALL_TAGS | PROGRAM_CALL_TAGS

    #: Every tag this release knows about, whichever of the two messages carries it.
    ALL_TAGS = REJECTED_TAGS | ENGINE_FAILURE_TAGS


# Same regexp as gateway engineReasonTag: lowercase words joined by underscores.
_REASON_TAG_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_REJECTED_PREFIX = "Rejected: "
_ENGINE_FAILED_RE = re.compile(r"^(?:TRANSFER|PROGRAM_CALL|CONTRACT_CALL) failed: (.+)$", re.DOTALL)
# The only 503 message the gateway writes AFTER the transaction row exists
# (api/handler/transaction_handler.go writeOperationError, ErrEngineBusy). The
# other two 503 messages ("Chain RPC unavailable; cannot verify request",
# "<OPERATION> is not enabled on this gateway") are written before any insert.
_ENGINE_BUSY_MESSAGE = "Signing service is busy, retry later"


def _extract_reason_tag(message: str) -> Optional[str]:
    if message.startswith(_REJECTED_PREFIX):
        rest = message[len(_REJECTED_PREFIX):]
    else:
        m = _ENGINE_FAILED_RE.match(message)
        if not m:
            return None
        rest = m.group(1)
    tag = rest.split(":", 1)[0].strip()
    if tag and len(tag) <= 64 and _REASON_TAG_RE.match(tag):
        return tag
    return None


class APIError(Exception):
    """Error returned by the Paratro API.

    Attributes:
        http_status: HTTP status code.
        code: ``code`` field of the error body (see ``ErrorCode``).
        error_type: ``type`` field of the error body (see ``ErrorType``).
        message: ``message`` field of the error body.
    """

    def __init__(self, http_status: int, code: str, error_type: str, message: str) -> None:
        self.http_status = http_status
        self.code = code
        self.error_type = error_type
        self.message = message
        super().__init__(f"[{http_status}] {code}: {message}")

    @property
    def reason_tag(self) -> Optional[str]:
        """Machine-readable reason behind a rejected operation, if any.

        * ``400 "Rejected: <tag>: <detail>"`` (verifier / policy rejection) → ``<tag>``
        * ``400 code=transaction_failed "<OPERATION> failed: <tag>"`` (engine
          rejected after the row was created) → ``<tag>``; ``None`` when the
          gateway collapsed the reason to ``"engine rejected the transaction"``.
        * anything else → ``None``.
        """
        return _extract_reason_tag(self.message)

    @property
    def is_rejected(self) -> bool:
        """True for ``400 "Rejected: <tag>: …"`` (policy / verifier rejection)."""
        return self.http_status == 400 and self.message.startswith(_REJECTED_PREFIX)

    @property
    def is_duplicate_reference(self) -> bool:
        """True when the same ``reference_id`` was submitted twice by this client."""
        return self.http_status == 400 and self.message.startswith("Duplicate reference_id")

    @classmethod
    def from_response(cls, http_status: int, body: Optional[Dict[str, Any]], raw_text: str = "") -> "APIError":
        """Build the most specific error subclass for an HTTP status + body."""
        if isinstance(body, dict):
            code = str(body.get("code", "unknown"))
            error_type = str(body.get("type", "unknown"))
            message = str(body.get("message", raw_text))
        else:
            code, error_type, message = "unknown", "unknown", raw_text

        subclass = _SUBCLASS_BY_STATUS.get(http_status, cls)
        if http_status == 400 and message.startswith(_REJECTED_PREFIX):
            subclass = RejectedError
        return subclass(http_status, code, error_type, message)


class RejectedError(APIError):
    """``400 "Rejected: <tag>: …"`` — the operation is well-formed but not allowed.

    Inspect ``reason_tag`` (one of ``RejectionReason``). Fix the request or the
    policy before retrying; resending the same request will be rejected again.

    Normally raised before anything was signed or written, so the
    ``reference_id`` is still free. One exception: a CONTRACT_CALL is
    re-verified **after** its EIP-2612 permit was signed and the row inserted
    (gateway ``contract_call.go`` post-sign ``VerifyExecuteSwap``); that rejection
    leaves the row held ``PENDING`` until the permit deadline, the ``reference_id``
    stays consumed (``400 Duplicate reference_id`` on a resend), and a retry with a
    new ``reference_id`` can see ``insufficient_balance`` while the reservation is
    held. The two cases cannot be told apart from the response, so when a
    CONTRACT_CALL is rejected retry, if at all, with a new ``reference_id``.
    """


class BadRequestError(APIError):
    """HTTP 400 that is not a verifier rejection (validation, duplicate
    ``reference_id``, ``insufficient_balance``, ``transaction_failed``, …).

    ``code=transaction_failed`` (``"<OPERATION> failed: <tag>"``) means the
    engine answered FAILED **after** the transaction row was inserted, and the
    row keeps your ``reference_id``. Normally it is marked FAILED and its
    reservation released; a CONTRACT_CALL whose EIP-2612 permit was already
    signed is instead held PENDING with the reservation locked until the
    permit deadline has passed and the reconciler has confirmed the permit was
    not used (gateway ``dispatchSettle`` / ``holdOperation``). Either way a
    resubmission with the same value answers ``400 Duplicate reference_id``:
    use a new ``reference_id`` — while the row is still held the retry can see
    ``insufficient_balance``.
    """


class AuthenticationError(APIError):
    """HTTP 401 — ``unauthorized`` / ``invalid_token`` / ``token_expired``.

    ``token_expired`` is handled by the client automatically (one token refresh
    and one retry); you only see it when the retry also failed.
    """

    @property
    def is_token_expired(self) -> bool:
        return self.code == ErrorCode.TOKEN_EXPIRED


class ForbiddenError(APIError):
    """HTTP 403.

    * PROGRAM_CALL / CONTRACT_CALL (``code=forbidden``): no active
      OPERATION_RULES policy authorises this (operation, chain, network).
    * TRANSFER (``code=address_blacklisted``): the destination address is
      blacklisted — the policy UI will not help, the ``to_address`` is the problem.
    * ``POST /auth/token`` (``code=forbidden``): caller IP not in the allowlist,
      or the client account is suspended.
    """

    @property
    def is_address_blacklisted(self) -> bool:
        return self.code == ErrorCode.ADDRESS_BLACKLISTED


class NotFoundError(APIError):
    """HTTP 404 — the address / asset does not belong to this client, or the
    token has not been credited to the account yet."""


class ConflictError(APIError):
    """HTTP 409 — ``conflict`` / ``resource_exists``."""


class EndpointRetiredError(APIError):
    """HTTP 410 — the endpoint has been retired (``type=endpoint_retired``).

    ``POST /api/v1/transfer`` and ``POST /api/v1/x402/sign`` answer 410; the
    message names the replacement (``POST /api/v1/transactions``).
    """


class RateLimitError(APIError):
    """HTTP 429 — ``too_many_requests`` / ``api_quota_exceeded``."""


class ServiceUnavailableError(APIError):
    """HTTP 503 (``code=service_unavailable``) — only PROGRAM_CALL / CONTRACT_CALL
    produce it; TRANSFER never answers 503.

    The gateway writes exactly three messages, and they differ in whether your
    ``reference_id`` is still free:

    * ``"Chain RPC unavailable; cannot verify request"`` and
      ``"<OPERATION> is not enabled on this gateway"`` are raised **before** any
      row is inserted. Nothing was recorded; retry later with the **same**
      ``reference_id``.
    * ``"Signing service is busy, retry later"`` (``is_engine_busy``) is raised
      **after** the row was inserted: the engine's signing lane was saturated
      and the row keeps your ``reference_id`` (unique key ``uk_client_reference``
      does not exclude FAILED rows). A PROGRAM_CALL row, or a CONTRACT_CALL
      refused at the permit-signing step, is marked FAILED and its reservation
      released; a CONTRACT_CALL refused at the broadcast step — after its
      EIP-2612 permit was signed — is held PENDING with the reservation locked
      until the permit deadline has passed and the reconciler has checked the
      permit was not used. Resubmitting with the same ``reference_id`` answers
      ``400 Duplicate reference_id``; retry with a **new** ``reference_id``
      (while a row is still held the retry can see ``insufficient_balance``).
      The 503 body carries no ``tx_id`` and ``GET /transactions`` cannot filter
      by ``reference_id``, so the leftover row can only be found by listing
      the wallet's recent transactions.
    """

    @property
    def is_engine_busy(self) -> bool:
        """True for the engine-busy 503 — the row exists (FAILED, or held
        PENDING when a CONTRACT_CALL permit was already signed) and the
        submitted ``reference_id`` is consumed."""
        return self.message.startswith(_ENGINE_BUSY_MESSAGE)

    @property
    def reference_id_consumed(self) -> bool:
        """Whether the ``reference_id`` of the failed request is now taken.

        Alias of ``is_engine_busy``: the other 503 causes happen before the
        insert and leave the reference free.
        """
        return self.is_engine_busy


_SUBCLASS_BY_STATUS = {
    400: BadRequestError,
    401: AuthenticationError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    410: EndpointRetiredError,
    429: RateLimitError,
    503: ServiceUnavailableError,
}


# ── Predicate helpers (kept for pre-1.8 compatibility) ──


def is_not_found(err: BaseException) -> bool:
    """Check if the error is a 404 Not Found."""
    return isinstance(err, APIError) and err.http_status == 404


def is_rate_limited(err: BaseException) -> bool:
    """Check if the error is a 429 Rate Limited."""
    return isinstance(err, APIError) and err.http_status == 429


def is_auth_error(err: BaseException) -> bool:
    """Check if the error is a 401 or 403 auth error."""
    return isinstance(err, APIError) and err.http_status in (401, 403)


def is_rejected(err: BaseException) -> bool:
    """Check if the error is a ``400 "Rejected: <tag>: …"`` policy/verifier rejection."""
    return isinstance(err, APIError) and err.is_rejected


def is_forbidden(err: BaseException) -> bool:
    """Check if the error is a 403 (no policy authorises the operation)."""
    return isinstance(err, APIError) and err.http_status == 403


def is_endpoint_retired(err: BaseException) -> bool:
    """Check if the error is a 410 endpoint_retired."""
    return isinstance(err, APIError) and err.http_status == 410


def is_service_unavailable(err: BaseException) -> bool:
    """Check if the error is a 503 (engine busy / chain RPC unavailable / operation not enabled).

    See ``ServiceUnavailableError``: only the chain-RPC / not-enabled variants
    leave the ``reference_id`` free; engine busy consumes it.
    """
    return isinstance(err, APIError) and err.http_status == 503


def is_engine_busy(err: BaseException) -> bool:
    """Check if the error is the engine-busy 503 (row FAILED, ``reference_id`` consumed)."""
    return isinstance(err, ServiceUnavailableError) and err.is_engine_busy


def is_token_expired(err: BaseException) -> bool:
    """Check if the error is a 401 token_expired."""
    return isinstance(err, APIError) and err.http_status == 401 and err.code == ErrorCode.TOKEN_EXPIRED
