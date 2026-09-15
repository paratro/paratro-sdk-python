"""The scripts under examples/ (also shown in README) run unchanged against the fake gateway."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def run_example(gateway, name: str, extra_env=None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PARATRO_API_KEY": "fixture-key",
        "PARATRO_API_SECRET": "fixture-secret",
        "PARATRO_BASE_URL": gateway.base_url,
        "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1",
        "PYTHONPATH": str(EXAMPLES.parent),
        **(extra_env or {}),
    }
    return subprocess.run([sys.executable, str(EXAMPLES / name)], env=env, cwd=str(EXAMPLES),
                          capture_output=True, text=True, timeout=60)


def test_transfer_example(gateway):
    gateway.queue.extend([
        (200, {"tx_id": "tx-t1", "status": "PENDING", "message": "Transfer task created"}),
        (200, {"tx_id": "tx-t1", "status": "SIGNED", "tx_hash": ""}),
    ])
    proc = run_example(gateway, "transfer.py", {"REFERENCE_ID": "order-1"})
    assert proc.returncode == 0, proc.stderr
    assert "tx_id=tx-t1 status=PENDING" in proc.stdout
    assert "polled status=SIGNED" in proc.stdout
    create, get = gateway.api_calls()
    assert (create["method"], create["path"]) == ("POST", "/api/v1/transactions")
    assert create["body"]["operation"] == "TRANSFER" and create["body"]["reference_id"] == "order-1"
    assert (get["method"], get["path"]) == ("GET", "/api/v1/transactions/tx-t1")


def test_transfer_example_duplicate_reference(gateway):
    gateway.queue.append((400, {"code": "invalid_parameter", "type": "invalid_request_error",
                                "message": "Duplicate reference_id: this reference has already been used"}))
    proc = run_example(gateway, "transfer.py")
    assert proc.returncode == 1
    assert "reference_id already used" in proc.stderr


def test_program_call_example_broadcast(gateway):
    gateway.queue.append((200, {"tx_id": "tx-p1", "status": "BROADCAST", "message": "PROGRAM_CALL broadcast", "tx_hash": "5Sig"}))
    proc = run_example(gateway, "program_call.py", {"REFERENCE_ID": "quote-sol"})
    assert proc.returncode == 0, proc.stderr
    assert "broadcast: tx_id=tx-p1 tx_hash=5Sig" in proc.stdout
    body = gateway.api_calls()[0]["body"]
    assert body == {"operation": "PROGRAM_CALL", "reference_id": "quote-sol", "from_address": "YourSolanaPayerWallet",
                    "chain": "solana", "signed_transaction": "AQIDBA=="}


def test_program_call_example_202_and_rejection(gateway):
    gateway.queue.append((202, {"tx_id": "tx-p2", "status": "PENDING", "message": "PROGRAM_CALL accepted but ..."}))
    proc = run_example(gateway, "program_call.py")
    assert proc.returncode == 0, proc.stderr
    assert "accepted, outcome unknown: tx_id=tx-p2" in proc.stdout

    gateway.queue.append((400, {"code": "invalid_parameter", "type": "invalid_request_error",
                                "message": "Rejected: fee_payer: fee payer X is not our payer Y"}))
    proc = run_example(gateway, "program_call.py")
    assert proc.returncode == 1
    assert "fee-payer slot" in proc.stderr


def test_contract_call_example_broadcast(gateway):
    gateway.queue.append((200, {"tx_id": "tx-c1", "status": "BROADCAST", "message": "CONTRACT_CALL broadcast", "tx_hash": "0xhash"}))
    proc = run_example(gateway, "contract_call.py", {"REFERENCE_ID": "quote-evm", "EXPIRATION": "1789449058"})
    assert proc.returncode == 0, proc.stderr
    assert "broadcast: tx_id=tx-c1 tx_hash=0xhash" in proc.stdout
    body = gateway.api_calls()[0]["body"]
    assert body["operation"] == "CONTRACT_CALL" and body["reference_id"] == "quote-evm"
    assert body["contract_call"]["expiration"] == 1789449058
    assert set(body["contract_call"]) == {"quote_id", "expiration", "incoming", "outgoing", "counterparty_signature"}
    assert set(body["contract_call"]["incoming"]) == {"to", "token", "amount"}
    assert set(body["contract_call"]["outgoing"]) == {"from", "to", "token", "amount"}


def test_contract_call_example_202_then_poll(gateway):
    gateway.queue.extend([
        (202, {"tx_id": "tx-c2", "status": "PENDING", "message": "CONTRACT_CALL accepted but ..."}),
        (200, {"tx_id": "tx-c2", "status": "PENDING"}),
        (200, {"tx_id": "tx-c2", "status": "BROADCAST", "tx_hash": "0xlate"}),
    ])
    proc = run_example(gateway, "contract_call.py", {"POLL_INTERVAL": "0", "POLL_ATTEMPTS": "5"})
    assert proc.returncode == 0, proc.stderr
    assert "accepted, outcome unknown: tx_id=tx-c2" in proc.stdout
    assert "final: status=BROADCAST tx_hash=0xlate" in proc.stdout
    assert [c["path"] for c in gateway.api_calls()] == ["/api/v1/transactions"] + ["/api/v1/transactions/tx-c2"] * 2


@pytest.mark.parametrize("status, body, expect", [
    (400, {"code": "invalid_parameter", "type": "invalid_request_error", "message": "Rejected: expiration_passed: quote expired"}, "get a fresh quote"),
    (403, {"code": "forbidden", "type": "permission_error", "message": "operation not authorized by policy"}, "no OPERATION_RULES policy"),
    (404, {"code": "resource_not_found", "type": "not_found_error", "message": "no asset registered for token 0x59fb"}, "not credited yet"),
    # Engine busy: the row already exists (FAILED) and holds the reference → the example must say NEW.
    (503, {"code": "service_unavailable", "type": "api_error", "message": "Signing service is busy, retry later"}, "retry later with a NEW reference_id"),
    # Chain RPC / not enabled: raised before the insert → same reference_id is fine.
    (503, {"code": "service_unavailable", "type": "api_error", "message": "Chain RPC unavailable; cannot verify request"}, "retry later with the same reference_id"),
    (503, {"code": "service_unavailable", "type": "api_error", "message": "CONTRACT_CALL is not enabled on this gateway"}, "retry later with the same reference_id"),
])
def test_contract_call_example_error_paths(gateway, status, body, expect):
    gateway.queue.append((status, body))
    proc = run_example(gateway, "contract_call.py")
    assert proc.returncode == 1
    assert expect in proc.stderr


def test_contract_call_example_engine_busy_never_says_same_reference(gateway):
    gateway.queue.append((503, {"code": "service_unavailable", "type": "api_error", "message": "Signing service is busy, retry later"}))
    proc = run_example(gateway, "contract_call.py")
    assert proc.returncode == 1
    assert "same reference_id" not in proc.stderr


def test_contract_call_example_poll_stops_on_unlisted_terminal_status(gateway):
    # CANCELLED is written by the portal, not by the API path; the poll loop must still stop on it
    # instead of spinning until POLL_ATTEMPTS.
    gateway.queue.extend([
        (202, {"tx_id": "tx-c3", "status": "PENDING", "message": "CONTRACT_CALL accepted but ..."}),
        (200, {"tx_id": "tx-c3", "status": "SIGNED"}),
        (200, {"tx_id": "tx-c3", "status": "CANCELLED", "tx_hash": ""}),
    ])
    proc = run_example(gateway, "contract_call.py", {"POLL_INTERVAL": "0", "POLL_ATTEMPTS": "10"})
    assert proc.returncode == 0, proc.stderr
    assert "final: status=CANCELLED tx_hash=-" in proc.stdout
    assert [c["path"] for c in gateway.api_calls()] == ["/api/v1/transactions"] + ["/api/v1/transactions/tx-c3"] * 2
