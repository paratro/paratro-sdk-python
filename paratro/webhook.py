"""Webhook signature verification and event parsing.

Usage::

    from paratro.webhook import verify_signature, parse_event

    # In your webhook handler:
    verify_signature(
        secret="your_webhook_secret",
        timestamp=request.headers["X-Paratro-Timestamp"],
        payload=request.body,
        signature=request.headers["X-Paratro-Signature"],
    )

    event = parse_event(request.json())
    if event.event_type == WebhookEventType.TRANSACTION_CONFIRMING:
        print(f"Transaction {event.txhash} confirming ({event.confirmations}/{event.required_confirmations})")
    elif event.event_type == WebhookEventType.TRANSACTION_CONFIRMED:
        print(f"Transaction {event.txhash} confirmed, amount: {event.amount}")
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Union

from paratro.errors import APIError
from paratro.models import WebhookEvent


DEFAULT_TOLERANCE = 300  # 5 minutes


def verify_signature(
    secret: str,
    timestamp: str,
    payload: Union[str, bytes],
    signature: str,
    tolerance: int = DEFAULT_TOLERANCE,
) -> None:
    """Verify a webhook signature using HMAC-SHA256.

    Args:
        secret: Your webhook secret (from Paratro dashboard).
        timestamp: Value of X-Paratro-Timestamp header.
        payload: Raw request body (bytes or string).
        signature: Value of X-Paratro-Signature header (e.g. "v1=abc123...").
        tolerance: Maximum allowed age in seconds (default: 300 = 5 minutes).

    Raises:
        APIError: If verification fails (invalid signature, expired timestamp, etc.)
    """
    # Validate timestamp
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        raise APIError(
            http_status=400,
            code="webhook_invalid_timestamp",
            error_type="webhook_error",
            message=f"Invalid timestamp: {timestamp}",
        )

    if tolerance > 0:
        age = abs(time.time() - ts)
        if age > tolerance:
            raise APIError(
                http_status=400,
                code="webhook_timestamp_expired",
                error_type="webhook_error",
                message=f"Timestamp too old (age: {int(age)}s, tolerance: {tolerance}s)",
            )

    # Build canonical string: {timestamp}.{body}
    if isinstance(payload, str):
        payload = payload.encode("utf-8")

    canonical = f"{timestamp}.".encode("utf-8") + payload

    # Compute expected signature
    mac = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256)
    expected = f"v1={mac.hexdigest()}"

    # Constant-time comparison
    if not hmac.compare_digest(expected, signature):
        raise APIError(
            http_status=400,
            code="webhook_signature_mismatch",
            error_type="webhook_error",
            message="Signature verification failed",
        )


def parse_event(data: dict) -> WebhookEvent:
    """Parse a webhook JSON payload into a WebhookEvent.

    Args:
        data: Parsed JSON body from the webhook request.

    Returns:
        WebhookEvent with all fields populated.
    """
    return WebhookEvent(
        event_id=data.get("event_id", ""),
        event_type=data.get("event_type", ""),
        event_time=data.get("event_time", ""),
        source_id=data.get("source_id", ""),
        wallet_id=data.get("wallet_id", ""),
        account_id=data.get("account_id", ""),
        status=data.get("status", ""),
        transaction_type=data.get("transaction_type", ""),
        chain=data.get("chain", ""),
        network=data.get("network", ""),
        txhash=data.get("txhash", ""),
        block_number=data.get("block_number", 0),
        from_addr=data.get("from", ""),
        to_addr=data.get("to", ""),
        symbol=data.get("symbol", ""),
        contract_address=data.get("contract_address", ""),
        amount=data.get("amount", "0"),
        decimals=data.get("decimals", 0),
        confirmations=data.get("confirmations", 0),
        required_confirmations=data.get("required_confirmations", 0),
        created_at=data.get("created_at", ""),
        confirmed_at=data.get("confirmed_at"),
        risk_checked=data.get("risk_checked", False),
        risk_score=data.get("risk_score", 0.0),
        risk_level=data.get("risk_level", ""),
        data=data.get("data", ""),
    )
