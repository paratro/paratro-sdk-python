"""Transactions service — the unified entry ``POST /api/v1/transactions``.

One endpoint, three operations selected by the ``operation`` field:

======================  ======================================  ==========================================
operation               request type                            success response
======================  ======================================  ==========================================
``TRANSFER``            :class:`paratro.models.TransferRequest`      200 ``{tx_id, status="PENDING", message}``
``PROGRAM_CALL``        :class:`paratro.models.ProgramCallRequest`   200 ``{…, status="BROADCAST", tx_hash}`` or 202 ``{…, status="PENDING"}``
``CONTRACT_CALL``       :class:`paratro.models.ContractCallRequest`  200 ``{…, status="BROADCAST", tx_hash}`` or 202 ``{…, status="PENDING"}``
======================  ======================================  ==========================================

Errors (all ``{"code","type","message"}``):

* ``400`` ``"Rejected: <tag>: …"`` → :class:`paratro.errors.RejectedError`, ``reason_tag``
* ``400`` ``"Duplicate reference_id: …"`` → :class:`paratro.errors.BadRequestError`, ``is_duplicate_reference``
* ``400`` ``insufficient_balance`` → :class:`paratro.errors.BadRequestError` (no row written)
* ``400`` ``transaction_failed`` ``"<OP> failed: <tag>"`` → :class:`paratro.errors.BadRequestError`
  (row written before the engine refused — FAILED, or held PENDING until the permit deadline when a
  CONTRACT_CALL permit was already signed; the ``reference_id`` is consumed, use a new one)
* ``403`` → :class:`paratro.errors.ForbiddenError` (no OPERATION_RULES policy authorises it;
  for TRANSFER ``code=address_blacklisted`` = destination blacklisted)
* ``404`` → :class:`paratro.errors.NotFoundError` (address/asset not this client's, or token not credited yet)
* ``503`` → :class:`paratro.errors.ServiceUnavailableError` — two different situations:

  - ``"Chain RPC unavailable; cannot verify request"`` / ``"<OP> is not enabled on this gateway"``:
    raised before any row is written; retry later with the **same** ``reference_id``.
  - ``"Signing service is busy, retry later"`` (``is_engine_busy``): the row was already written and
    keeps your ``reference_id`` (FAILED, or held PENDING until the permit deadline when a CONTRACT_CALL
    permit was already signed); resubmitting it answers ``400 Duplicate reference_id``. Retry with a
    **new** ``reference_id``.

Which errors consume ``reference_id`` (row exists, unique key ``uk_client_reference`` covers FAILED rows):
``202`` (row PENDING — poll, never resubmit), ``400 transaction_failed``, ``503`` engine busy, and the
CONTRACT_CALL post-sign ``400 "Rejected: …"`` (gateway ``contract_call.go`` re-verifies the calldata after
the permit was signed and the row inserted; that row is held PENDING until the permit deadline and keeps
the ``reference_id``, so a retry with a new ``reference_id`` can see ``insufficient_balance`` until then).
Every other ``Rejected`` is raised before the insert. A ``500`` cannot be classified from the outside
(some are raised after the insert); if a resend with the same ``reference_id`` answers
``400 Duplicate reference_id`` the first attempt did create a row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from paratro.models import (
    ContractCallRequest,
    CreateTransactionResponse,
    ListTransactionsRequest,
    PaginatedResponse,
    ProgramCallRequest,
    Transaction,
    TransferRequest,
)

if TYPE_CHECKING:  # pragma: no cover
    from paratro.client import MPCClient

TransactionRequest = Union[TransferRequest, ProgramCallRequest, ContractCallRequest]

PATH = "/api/v1/transactions"


class TransactionsService:
    """``client.transactions`` — create / get / list transactions."""

    def __init__(self, client: "MPCClient") -> None:
        self._client = client

    def create(
        self,
        req: TransactionRequest,
        idempotency_key: Optional[str] = None,
    ) -> CreateTransactionResponse:
        """``POST /api/v1/transactions``.

        Args:
            req: One of ``TransferRequest``, ``ProgramCallRequest``, ``ContractCallRequest``.
                ``reference_id`` is your business reference; the gateway rejects a
                second submission with the same value (``400 Duplicate reference_id``).
            idempotency_key: Optional ``Idempotency-Key`` header. The gateway caches
                a 2xx response for 24 h per (client, key) and replays it — always
                with HTTP 200, even if the original answer was 202 — without
                re-processing the request. ``accepted`` stays True on such a
                replay because it also looks at ``status`` and ``operation``.

        Returns:
            ``CreateTransactionResponse``. Check ``accepted`` (HTTP 202, or a
            PROGRAM_CALL / CONTRACT_CALL replayed as 200 ``PENDING``): the engine
            outcome is unknown; poll ``get(tx_id)`` and do **not** resubmit with the
            same ``reference_id``.

        Raises:
            ValueError: a required field for the chosen operation is missing.
            APIError: see module docstring for the typed subclasses.
        """
        if not hasattr(req, "to_body"):
            raise TypeError(
                "req must be a TransferRequest, ProgramCallRequest or ContractCallRequest"
            )
        body = req.to_body()
        headers: Dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        status, data = self._client._request_with_status("POST", PATH, body=body, headers=headers)
        return _create_response(status, data, str(getattr(req, "operation", "") or ""))

    def get(self, tx_id: str) -> Transaction:
        """``GET /api/v1/transactions/{tx_id}``."""
        if not tx_id:
            raise ValueError("tx_id is required")
        data = self._client._request("GET", f"{PATH}/{tx_id}")
        return _transaction(data)

    def list(self, req: Optional[ListTransactionsRequest] = None) -> PaginatedResponse[Transaction]:
        """``GET /api/v1/transactions`` — filters: ``wallet_id``, ``account_id``, ``chain``, ``page``, ``page_size``."""
        params: Dict[str, str] = {}
        if req:
            if req.wallet_id:
                params["wallet_id"] = req.wallet_id
            if req.account_id:
                params["account_id"] = req.account_id
            if req.chain:
                params["chain"] = req.chain
            if req.page > 0:
                params["page"] = str(req.page)
            if req.page_size > 0:
                params["page_size"] = str(req.page_size)
        data = self._client._request("GET", PATH, params=params)
        items = [_transaction(item) for item in data.get("data", []) or []]
        return PaginatedResponse(
            items=items,
            total=int(data.get("total", 0) or 0),
            has_more=bool(data.get("has_more", False)),
        )


def _create_response(http_status: int, data: Dict[str, Any], operation: str = "") -> CreateTransactionResponse:
    return CreateTransactionResponse(
        tx_id=str(data.get("tx_id", "") or ""),
        status=str(data.get("status", "") or ""),
        message=str(data.get("message", "") or ""),
        tx_hash=str(data.get("tx_hash", "") or ""),
        http_status=http_status,
        operation=operation,
    )


def _transaction(data: Dict[str, Any]) -> Transaction:
    return Transaction(
        tx_id=str(data.get("tx_id", "") or ""),
        wallet_id=str(data.get("wallet_id", "") or ""),
        client_id=str(data.get("client_id", "") or ""),
        chain=str(data.get("chain", "") or ""),
        transaction_type=str(data.get("transaction_type", "") or ""),
        from_address=str(data.get("from_address", "") or ""),
        to_address=str(data.get("to_address", "") or ""),
        token_symbol=str(data.get("token_symbol", "") or ""),
        amount=str(data.get("amount", "0") or "0"),
        status=str(data.get("status", "") or ""),
        tx_hash=str(data.get("tx_hash", "") or ""),
        risk_score=str(data.get("risk_score", "") or ""),
        risk_level=str(data.get("risk_level", "") or ""),
        created_at=str(data.get("created_at", "") or ""),
    )
