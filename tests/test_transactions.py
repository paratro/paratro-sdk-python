"""POST /api/v1/transactions — wire format pinned to the gateway DTOs."""

from __future__ import annotations

import json

import pytest

import paratro
from paratro import (
    BadRequestError,
    ContractCall,
    ContractCallIncomingLeg,
    ContractCallOutgoingLeg,
    ContractCallRequest,
    CreateTransferRequest,
    EndpointRetiredError,
    ForbiddenError,
    ListTransactionsRequest,
    NotFoundError,
    Operation,
    ProgramCallRequest,
    RejectedError,
    RejectionReason,
    ServiceUnavailableError,
    TransferRequest,
)

FROM = "0x96586e99CE724F45bAb65cf963533b810147c1F4"
CP = "0xcf8a9d1e489c58f4c3d69b45380fb4a6c03ada47"
BUSDC = "0x59fb67f6778cff089484cf7115906725dfc44293"
AAPLX = "0xa55a927f2211fe52188526ed7e779b7298646e75"
QUOTE = "0x" + "ab" * 32
SIG = "0x" + "11" * 65


def transfer_req() -> TransferRequest:
    return TransferRequest(
        from_address=FROM, to_address=CP, chain="ethereum", token_symbol="USDC",
        amount="10.5", memo="Invoice #1234", reference_id="order-1001",
    )


def program_call_req() -> ProgramCallRequest:
    return ProgramCallRequest(
        from_address="PayerSoLana111111111111111111111111111111111",
        chain="solana",
        signed_transaction="AQIDBA==",
        receive_address="RecvSoLana1111111111111111111111111111111111",
        reference_id="quote-sol-1",
    )


def contract_call_req(permit_deadline=None) -> ContractCallRequest:
    return ContractCallRequest(
        from_address=FROM, chain="ethereum", receive_address=FROM, reference_id="quote-evm-1", memo="swap",
        contract_call=ContractCall(
            quote_id=QUOTE, expiration=1789449058,
            incoming=ContractCallIncomingLeg(to=CP, token=BUSDC, amount="10000000"),
            outgoing=ContractCallOutgoingLeg(from_=CP, to=FROM, token=AAPLX, amount="42000000000000000"),
            counterparty_signature=SIG, permit_deadline=permit_deadline,
        ),
    )


# ── wire format ──


def test_transfer_wire_format_and_response(gateway, client):
    gateway.queue.append((200, {"tx_id": "tx-1", "status": "PENDING", "message": "Transfer task created"}))
    out = client.transactions.create(transfer_req())

    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/transactions")
    assert call["headers"]["authorization"] == "Bearer tok-1"
    assert call["headers"]["content-type"] == "application/json"
    assert "idempotency-key" not in call["headers"]
    assert call["body"] == {
        "operation": "TRANSFER",
        "reference_id": "order-1001",
        "from_address": FROM,
        "to_address": CP,
        "chain": "ethereum",
        "token_symbol": "USDC",
        "amount": "10.5",
        "memo": "Invoice #1234",
    }
    assert out.tx_id == "tx-1" and out.status == "PENDING" and out.tx_hash == ""
    assert out.http_status == 200 and out.accepted is False and out.broadcast is False


def test_program_call_wire_format_and_broadcast(gateway, client):
    gateway.queue.append((200, {"tx_id": "tx-2", "status": "BROADCAST", "message": "PROGRAM_CALL broadcast",
                                "tx_hash": "5sig" * 8}))
    out = client.transactions.create(program_call_req())

    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/transactions")
    assert call["body"] == {
        "operation": "PROGRAM_CALL",
        "reference_id": "quote-sol-1",
        "from_address": "PayerSoLana111111111111111111111111111111111",
        "chain": "solana",
        "receive_address": "RecvSoLana1111111111111111111111111111111111",
        "signed_transaction": "AQIDBA==",
    }
    assert out.status == "BROADCAST" and out.tx_hash == "5sig" * 8 and out.broadcast is True
    assert out.accepted is False


def test_program_call_omits_receive_address_when_empty(gateway, client):
    gateway.queue.append((200, {"tx_id": "tx-2", "status": "BROADCAST", "message": "m", "tx_hash": "h"}))
    req = program_call_req()
    req.receive_address = ""
    req.reference_id = ""
    client.transactions.create(req)
    body = gateway.api_calls()[0]["body"]
    assert set(body) == {"operation", "from_address", "chain", "signed_transaction"}


