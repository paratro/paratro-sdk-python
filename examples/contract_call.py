"""operation=CONTRACT_CALL — EVM AtomicSwap executeSwap with an EIP-2612 permit.

Run:  python examples/contract_call.py
"""

from __future__ import annotations

import time

from paratro import (
    ContractCall,
    ContractCallIncomingLeg,
    ContractCallOutgoingLeg,
    ContractCallRequest,
    ForbiddenError,
    NotFoundError,
    RejectedError,
    RejectionReason,
    ServiceUnavailableError,
    TransactionStatus,
)

from _env import env, make_client

client = make_client()

OUR_WALLET = env("FROM_ADDRESS", "0x96586e99CE724F45bAb65cf963533b810147c1F4")
COUNTERPARTY = env("COUNTERPARTY", "0xcf8a9d1e489c58f4c3d69b45380fb4a6c03ada47")

request = ContractCallRequest(
    from_address=OUR_WALLET,                  # our paying wallet = incoming payer = permit owner
    chain="ethereum",
    receive_address=OUR_WALLET,               # our receiving wallet = outgoing.to (default: from_address)
    reference_id=env("REFERENCE_ID", f"quote-{int(time.time())}"),
    contract_call=ContractCall(
        quote_id=env("QUOTE_ID", "0x" + "ab" * 32),                 # bytes32 hex
        expiration=int(env("EXPIRATION", str(int(time.time()) + 120))),  # unix seconds, in the future
        # amounts are smallest-unit integer strings (bUSDC has 6 decimals: "10000000" = 10 bUSDC)
        incoming=ContractCallIncomingLeg(to=COUNTERPARTY, token=env("PAY_TOKEN", "0x59fb67f6778cff089484cf7115906725dfc44293"), amount="10000000"),
        outgoing=ContractCallOutgoingLeg(from_=COUNTERPARTY, to=OUR_WALLET, token=env("TARGET_TOKEN", "0xa55a927f2211fe52188526ed7e779b7298646e75"), amount="42000000000000000"),
        counterparty_signature=env("COUNTERPARTY_SIGNATURE", "0x" + "11" * 65),  # EIP-712, verified by the contract
        # permit_deadline=None -> gateway default now + min(max_permit_lifetime_seconds, 300)
    ),
    # No contract address here: the gateway takes it from the policy's allowed_contracts[chain]. Native value is always 0.
)

try:
    result = client.transactions.create(request)
except RejectedError as e:
    # 400 "Rejected: <tag>: <detail>"; e.reason_tag is one of RejectionReason.CONTRACT_CALL_TAGS
    if e.reason_tag in (RejectionReason.EXPIRATION_PASSED, RejectionReason.EXPIRATION_TOO_FAR):
        raise SystemExit("get a fresh quote: " + e.message)
    if e.reason_tag in (RejectionReason.COUNTERPARTY_NOT_REGISTERED, RejectionReason.PAYMENT_TOKEN_NOT_REGISTERED,
                        RejectionReason.TARGET_TOKEN_NOT_REGISTERED):
        raise SystemExit("policy does not allow this counterparty/token: " + e.message)
    raise SystemExit(f"rejected ({e.reason_tag}): {e.message}")
except ForbiddenError:
    raise SystemExit("no OPERATION_RULES policy authorises CONTRACT_CALL on ethereum")
except NotFoundError as e:
    raise SystemExit("address/asset not ours or token not credited yet: " + e.message)
except ServiceUnavailableError as e:
    if e.is_engine_busy:
        # The row was inserted before the engine answered BUSY and still holds this reference_id
        # (FAILED — or held PENDING until the permit deadline if the permit was already signed), so a
        # resend with the same value gets 400 Duplicate reference_id.
        raise SystemExit("engine busy: row keeps the reference_id, retry later with a NEW reference_id: " + e.message)
    # "Chain RPC unavailable" / "<OP> is not enabled": nothing was recorded.
    raise SystemExit("chain RPC down / not enabled, retry later with the same reference_id: " + e.message)

if result.accepted:
    # HTTP 202 -> {"tx_id","status":"PENDING"} (or its Idempotency-Key replay as 200 PENDING): the engine did not answer in time.
    # Poll by tx_id; do NOT resubmit with the same reference_id (it would hit the uniqueness constraint).
    print(f"accepted, outcome unknown: tx_id={result.tx_id}")
    for _ in range(int(env("POLL_ATTEMPTS", "10"))):
        tx = client.transactions.get(result.tx_id)
        # The status set is not closed (portal / chain-watcher write the same column), so stop on
        # anything that is no longer in flight instead of enumerating the "good" values.
        if not TransactionStatus.is_in_flight(tx.status):
            print(f"final: status={tx.status} tx_hash={tx.tx_hash or '-'}")
            break
        time.sleep(float(env("POLL_INTERVAL", "3")))
else:
    # HTTP 200 -> {"tx_id","status":"BROADCAST","tx_hash"}
    print(f"broadcast: tx_id={result.tx_id} tx_hash={result.tx_hash}")
