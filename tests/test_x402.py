"""x402 facilitator endpoints (verify / settle / settle status / settlements)."""

from __future__ import annotations

import pytest

from paratro import ListX402SettlementsRequest, NotFoundError

V1_BODY = {
    "x402Version": 1,
    "paymentPayload": {
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": "0x" + "22" * 65,
            "authorization": {"from": "0xPayer", "to": "0xPayee", "value": "1000000",
                              "validAfter": "0", "validBefore": "1900000000", "nonce": "0x" + "33" * 32},
        },
    },
    "paymentRequirements": {"scheme": "exact", "network": "base-sepolia", "maxAmountRequired": "1000000",
                            "payTo": "0xPayee", "asset": "0xUSDC"},
}


def test_verify(gateway, client):
    gateway.queue.append((200, {"isValid": True, "payer": "0xPayer"}))
    out = client.x402.verify(V1_BODY)
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/x402/verify")
    assert call["body"] == V1_BODY
    assert out.is_valid is True and out.payer == "0xPayer" and out.invalid_reason is None


def test_verify_invalid_reason(gateway, client):
    gateway.queue.append((200, {"isValid": False, "invalidReason": "insufficient_funds"}))
    out = client.x402.verify(V1_BODY)
    assert out.is_valid is False and out.invalid_reason == "insufficient_funds"


def test_settle_with_idempotency_key(gateway, client):
    gateway.queue.append((200, {"success": True, "txId": "settle-1", "transaction": "0xtxhash",
                                "payer": "0xPayer", "network": "base-sepolia"}))
    out = client.x402.settle(V1_BODY, idempotency_key="settle-key-1")
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/x402/settle")
    assert call["headers"]["idempotency-key"] == "settle-key-1"
    assert call["body"] == V1_BODY
    assert out.success and out.tx_id == "settle-1" and out.transaction == "0xtxhash" and out.error_reason is None


def test_settle_failure_reason(gateway, client):
    gateway.queue.append((200, {"success": False, "transaction": "", "errorReason": "invalid_signature"}))
    out = client.x402.settle(V1_BODY)
    assert out.success is False and out.error_reason == "invalid_signature"
    assert "idempotency-key" not in gateway.api_calls()[0]["headers"]


def test_settle_status(gateway, client):
    gateway.queue.append((200, {"success": True, "txId": "settle-1", "status": "CONFIRMED",
                                "txHash": "0xabc", "network": "base-sepolia"}))
    out = client.x402.settle_status("settle-1")
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("GET", "/api/v1/x402/settle/settle-1")
    assert out.tx_id == "settle-1" and out.status == "CONFIRMED" and out.tx_hash == "0xabc"


def test_settle_status_404(gateway, client):
    gateway.queue.append((404, {"code": "not_found", "type": "not_found_error", "message": "settle transaction not found"}))
    with pytest.raises(NotFoundError):
        client.x402.settle_status("missing")


def test_list_settlements(gateway, client):
    gateway.queue.append((200, {"data": [{
        "tx_id": "s1", "chain": "base", "from_address": "0xPayer", "to_address": "0xPayee", "amount": "1000000",
        "status": "SETTLED", "valid_before": 1900000000, "signature_v": 27, "signature_r": "0xr", "signature_s": "0xs",
        "created_at": "2026-09-15T00:00:00Z"}], "total": 1, "has_more": False}))
    out = client.x402.list_settlements(ListX402SettlementsRequest(status="SETTLED", page=1, page_size=20))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("GET", "/api/v1/x402/settlements")
    assert sorted(call["query"].split("&")) == ["page=1", "page_size=20", "status=SETTLED"]
    s = out.items[0]
    assert s.tx_id == "s1" and s.status == "SETTLED" and s.valid_before == 1900000000 and s.signature_v == 27
    assert out.total == 1 and out.has_more is False


@pytest.mark.parametrize("bad", [{}, {"x402Version": 3, "paymentPayload": {}}, {"x402Version": 1}])
def test_facilitator_body_validation(gateway, client, bad):
    with pytest.raises(ValueError):
        client.x402.verify(bad)
    with pytest.raises(ValueError):
        client.x402.settle(bad)
    assert gateway.calls == []