def test_contract_call_wire_format_with_permit_deadline(gateway, client):
    gateway.queue.append((200, {"tx_id": "tx-3", "status": "BROADCAST", "message": "CONTRACT_CALL broadcast",
                                "tx_hash": "0x" + "cd" * 32}))
    out = client.transactions.create(contract_call_req(permit_deadline=1789449358))

    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/transactions")
    assert call["body"] == {
        "operation": "CONTRACT_CALL",
        "reference_id": "quote-evm-1",
        "from_address": FROM,
        "chain": "ethereum",
        "receive_address": FROM,
        "memo": "swap",
        "contract_call": {
            "quote_id": QUOTE,
            "expiration": 1789449058,
            "incoming": {"to": CP, "token": BUSDC, "amount": "10000000"},
            "outgoing": {"from": CP, "to": FROM, "token": AAPLX, "amount": "42000000000000000"},
            "counterparty_signature": SIG,
            "permit_deadline": 1789449358,
        },
    }
    # Numbers stay numbers, amounts stay strings — byte-level check of the raw body.
    raw = json.loads(call["raw"])
    assert isinstance(raw["contract_call"]["expiration"], int)
    assert isinstance(raw["contract_call"]["incoming"]["amount"], str)
    assert "contract_address" not in raw["contract_call"] and "value" not in raw["contract_call"]
    assert out.tx_hash == "0x" + "cd" * 32 and out.broadcast


def test_contract_call_omits_permit_deadline_when_none(gateway, client):
    gateway.queue.append((200, {"tx_id": "tx-3", "status": "BROADCAST", "message": "m", "tx_hash": "h"}))
    client.transactions.create(contract_call_req())
    cc = gateway.api_calls()[0]["body"]["contract_call"]
    assert "permit_deadline" not in cc
    assert set(cc) == {"quote_id", "expiration", "incoming", "outgoing", "counterparty_signature"}


def test_idempotency_key_header(gateway, client):
    gateway.queue.append((200, {"tx_id": "tx-1", "status": "PENDING", "message": "m"}))
    client.transactions.create(transfer_req(), idempotency_key="idem-abc")
    assert gateway.api_calls()[0]["headers"]["idempotency-key"] == "idem-abc"


# ── 202: engine outcome unknown ──


def test_202_accepted_is_distinguishable(gateway, client):
    msg = ("CONTRACT_CALL accepted but the signing engine did not answer in time; "
           "poll GET /api/v1/transactions/tx-9 for the outcome and do not resubmit with the same reference_id")
    gateway.queue.append((202, {"tx_id": "tx-9", "status": "PENDING", "message": msg}))
    out = client.transactions.create(contract_call_req())
    assert out.http_status == 202
    assert out.accepted is True
    assert out.status == "PENDING" and out.tx_id == "tx-9" and out.tx_hash == ""
    assert out.broadcast is False
    assert "do not resubmit" in out.message


def test_idempotency_replay_of_a_202_is_still_accepted(gateway, client):
    # middleware/idempotency.go replays a cached 2xx body with c.Data(200, …): the
    # original 202 PENDING comes back as HTTP 200 with the same body. For a
    # PROGRAM_CALL / CONTRACT_CALL that is still "outcome unknown".
    msg = ("CONTRACT_CALL accepted but the signing engine did not answer in time; "
           "poll GET /api/v1/transactions/tx-9 for the outcome and do not resubmit with the same reference_id")
    gateway.queue.append((200, {"tx_id": "tx-9", "status": "PENDING", "message": msg}))
    out = client.transactions.create(contract_call_req(), idempotency_key="idem-9")
    assert out.http_status == 200
    assert out.operation == Operation.CONTRACT_CALL
    assert out.accepted is True
    assert out.broadcast is False and out.tx_hash == ""


