"""Webhook payload parsing: ``operation`` on every event and ``swap_incoming`` on swaps.

Shapes are the ones paratro-mpc-message pins in internal/dispatcher/swap_webhook_test.go
and documents in paratro-docs features/webhooks.mdx (Swap events).
"""

from __future__ import annotations

import copy

from paratro import SwapAccountingStatus, SwapIncoming, WebhookEventType, WebhookOperation, parse_event

_BASE = {
    "event_id": "c4d5e6f7-0a1b-4c2d-8e3f-4a5b6c7d8e9f", "event_time": "2026-09-16T09:12:40Z",
    "source_id": "0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b", "wallet_id": "w-1", "account_id": "a-1",
    "chain": "ethereum", "network": "testnet", "txhash": "0xswap", "block_number": 10671204,
    "from": "0xpayer", "to": "0xcounterparty", "symbol": "USDC", "contract_address": "0xusdc",
    "amount": "10000000", "decimals": 6, "confirmations": 0, "required_confirmations": 6,
    "created_at": "2026-09-16T09:11:58Z", "confirmed_at": "2026-09-16T09:12:40Z",
    "risk_checked": False, "risk_score": 0, "risk_level": "UNSCANNED", "data": "",
}


def _event(**overrides):
    payload = copy.deepcopy(_BASE)
    payload.update(overrides)
    return payload


def test_swap_confirmed_carries_operation_and_booked_leg():
    event = parse_event(_event(
        event_type="transaction.confirmed", status="CONFIRMED", transaction_type="OUTBOUND",
        operation="CONTRACT_CALL",
        swap_incoming={"token_address": "0xa55a927f2211fe52188526ed7e779b7298646e75", "symbol": "AAPLx",
                       "amount": "42000000000000000", "decimals": 18, "booked": True,
                       "accounting_status": "APPLIED"},
    ))
    assert event.operation == WebhookOperation.CONTRACT_CALL == "CONTRACT_CALL"
    assert event.amount == "10000000", "the outgoing leg stays at the top level"
    leg = event.swap_incoming
    assert isinstance(leg, SwapIncoming)
    assert (leg.token_address, leg.symbol, leg.decimals) == ("0xa55a927f2211fe52188526ed7e779b7298646e75", "AAPLx", 18)
    assert leg.amount == "42000000000000000"
    assert leg.booked is True and leg.accounting_status == SwapAccountingStatus.APPLIED
    assert leg.reason is None and leg.audit_type is None, "a booked leg carries no reason/audit_type"


def test_swap_not_booked_carries_reason_audit_type_and_onchain_amount():
    event = parse_event(_event(
        event_type="transaction.confirmed", status="CONFIRMED", transaction_type="OUTBOUND",
        operation="PROGRAM_CALL",
        swap_incoming={"token_address": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "symbol": "",
                       "amount": "1500", "decimals": 0, "booked": False, "accounting_status": "REVIEW_REQUIRED",
                       "reason": "currency_code_not_found_or_inactive",
                       "audit_type": "SWAP_INCOMING_ASSET_UNREGISTERED"},
    ))
    assert event.operation == WebhookOperation.PROGRAM_CALL
    leg = event.swap_incoming
    assert leg.booked is False and leg.accounting_status == SwapAccountingStatus.REVIEW_REQUIRED
    assert leg.reason == "currency_code_not_found_or_inactive"
    assert leg.audit_type == "SWAP_INCOMING_ASSET_UNREGISTERED"
    assert leg.amount == "1500", "funds arrived but were not credited: the on-chain amount, not '0'"
    assert (leg.symbol, leg.decimals) == ("", 0), "an unregistered asset is not invented"


def test_swap_failed_is_not_applicable():
    event = parse_event(_event(
        event_type="transaction.failed", status="FAILED", transaction_type="OUTBOUND", confirmed_at="",
        operation="CONTRACT_CALL",
        swap_incoming={"token_address": "0xa55a927f2211fe52188526ed7e779b7298646e75", "symbol": "AAPLx",
                       "amount": "0", "decimals": 18, "booked": False, "accounting_status": "NOT_APPLICABLE",
                       "reason": "onchain_execution_failed"},
    ))
    assert event.event_type == WebhookEventType.TRANSACTION_FAILED
    leg = event.swap_incoming
    assert leg.booked is False and leg.accounting_status == SwapAccountingStatus.NOT_APPLICABLE
    assert leg.reason == "onchain_execution_failed" and leg.audit_type is None
    assert leg.amount == "0"


def test_non_swap_events_carry_operation_but_no_swap_incoming():
    cases = [
        ("transaction.confirmed", "OUTBOUND", WebhookOperation.TRANSFER),
        ("transaction.confirmed", "INBOUND", WebhookOperation.DEPOSIT),
        ("transfer.credited", "INTERNAL", WebhookOperation.TRANSFER),
        # x402 settlements are X402, not DEPOSIT (paratro-mpc-message webhook.ResolveOperation).
        ("x402.settlement.confirmed", "INBOUND", WebhookOperation.X402),
    ]
    for event_type, tx_type, operation in cases:
        event = parse_event(_event(event_type=event_type, status="CONFIRMED", transaction_type=tx_type,
                                   operation=operation))
        assert event.operation == operation, event_type
        assert event.swap_incoming is None, event_type


def test_legacy_payload_without_new_fields_still_parses():
    event = parse_event(_event(event_type="transaction.confirmed", status="CONFIRMED", transaction_type="OUTBOUND"))
    assert event.operation == ""
    assert event.swap_incoming is None
    # a malformed swap_incoming (not an object) is ignored rather than raising
    event = parse_event(_event(event_type="transaction.confirmed", status="CONFIRMED", transaction_type="OUTBOUND",
                               operation="CONTRACT_CALL", swap_incoming="oops"))
    assert event.swap_incoming is None
