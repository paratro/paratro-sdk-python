"""operation=PROGRAM_CALL — co-sign a counterparty-signed Solana transaction.

Run:  python examples/program_call.py
"""

from __future__ import annotations

import time

from paratro import ForbiddenError, ProgramCallRequest, RejectedError, RejectionReason

from _env import env, make_client

client = make_client()

try:
    result = client.transactions.create(ProgramCallRequest(
        from_address=env("FROM_ADDRESS", "YourSolanaPayerWallet"),
        chain="solana",
        signed_transaction=env("SIGNED_TRANSACTION", "AQIDBA=="),   # base64 or 0x-hex, partially signed
        receive_address=env("RECEIVE_ADDRESS", ""),                  # optional; default = from_address
        reference_id=env("REFERENCE_ID", f"quote-{int(time.time())}"),
    ))
except RejectedError as e:
    # 400 "Rejected: <tag>: <detail>" — fix the transaction or the policy; do not retry blindly.
    if e.reason_tag == RejectionReason.FEE_PAYER:
        raise SystemExit("our wallet must be in the fee-payer slot with an empty signature")
    if e.reason_tag in (RejectionReason.LIMIT_PER_TRANSACTION, RejectionReason.LIMIT_DAILY):
        raise SystemExit(f"over limit: {e.message}")
    raise SystemExit(f"rejected ({e.reason_tag}): {e.message}")
except ForbiddenError:
    raise SystemExit("no OPERATION_RULES policy authorises PROGRAM_CALL on solana for this client")

if result.accepted:
    # HTTP 202 (or a 200 PENDING replay): the engine did not answer in time. Poll by tx_id; never resend the same reference_id.
    print(f"accepted, outcome unknown: tx_id={result.tx_id} -> poll transactions.get()")
else:
    # HTTP 200: broadcast synchronously; tx_hash = signatures[0].
    print(f"broadcast: tx_id={result.tx_id} tx_hash={result.tx_hash}")