def test_transfer_200_pending_is_not_accepted_and_carries_operation(gateway, client):
    gateway.queue.append((200, {"tx_id": "tx-1", "status": "PENDING", "message": "Transfer task created"}))
    out = client.transactions.create(transfer_req())
    assert out.operation == Operation.TRANSFER
    assert out.accepted is False

    gateway.queue.append((200, {"tx_id": "tx-2", "status": "BROADCAST", "message": "m", "tx_hash": "h"}))
    out = client.transactions.create(program_call_req())
    assert out.operation == Operation.PROGRAM_CALL
    assert out.accepted is False and out.broadcast is True


def test_accepted_rule_without_a_client():
    from paratro import CreateTransactionResponse
    pending = dict(tx_id="t", status="PENDING", message="")
    assert CreateTransactionResponse(**pending, http_status=202, operation="").accepted is True
    assert CreateTransactionResponse(**pending, http_status=200, operation="CONTRACT_CALL").accepted is True
    assert CreateTransactionResponse(**pending, http_status=200, operation="PROGRAM_CALL").accepted is True
    assert CreateTransactionResponse(**pending, http_status=200, operation="TRANSFER").accepted is False
    # Hand-built value with no operation: cannot be classified as accepted.
    assert CreateTransactionResponse(**pending, http_status=200).accepted is False
    assert CreateTransactionResponse(tx_id="t", status="BROADCAST", message="", tx_hash="h",
                                     http_status=200, operation="CONTRACT_CALL").accepted is False


# ── error mapping ──


def test_400_rejected_reason_tag(gateway, client):
    gateway.queue.append((400, {"code": "invalid_parameter", "type": "invalid_request_error",
                                "message": "Rejected: expiration_passed: quote expired at 1789449058"}))
    with pytest.raises(RejectedError) as ei:
        client.transactions.create(contract_call_req())
    err = ei.value
    assert err.http_status == 400 and err.code == "invalid_parameter"
    assert err.is_rejected
    assert err.reason_tag == "expiration_passed" == RejectionReason.EXPIRATION_PASSED
    assert err.reason_tag in RejectionReason.CONTRACT_CALL_TAGS


def test_400_rejected_solana_tag(gateway, client):
    gateway.queue.append((400, {"code": "invalid_parameter", "type": "invalid_request_error",
                                "message": "Rejected: fee_payer: fee payer X is not our payer Y; the engine signs the fee-payer slot"}))
    with pytest.raises(RejectedError) as ei:
        client.transactions.create(program_call_req())
    assert ei.value.reason_tag == RejectionReason.FEE_PAYER
    assert ei.value.reason_tag in RejectionReason.PROGRAM_CALL_TAGS


def test_400_duplicate_reference_id(gateway, client):
    gateway.queue.append((400, {"code": "invalid_parameter", "type": "invalid_request_error",
                                "message": "Duplicate reference_id: this reference has already been used"}))
    with pytest.raises(BadRequestError) as ei:
        client.transactions.create(transfer_req())
    assert ei.value.is_duplicate_reference and not ei.value.is_rejected
    assert ei.value.reason_tag is None


def test_400_transaction_failed_engine_tag(gateway, client):
    gateway.queue.append((400, {"code": "transaction_failed", "type": "business_error",
                                "message": "CONTRACT_CALL failed: limit_daily"}))
    with pytest.raises(BadRequestError) as ei:
        client.transactions.create(contract_call_req())
    assert ei.value.code == "transaction_failed"
    assert ei.value.reason_tag == "limit_daily"


def test_400_transaction_failed_generic_has_no_tag(gateway, client):
    gateway.queue.append((400, {"code": "transaction_failed", "type": "business_error",
                                "message": "PROGRAM_CALL failed: engine rejected the transaction"}))
    with pytest.raises(BadRequestError) as ei:
        client.transactions.create(program_call_req())
    assert ei.value.reason_tag is None


def test_400_insufficient_balance(gateway, client):
    gateway.queue.append((400, {"code": "insufficient_balance", "type": "business_error", "message": "Insufficient balance"}))
    with pytest.raises(BadRequestError) as ei:
        client.transactions.create(transfer_req())
    assert ei.value.code == "insufficient_balance"


def test_400_unsupported_operation_x402(gateway, client):
    # The SDK cannot even build an X402 request; a hand-crafted body gets the gateway's answer.
    gateway.queue.append((400, {"code": "invalid_parameter", "type": "invalid_request_error",
                                "message": "Unsupported operation: only TRANSFER, PROGRAM_CALL and CONTRACT_CALL are available"}))
    with pytest.raises(BadRequestError) as ei:
        client._request("POST", "/api/v1/transactions", body={"operation": "X402", "from_address": FROM, "chain": "ethereum"})
    assert ei.value.message.startswith("Unsupported operation")


