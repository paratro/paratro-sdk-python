"""operation=TRANSFER — asynchronous transfer signed by the MPC engine.

Run:  python examples/transfer.py
"""

from __future__ import annotations

import time

from paratro import APIError, TransactionStatus, TransferRequest

from _env import env, make_client

client = make_client()

try:
    result = client.transactions.create(TransferRequest(
        from_address=env("FROM_ADDRESS", "0xYourVaultAddress"),
        to_address=env("TO_ADDRESS", "0xRecipientAddress"),
        chain=env("CHAIN", "ethereum"),
        token_symbol=env("TOKEN_SYMBOL", "USDC"),
        amount=env("AMOUNT", "10.5"),          # human-readable decimal string
        memo="Invoice #1234",                    # optional, <= 100 chars
        reference_id=env("REFERENCE_ID", f"order-{int(time.time())}"),  # your business id; reused -> 400
    ))
except APIError as e:
    if e.is_duplicate_reference:
        raise SystemExit(f"reference_id already used: {e.message}")
    raise

# TRANSFER always answers 200 + PENDING: the engine signs asynchronously.
print(f"tx_id={result.tx_id} status={result.status} message={result.message!r}")
assert result.status == TransactionStatus.PENDING and result.tx_hash == ""

# Poll (or use the transaction.confirming / confirmed / failed webhooks).
tx = client.transactions.get(result.tx_id)
print(f"polled status={tx.status} tx_hash={tx.tx_hash or '-'}")
