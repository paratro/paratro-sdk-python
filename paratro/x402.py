"""x402 facilitator service (``/api/v1/x402/*``).

Only the facilitator side of the x402 protocol is exposed: ``verify`` /
``settle`` / ``settle_status`` / ``list_settlements``. The payer-side
``POST /api/v1/x402/sign`` has been retired by the gateway (HTTP 410,
``type=endpoint_retired``) and is not available through this SDK.

``verify`` and ``settle`` take the Coinbase-compatible facilitator body as a
plain ``dict`` because its shape depends on ``x402Version``::

    {
      "x402Version": 1 | 2,
      "paymentPayload": {...},          # v1: {scheme, network, payload}; v2: {payload, accepted, resource?}
      "paymentRequirements": {...}      # v1 only
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from paratro.models import (
    ListX402SettlementsRequest,
    PaginatedResponse,
    X402Settlement,
    X402SettleResponse,
    X402SettleStatusResponse,
    X402VerifyResponse,
)

if TYPE_CHECKING:  # pragma: no cover
    from paratro.client import MPCClient

BASE = "/api/v1/x402"


class X402Service:
    """``client.x402`` — x402 facilitator endpoints."""

    def __init__(self, client: "MPCClient") -> None:
        self._client = client

    def verify(self, payload: Dict[str, Any]) -> X402VerifyResponse:
        """``POST /api/v1/x402/verify`` — validate a payment signature."""
        _require_facilitator_body(payload)
        data = self._client._request("POST", f"{BASE}/verify", body=payload)
        return X402VerifyResponse(
            is_valid=bool(data.get("isValid", False)),
            invalid_reason=data.get("invalidReason"),
            payer=str(data.get("payer", "") or ""),
        )

    def settle(self, payload: Dict[str, Any], idempotency_key: Optional[str] = None) -> X402SettleResponse:
        """``POST /api/v1/x402/settle`` — execute the on-chain settlement.

        ``idempotency_key`` sets the ``Idempotency-Key`` header; the gateway
        replays a cached 2xx response for 24 h per (client, key).
        """
        _require_facilitator_body(payload)
        headers: Dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        data = self._client._request("POST", f"{BASE}/settle", body=payload, headers=headers)
        return X402SettleResponse(
            success=bool(data.get("success", False)),
            tx_id=str(data.get("txId", "") or ""),
            transaction=str(data.get("transaction", "") or ""),
            error_reason=data.get("errorReason"),
            payer=str(data.get("payer", "") or ""),
            network=str(data.get("network", "") or ""),
        )

    def settle_status(self, tx_id: str) -> X402SettleStatusResponse:
        """``GET /api/v1/x402/settle/{tx_id}`` — status of a settlement transaction."""
        if not tx_id:
            raise ValueError("tx_id is required")
        data = self._client._request("GET", f"{BASE}/settle/{tx_id}")
        return X402SettleStatusResponse(
            success=bool(data.get("success", False)),
            tx_id=str(data.get("txId", "") or ""),
            status=str(data.get("status", "") or ""),
            tx_hash=str(data.get("txHash", "") or ""),
            network=str(data.get("network", "") or ""),
        )

    def list_settlements(
        self, req: Optional[ListX402SettlementsRequest] = None
    ) -> PaginatedResponse[X402Settlement]:
        """``GET /api/v1/x402/settlements`` — filters: ``status``, ``page``, ``page_size``."""
        params: Dict[str, str] = {}
        if req:
            if req.status:
                params["status"] = req.status
            if req.page > 0:
                params["page"] = str(req.page)
            if req.page_size > 0:
                params["page_size"] = str(req.page_size)
        data = self._client._request("GET", f"{BASE}/settlements", params=params)
        items = [_settlement(item) for item in data.get("data", []) or []]
        return PaginatedResponse(
            items=items,
            total=int(data.get("total", 0) or 0),
            has_more=bool(data.get("has_more", False)),
        )


def _require_facilitator_body(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    if payload.get("x402Version") not in (1, 2):
        raise ValueError("payload.x402Version must be 1 or 2")
    if "paymentPayload" not in payload:
        raise ValueError("payload.paymentPayload is required")


def _settlement(data: Dict[str, Any]) -> X402Settlement:
    return X402Settlement(
        tx_id=str(data.get("tx_id", "") or ""),
        chain=str(data.get("chain", "") or ""),
        from_address=str(data.get("from_address", "") or ""),
        to_address=str(data.get("to_address", "") or ""),
        amount=str(data.get("amount", "") or ""),
        status=str(data.get("status", "") or ""),
        valid_before=int(data.get("valid_before", 0) or 0),
        signature_v=data.get("signature_v"),
        signature_r=data.get("signature_r"),
        signature_s=data.get("signature_s"),
        created_at=str(data.get("created_at", "") or ""),
    )