def test_403_no_policy(gateway, client):
    gateway.queue.append((403, {"code": "forbidden", "type": "permission_error",
                                "message": "operation not authorized by policy"}))
    with pytest.raises(ForbiddenError) as ei:
        client.transactions.create(program_call_req())
    assert ei.value.http_status == 403 and paratro.is_forbidden(ei.value)


def test_404_asset_not_registered(gateway, client):
    gateway.queue.append((404, {"code": "resource_not_found", "type": "not_found_error",
                                "message": "no asset registered for token 0x59fb…"}))
    with pytest.raises(NotFoundError) as ei:
        client.transactions.create(contract_call_req())
    assert paratro.is_not_found(ei.value)


def test_503_engine_busy_consumes_reference_id(gateway, client):
    gateway.queue.append((503, {"code": "service_unavailable", "type": "api_error",
                                "message": "Signing service is busy, retry later"}))
    with pytest.raises(ServiceUnavailableError) as ei:
        client.transactions.create(contract_call_req())
    assert paratro.is_service_unavailable(ei.value)
    # Row inserted, then marked FAILED with the reference kept → a resend collides.
    assert ei.value.is_engine_busy and ei.value.reference_id_consumed and paratro.is_engine_busy(ei.value)
    gateway.queue.append((400, {"code": "invalid_parameter", "type": "invalid_request_error",
                                "message": "Duplicate reference_id: this reference has already been used"}))
    with pytest.raises(BadRequestError) as dup:
        client.transactions.create(contract_call_req())
    assert dup.value.is_duplicate_reference


@pytest.mark.parametrize("message", [
    "Chain RPC unavailable; cannot verify request",
    "CONTRACT_CALL is not enabled on this gateway",
])
def test_503_before_insert_leaves_reference_id_free(gateway, client, message):
    gateway.queue.append((503, {"code": "service_unavailable", "type": "api_error", "message": message}))
    with pytest.raises(ServiceUnavailableError) as ei:
        client.transactions.create(contract_call_req())
    assert not ei.value.is_engine_busy and not ei.value.reference_id_consumed
    assert not paratro.is_engine_busy(ei.value)


def test_403_transfer_address_blacklisted(gateway, client):
    gateway.queue.append((403, {"code": "address_blacklisted", "type": "permission_error",
                                "message": "Destination address is blacklisted"}))
    with pytest.raises(ForbiddenError) as ei:
        client.transactions.create(transfer_req())
    assert ei.value.is_address_blacklisted and ei.value.code == "address_blacklisted"


def test_410_retired_endpoint_mapping(gateway, client):
    gateway.queue.append((410, {"code": "invalid_parameter", "type": "endpoint_retired",
                                "message": "This endpoint has been retired. Use POST /api/v1/transactions (operation=TRANSFER)."}))
    with pytest.raises(EndpointRetiredError) as ei:
        client._request("POST", "/api/v1/transfer", body={})
    assert ei.value.http_status == 410 and ei.value.error_type == "endpoint_retired"
    assert paratro.is_endpoint_retired(ei.value)
    assert "POST /api/v1/transactions" in ei.value.message


# ── 1.x compatibility ──


def test_create_transfer_wrapper_hits_unified_entry(gateway, client):
    gateway.queue.append((200, {"tx_id": "tx-1", "status": "PENDING", "message": "Transfer task created"}))
    out = client.create_transfer(CreateTransferRequest(
        from_address=FROM, to_address=CP, chain="ethereum", token_symbol="USDC", amount="10.5",
    ))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/transactions")
    assert call["body"]["operation"] == Operation.TRANSFER
    assert set(call["body"]) == {"operation", "from_address", "to_address", "chain", "token_symbol", "amount"}
    assert out.tx_id == "tx-1" and out.status == "PENDING"
    assert CreateTransferRequest is TransferRequest


def test_create_transfer_rejects_other_operations(client):
    with pytest.raises(TypeError):
        client.create_transfer(program_call_req())  # type: ignore[arg-type]


# ── client-side validation happens before any HTTP call ──


@pytest.mark.parametrize("req, missing", [
    (TransferRequest(from_address=FROM, chain="ethereum", token_symbol="USDC", amount="1"), "to_address"),
    (TransferRequest(from_address=FROM, to_address=CP, chain="ethereum", amount="1"), "token_symbol"),
    (TransferRequest(from_address=FROM, to_address=CP, chain="ethereum", token_symbol="USDC"), "amount"),
    (ProgramCallRequest(from_address=FROM, chain="solana"), "signed_transaction"),
    (ContractCallRequest(from_address=FROM, chain="ethereum"), "contract_call.quote_id"),
])
def test_missing_required_fields_raise_before_request(gateway, client, req, missing):
    with pytest.raises(ValueError, match=missing):
        client.transactions.create(req)
    assert gateway.calls == []


def test_create_rejects_non_request_objects(client):
    with pytest.raises(TypeError):
        client.transactions.create({"operation": "TRANSFER"})  # type: ignore[arg-type]


# ── GET / list ──


def test_get_transaction(gateway, client):
    gateway.queue.append((200, {
        "tx_id": "tx-1", "wallet_id": "w", "client_id": "c", "chain": "ethereum", "transaction_type": "OUTBOUND",
        "from_address": FROM, "to_address": CP, "token_symbol": "USDC", "amount": "10.5", "status": "CONFIRMED",
        "tx_hash": "0xhash", "risk_score": "12.5", "risk_level": "LOW", "created_at": "2026-09-15T00:00:00Z",
    }))
    tx = client.transactions.get("tx-1")
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("GET", "/api/v1/transactions/tx-1")
    assert tx.tx_id == "tx-1" and tx.status == "CONFIRMED" and tx.tx_hash == "0xhash"
    assert tx.risk_score == "12.5" and tx.risk_level == "LOW"
    assert not hasattr(tx, "direction") and not hasattr(tx, "block_number") and not hasattr(tx, "confirmations")


def test_get_transaction_alias_and_404(gateway, client):
    gateway.queue.append((404, {"code": "not_found", "type": "not_found_error", "message": "Transaction not found"}))
    with pytest.raises(NotFoundError):
        client.get_transaction("nope")


def test_list_transactions_query(gateway, client):
    gateway.queue.append((200, {"data": [{"tx_id": "a", "status": "PENDING"}, {"tx_id": "b", "status": "BROADCAST"}],
                                "total": 7, "has_more": True}))
    out = client.transactions.list(ListTransactionsRequest(wallet_id="w1", account_id="a1", chain="solana", page=2, page_size=2))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("GET", "/api/v1/transactions")
    assert sorted(call["query"].split("&")) == ["account_id=a1", "chain=solana", "page=2", "page_size=2", "wallet_id=w1"]
    assert [t.tx_id for t in out.items] == ["a", "b"] and out.total == 7 and out.has_more is True


def test_list_transactions_alias_without_filters(gateway, client):
    gateway.queue.append((200, {"data": [], "total": 0, "has_more": False}))
    out = client.list_transactions()
    assert gateway.api_calls()[0]["query"] == "" and out.items == []


# ── things that must NOT exist any more ──


def test_x402_sign_does_not_exist(client):
    assert not hasattr(client, "x402_sign")
    assert not hasattr(client, "create_x402_sign")
    assert not hasattr(client.x402, "sign")
    assert not hasattr(paratro, "X402SignRequest")
    assert not hasattr(paratro, "X402SignResponse")


def test_rolled_back_draft_surface_does_not_exist(client):
    for name in ("get_transaction_by_external_tx_id", "list_asset_changes", "list_transaction_operations",
                 "list_security_factors", "add_security_factor", "delete_security_factor", "set_security_factor_status"):
        assert not hasattr(client, name), name
    for name in ("X402OperationRequest", "ListAssetChangesRequest", "SecurityFactorItem", "ListSecurityFactorResponse"):
        assert not hasattr(paratro, name), name
    for req in (transfer_req(), program_call_req(), contract_call_req()):
        body = req.to_body()
        assert "external_tx_id" not in body and "extra_parameters" not in body
    assert not hasattr(Operation, "X402")
