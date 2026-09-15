# Paratro MPC Wallet Gateway Python SDK

[![PyPI version](https://img.shields.io/pypi/v/paratro-sdk.svg)](https://pypi.org/project/paratro-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/paratro-sdk.svg)](https://pypi.org/project/paratro-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Official Python SDK for the [Paratro](https://paratro.com) MPC Wallet Gateway.

> **1.8.1 is not a purely additive release.** `POST /api/v1/transfer` and `POST /api/v1/x402/sign` were
> retired by the gateway (HTTP 410). All transactions now go through `POST /api/v1/transactions` with an
> `operation` field. See [Migrating from 1.6 and earlier](#migrating-from-16-and-earlier) and the
> **⚠️ Breaking** section of [CHANGELOG.md](CHANGELOG.md).

## Features

- **MPC Wallets / Accounts / Assets** — create and manage wallets, per-chain accounts and tokens
- **Unified transactions entry** — `client.transactions.create()` with three operations:
  - `TRANSFER` — asynchronous transfer signed by the MPC engine
  - `PROGRAM_CALL` — co-sign a counterparty-signed Solana transaction (xChange swap shape)
  - `CONTRACT_CALL` — EVM AtomicSwap `executeSwap` with an EIP-2612 permit
- **Typed errors** — `{code,type,message}` parsed into `RejectedError` / `ForbiddenError` / `NotFoundError` /
  `ServiceUnavailableError` / `EndpointRetiredError` …, with `reason_tag` for `400 "Rejected: <tag>: …"`
- **x402 facilitator** — `verify` / `settle` / `settle_status` / `list_settlements`
- **Webhooks** — HMAC signature verification + event parsing
- **Auth handled for you** — JWT from `X-API-Key` / `X-API-Secret`, refreshed before expiry; a
  `401 token_expired` re-authenticates once and retries once. Thread-safe.

## Installation

```bash
pip install paratro-sdk
```

**Requirements:** Python 3.9+, `requests`.

## Quick Start

```python
from paratro import MPCClient, Config, TransferRequest, APIError

client = MPCClient("your-api-key", "your-api-secret", Config.sandbox())

result = client.transactions.create(TransferRequest(
    from_address="0xYourVaultAddress",
    to_address="0xRecipient",
    chain="ethereum",
    token_symbol="USDC",
    amount="10.5",               # human-readable decimal string, max 18 decimals
    reference_id="order-1001",   # your business id; reusing it -> 400 Duplicate reference_id
))
print(result.tx_id, result.status)  # status is PENDING: the engine signs asynchronously

tx = client.transactions.get(result.tx_id)
print(tx.status, tx.tx_hash)
```

Runnable versions of every snippet below live in [`examples/`](examples/) and are executed by the test
suite against a fake gateway (`tests/test_examples.py`).

## Configuration

```python
from paratro import Config

Config.sandbox()                          # https://api-sandbox.paratro.com
Config.production()                       # https://api.paratro.com
Config.custom("https://your-gateway")     # anything else
```

### HTTP timeout

`MPCClient(api_key, api_secret, config, timeout=200)` — the timeout (seconds) bounds every HTTP
exchange, the auth call included, and defaults to `paratro.DEFAULT_TIMEOUT` = **200 s**.
`PROGRAM_CALL` / `CONTRACT_CALL` are synchronous: the gateway holds the connection while the engine
signs and broadcasts — engine budget 120 s, it waits 150 s (budget + 30 s margin) for the engine
before answering `202`, and its server write timeout closes the connection at 180 s. The default
sits **above the 180 s write timeout** so the gateway, never the SDK, is the side that gives up: a
slow engine ends in a `202` with a `tx_id` instead of a client-side timeout. If the SDK gave up
first you would lose the `tx_id` while the row already exists under your `reference_id` (a resend
answers `400 Duplicate reference_id`, and the API cannot search by `reference_id`); 150 s is
exactly when the gateway answers `202`, so it is not enough. Keep the default for clients that
send those two operations; a shorter value is fine for a client that only reads or sends
`TRANSFER`. Same default as the Go (`paratro.DefaultTimeout`) and Rust
(`config::DEFAULT_TIMEOUT`) SDKs.

## Authentication

1. The first call sends `POST /api/v1/auth/token` with headers `X-API-Key` / `X-API-Secret` and receives
   `{"token", "expires_in", "token_type", "client": {...}}`.
2. The JWT is cached and sent as `Authorization: Bearer <jwt>`. It is refreshed 2 minutes before the
   `expires_in` the gateway returned (do not hard-code the lifetime; the gateway decides it).
3. A `401 token_expired` answer triggers exactly one re-authentication and one retry of the failed request.
   Any other 401 (`unauthorized`, `invalid_token`) is raised as `AuthenticationError` without retry.
4. The caller's IP must be in the client's IP allowlist, otherwise the token endpoint answers `403`.
5. The client never follows HTTP redirects (credentials and signed bodies are not forwarded).

## Transactions — `POST /api/v1/transactions`

One endpoint; the `operation` field selects what happens. Common fields: `operation`, `reference_id`
(idempotency — the same client may not reuse it), `from_address`, `chain`, `memo` (≤ 100 chars).

| operation | request type | success |
|---|---|---|
| `TRANSFER` | `TransferRequest` | `200 {tx_id, status:"PENDING", message}` |
| `PROGRAM_CALL` | `ProgramCallRequest` | `200 {tx_id, status:"BROADCAST", message, tx_hash}` or `202 {tx_id, status:"PENDING", message}` |
| `CONTRACT_CALL` | `ContractCallRequest` | same as PROGRAM_CALL |

`create()` returns `CreateTransactionResponse(tx_id, status, message, tx_hash, http_status, operation)`
with `.accepted` (`http_status == 202`, or a `PROGRAM_CALL` / `CONTRACT_CALL` with `status == "PENDING"` —
see [Handling 202](#handling-202-engine-outcome-unknown)) and `.broadcast` (`status == "BROADCAST"`).
`operation` is filled in by the SDK from the request; the gateway does not echo it.

### TRANSFER

```python
from paratro import TransferRequest

result = client.transactions.create(TransferRequest(
    from_address="0xYourVaultAddress",
    to_address="0xRecipient",
    chain="ethereum",
    token_symbol="USDC",
    amount="10.5",
    memo="Invoice #1234",
    reference_id="order-1001",
))
# result.status == "PENDING", result.tx_hash == ""  -> poll transactions.get() or use webhooks
```

`create_transfer(CreateTransferRequest(...))` from 1.6 still exists and sends exactly this request.

### PROGRAM_CALL (Solana)

```python
from paratro import ProgramCallRequest

result = client.transactions.create(ProgramCallRequest(
    from_address="YourSolanaPayerWallet",     # must be in the fee-payer slot with an empty signature
    chain="solana",
    signed_transaction="<base64 or 0x-hex>",  # counterparty-signed, exactly Memo + 2x TransferChecked, no ALT
    receive_address="",                       # optional; default = from_address
    reference_id="quote-42",
))
if result.accepted:
    print("engine outcome unknown, poll", result.tx_id)   # HTTP 202 — do NOT resend with the same reference_id
else:
    print("broadcast", result.tx_hash)                    # tx_hash = signatures[0]
```

### CONTRACT_CALL (EVM `executeSwap`)

```python
from paratro import (ContractCall, ContractCallIncomingLeg, ContractCallOutgoingLeg,
                     ContractCallRequest)

OUR_WALLET = "0x96586e99CE724F45bAb65cf963533b810147c1F4"
COUNTERPARTY = "0xcf8a9d1e489c58f4c3d69b45380fb4a6c03ada47"

result = client.transactions.create(ContractCallRequest(
    from_address=OUR_WALLET,          # our paying wallet = incoming payer = permit owner = tx sender
    chain="ethereum",
    receive_address=OUR_WALLET,       # our receiving wallet = outgoing.to (default: from_address)
    reference_id="quote-0xabc…",
    contract_call=ContractCall(
        quote_id="0x" + "ab" * 32,                       # bytes32 hex
        expiration=1789449058,                            # unix seconds, must be in the future
        incoming=ContractCallIncomingLeg(                 # we pay the counterparty
            to=COUNTERPARTY, token="0x59fb…(bUSDC)", amount="10000000"),        # smallest-unit integer strings
        outgoing=ContractCallOutgoingLeg(                 # the counterparty pays us
            from_=COUNTERPARTY, to=OUR_WALLET, token="0xa55a…(AAPLx)", amount="42000000000000000"),
        counterparty_signature="0x<65 bytes>",           # EIP-712 signature, verified by the contract
        permit_deadline=None,                             # optional; default now + min(max_permit_lifetime_seconds, 300)
    ),
))
```

The contract address is **not** a request field — the gateway takes it from the OPERATION_RULES policy
(`call_rules.allowed_contracts[chain]`). Native value is always 0.

Wire format sent for the request above:

```json
{
  "operation": "CONTRACT_CALL",
  "reference_id": "quote-0xabc…",
  "from_address": "0x9658…",
  "chain": "ethereum",
  "receive_address": "0x9658…",
  "contract_call": {
    "quote_id": "0xabab…",
    "expiration": 1789449058,
    "incoming":  { "to": "0xcf8a…", "token": "0x59fb…", "amount": "10000000" },
    "outgoing":  { "from": "0xcf8a…", "to": "0x9658…", "token": "0xa55a…", "amount": "42000000000000000" },
    "counterparty_signature": "0x…"
  }
}
```

### Handling 202 (engine outcome unknown)

For `PROGRAM_CALL` / `CONTRACT_CALL` the gateway may answer **HTTP 202** with `status="PENDING"`: the
signing engine did not answer in time and the transaction may or may not have been broadcast. The row
exists, so:

```python
result = client.transactions.create(request)
if result.accepted:                              # 202, or its Idempotency-Key replay as 200 PENDING
    tx = client.transactions.get(result.tx_id)   # poll while TransactionStatus.is_in_flight(tx.status)
    # do NOT call create() again with the same reference_id — it would be rejected as a duplicate
```

`accepted` is `True` for HTTP 202, and also for a `PROGRAM_CALL` / `CONTRACT_CALL` answered
`200 PENDING` — those operations never answer `PENDING` otherwise, and that is exactly how an
`Idempotency-Key` replay of a 202 arrives (the gateway replays cached bodies with HTTP 200). A
`TRANSFER`'s normal `200 PENDING` is not "accepted". Same rule as `Accepted()` in the Go SDK and
`is_accepted()` in the Rust SDK.

### Which errors consume `reference_id`

The gateway inserts the transaction row **before** it talks to the signing engine, and the unique key
behind `400 Duplicate reference_id` (`uk_client_reference`) also covers FAILED rows. So whether you may
resend with the same `reference_id` depends on *where* the request failed, not on the HTTP status alone:

| Answer | Row | `reference_id` |
|---|---|---|
| `400 "Rejected: …"` from the pre-checks, `400 insufficient_balance`, `403`, `404`, `503 "Chain RPC unavailable; cannot verify request"`, `503 "<OP> is not enabled on this gateway"` | not written | free — retry with the same value |
| `400 "Rejected: …"` from the CONTRACT_CALL post-sign re-verification (gateway `contract_call.go` re-runs `VerifyExecuteSwap` after the permit was signed and the row inserted) | PENDING, held until the permit deadline | taken — indistinguishable from a pre-check rejection in the response, so after a rejected CONTRACT_CALL retry, if at all, with a **new** `reference_id`; the retry can see `insufficient_balance` while the reservation is held |
| `202` | PENDING | taken — poll `tx_id`, never resubmit |
| `400 transaction_failed` (`"<OP> failed: <tag>"`) | FAILED (PENDING, held until the permit deadline, if the CONTRACT_CALL permit was already signed) | taken — submit again with a **new** `reference_id` |
| `503 "Signing service is busy, retry later"` (`ServiceUnavailableError.is_engine_busy`) | FAILED (PENDING, held until the permit deadline, if the CONTRACT_CALL permit was already signed) | taken — submit again with a **new** `reference_id` |
| `500` | unknown (some are raised after the insert) | resend with the same value; a `400 Duplicate reference_id` tells you the first attempt did create a row |

The engine-busy 503 body carries no `tx_id`, and `GET /transactions` has no `reference_id` filter (the
field is not returned either), so the leftover row can only be located by listing the wallet's recent
transactions. "Held" means the gateway keeps the row PENDING with its reservation locked because a signed
EIP-2612 permit for those funds is still valid; the reconciler releases it (→ FAILED) once the permit
deadline has passed and the on-chain nonce shows the permit was not used, so a retry with a new
`reference_id` can see `insufficient_balance` until then. TRANSFER never answers 503.

### Idempotency-Key (optional)

`create(request, idempotency_key="...")` sets the `Idempotency-Key` header. The gateway caches a 2xx
response for 24 h per (client, key) and replays it — always as HTTP 200, even if the original answer was
202 — without re-processing. `accepted` stays `True` on such a replay because it also looks at `status`
and `operation`, not only at `http_status`. `reference_id` remains the business-level guard
(`400 Duplicate reference_id`).

### Querying

```python
from paratro import ListTransactionsRequest

tx = client.transactions.get("tx_id")
page = client.transactions.list(ListTransactionsRequest(wallet_id="…", account_id="…", chain="ethereum",
                                                        page=1, page_size=20))
for tx in page.items:
    print(tx.tx_id, tx.transaction_type, tx.status, tx.tx_hash, tx.risk_level)
```

**Transaction fields:** `tx_id`, `wallet_id`, `client_id`, `chain`, `transaction_type`, `from_address`,
`to_address`, `token_symbol`, `amount`, `status`, `tx_hash`, `risk_score`, `risk_level`, `created_at`

**Statuses** (`TransactionStatus`): the API create path moves through `PENDING` → `SIGNED` → `BROADCAST` →
`CONFIRMING` → `CONFIRMED` | `FAILED`. The list is **not closed** — `GET /transactions` returns
`pto_transactions.status` verbatim and the same rows are also written by the portal and the chain watcher,
so `PENDING_APPROVAL`, `REJECTED`, `CANCELLED` (portal approval flow) and `COMPLIANCE_BLOCKED` (held inbound
deposits) can appear. Poll while `TransactionStatus.is_in_flight(status)` (`PENDING` / `SIGNED` /
`PENDING_APPROVAL`) instead of switching on an exhaustive set of "done" values; on-chain finality is
`CONFIRMED` / `FAILED` (or the webhooks).

## Error Handling

Every error body is `{"code", "type", "message"}`; the SDK raises `APIError` (or a subclass) carrying
`http_status`, `code`, `error_type`, `message`.

| HTTP | Exception | When |
|---|---|---|
| 400 `"Rejected: <tag>: …"` | `RejectedError` | policy / verifier rejection — inspect `reason_tag`. Normally pre-insert; the CONTRACT_CALL post-sign re-verification also rejects after the row exists (row held PENDING until the permit deadline, `reference_id` consumed) |
| 400 other | `BadRequestError` | validation, `Duplicate reference_id` (`is_duplicate_reference`), `insufficient_balance`, `transaction_failed` (row FAILED — or held PENDING after a signed CONTRACT_CALL permit — `reference_id` consumed, use a new one), `Unsupported operation` (X402) |
| 401 | `AuthenticationError` | `token_expired` is retried once automatically; `unauthorized` / `invalid_token` are not |
| 403 | `ForbiddenError` | PROGRAM_CALL / CONTRACT_CALL: no OPERATION_RULES policy authorises this operation/chain (`code=forbidden`); TRANSFER: destination address blacklisted (`code=address_blacklisted`, `is_address_blacklisted`); token endpoint: IP not allowed / client suspended |
| 404 | `NotFoundError` | address / asset not this client's, token not credited yet, unknown tx_id |
| 409 | `ConflictError` | `conflict` / `resource_exists` |
| 410 | `EndpointRetiredError` | `POST /api/v1/transfer`, `POST /api/v1/x402/sign` (`type=endpoint_retired`) |
| 429 | `RateLimitError` | `too_many_requests` / `api_quota_exceeded` |
| 503 | `ServiceUnavailableError` | `"Chain RPC unavailable; cannot verify request"` / `"<OP> is not enabled on this gateway"`: nothing recorded, retry later with the **same** `reference_id`. `"Signing service is busy, retry later"` (`is_engine_busy`): the row exists (FAILED, or held PENDING after a signed CONTRACT_CALL permit) and keeps your `reference_id`, retry with a **new** one. See [Which errors consume `reference_id`](#which-errors-consume-reference_id) |

```python
from paratro import (APIError, RejectedError, ForbiddenError, NotFoundError,
                     ServiceUnavailableError, RejectionReason)

try:
    result = client.transactions.create(request)
except RejectedError as e:
    # e.reason_tag is the machine-readable tag, e.g. "expiration_passed"
    if e.reason_tag in (RejectionReason.EXPIRATION_PASSED, RejectionReason.EXPIRATION_TOO_FAR):
        ...  # get a fresh quote
    elif e.reason_tag in (RejectionReason.LIMIT_PER_TRANSACTION, RejectionReason.LIMIT_DAILY):
        ...  # over the policy limit
    else:
        raise
except ForbiddenError:
    ...  # configure an OPERATION_RULES policy (AUTO_APPROVE) in the portal
except NotFoundError as e:
    ...  # e.message, e.g. "no asset registered for token 0x…"
except ServiceUnavailableError as e:
    if e.is_engine_busy:
        ...  # row exists (FAILED, or held PENDING) and holds this reference_id: back off, then resubmit with a NEW reference_id
    else:
        ...  # chain RPC down / operation not enabled: nothing recorded, back off and retry as is
except APIError as e:
    print(e.http_status, e.code, e.error_type, e.message)
```

`APIError.reason_tag` also parses `400 code=transaction_failed "<OPERATION> failed: <tag>"` (the engine
rejected after the row was created); it is `None` when the gateway collapsed the reason to
`"engine rejected the transaction"`.

**Rejection tags** (`RejectionReason`, verified against the gateway and verifier sources; `REJECTED_TAGS`
is the union of the two lists below, `ENGINE_FAILURE_TAGS` the engine verdicts, `ALL_TAGS` everything):

- CONTRACT_CALL: `abi` `amount_not_positive` `calldata` `calldata_not_canonical` `contract_address`
  `counterparty_not_registered` `expiration` `expiration_passed` `expiration_too_far` `incoming_from`
  `limit_daily` `limit_decimals_ambiguous` `limit_not_configured` `limit_per_transaction` `outgoing_to`
  `payment_token_not_registered` `permit_deadline` `permit_deadline_passed` `permit_deadline_too_far`
  `permit_owner` `selector` `target_token_not_registered` `value_not_zero`
- PROGRAM_CALL: `account_unresolvable` `alt_not_allowed` `ata_derivation` `counterparty_not_registered`
  `counterparty_signature_invalid` `counterparty_signature_missing` `fee_payer` `incoming_destination`
  `limit_daily` `limit_decimals_ambiguous` `limit_not_configured` `limit_per_transaction` `malformed`
  `mint_not_registered` `mint_program_unknown` `outgoing_authority` `outgoing_source`
  `payer_signature_present` `policy_invalid` `program_not_allowed` `program_unresolvable` `shape`
- `400 transaction_failed` engine verdicts (`ENGINE_FAILURE_TAGS`, 38 values — every literal in
  `mpc-engine internal/syncsettle` and, for the EIP-2612 permit a CONTRACT_CALL signs first,
  `internal/syncsign/permit.go`; the engine also re-runs the verifiers, so the tags above can appear
  here too): `calldata_invalid` `contract_address_invalid` `contract_not_registered` `cosignature_invalid`
  `daily_allowance_missing` `daily_usage_unavailable` `internal` `mint_token_program_unresolved`
  `payer_invalid` `payer_mismatch` `permit_digest_mismatch` `permit_digest_missing`
  `permit_domain_mismatch` `permit_domain_unverified` `permit_owner_mismatch` `permit_params_invalid`
  `permit_spender_mismatch` `permit_token_mismatch` `permit_token_not_registered`
  `permit_value_mismatch` `policy_not_authorized` `receiver_invalid` `receiver_lookup_failed`
  `receiver_missing` `receiver_not_ours` `request_digest_mismatch` `request_digest_missing` `signer_slot`

The sets are the literals in the code at release time, not a closed vocabulary: a new gateway / engine
release can add tags, and TSS / broadcast failures arrive without one (`engine rejected the
transaction`). Match on the tags you handle and treat an unknown tag as a rejection you have not seen yet.

The pre-1.8 predicates `is_not_found`, `is_rate_limited`, `is_auth_error` remain; `is_rejected`,
`is_forbidden`, `is_endpoint_retired`, `is_service_unavailable`, `is_engine_busy`, `is_token_expired` were added.

## Wallets, Accounts, Assets

```python
from paratro import CreateWalletRequest, CreateAccountRequest, CreateAssetRequest

wallet = client.create_wallet(CreateWalletRequest(wallet_name="Treasury", description="Primary"))
# Wallets are created asynchronously: poll get_wallet() until status == key_status == "ACTIVE".
# Signing quorum is 2-of-3 by default; override with threshold= / total_shares= (threshold <= total_shares,
# otherwise 400) and optionally pin the hot signers with signing_party_ids=[...] (len == threshold, unique).

account = client.create_account(CreateAccountRequest(
    wallet_id=wallet.wallet_id,
    chain="ethereum",
    account_type="OUTBOUND",   # optional: INBOUND | OUTBOUND
    label="Hot wallet",        # optional
))

asset = client.create_asset(CreateAssetRequest(
    account_id=account.account_id,
    symbol="USDC",             # ETH TRX USDT USDC BNB MATIC POL BTC SOL MNT
    chain="ethereum",          # required for EVM accounts
))

client.list_wallets(); client.get_wallet(id)
client.list_accounts(ListAccountsRequest(wallet_id=...)); client.get_account(id)
client.list_assets(ListAssetsRequest(account_id=...)); client.get_asset(id)
```

**Wallet:** `wallet_id`, `client_id`, `wallet_name`, `description`, `status`, `key_status`, `created_at`, `updated_at`
**Account:** `account_id`, `wallet_id`, `client_id`, `address`, `network`, `address_type`, `label`, `status`, `created_at`
**Asset:** `asset_id`, `account_id`, `wallet_id`, `client_id`, `chain`, `network`, `symbol`, `name`, `contract_address`,
`decimals`, `asset_type`, `balance`, `locked_balance`, `is_active`, `created_at`

`chain` values are the lowercase chain names registered in the gateway's chain registry (e.g. `ethereum`,
`bsc`, `polygon`, `arbitrum`, `optimism`, `tron`, `bitcoin`, `solana`). EVM chains share one key
derivation and therefore one address per wallet.

## x402 facilitator

The payer-side `POST /api/v1/x402/sign` has been retired (410) and is **not** in this SDK. The
facilitator endpoints are:

```python
from paratro import ListX402SettlementsRequest

body = {"x402Version": 1, "paymentPayload": {...}, "paymentRequirements": {...}}   # Coinbase-compatible

v = client.x402.verify(body)                     # POST /api/v1/x402/verify  -> is_valid, invalid_reason, payer
s = client.x402.settle(body, idempotency_key="k1")# POST /api/v1/x402/settle  -> success, tx_id, transaction, error_reason, payer, network
st = client.x402.settle_status(s.tx_id)          # GET  /api/v1/x402/settle/{tx_id} -> success, tx_id, status, tx_hash, network
page = client.x402.list_settlements(ListX402SettlementsRequest(status="SETTLED", page=1, page_size=20))
```

The x402 resource endpoints (`GET /api/v1/x402/paid-resources/{resource_id}`, `GET /api/v1/x402/resources`,
`GET /api/v1/x402/resources/{resource_id}/receipts`) exist on the gateway but are not wrapped by this SDK
yet; call them with `client._request("GET", path, params=...)` or plain HTTP with the same bearer token.

## Webhooks

```python
from paratro import verify_signature, parse_event, WebhookEventType

verify_signature(
    secret="your_webhook_secret",
    timestamp=request.headers["X-Paratro-Timestamp"],
    payload=request.data,                                   # raw body bytes
    signature=request.headers["X-Paratro-Signature"],       # "v1=<hex HMAC-SHA256 of '{ts}.{body}'>"
)
event = parse_event(request.json)

if event.event_type == WebhookEventType.TRANSACTION_CONFIRMING: ...
elif event.event_type == WebhookEventType.TRANSACTION_CONFIRMED: ...
elif event.event_type == WebhookEventType.TRANSACTION_FAILED: ...
elif event.event_type == WebhookEventType.TRANSFER_CREDITED: ...   # internal transfer credited, transaction_type=INTERNAL
elif event.event_type == WebhookEventType.X402_SETTLEMENT_CONFIRMED: ...   # x402 settlement credited to the recipient
```

| Event | Description |
|---|---|
| `transaction.confirming` | detected on-chain, awaiting confirmations |
| `transaction.confirmed` | fully confirmed (balance credited for deposits) |
| `transaction.failed` | failed on-chain |
| `transfer.credited` | a Paratro-to-Paratro transfer was credited to the receiving account (`transaction_type=INTERNAL`) |
| `x402.settlement.confirmed` | recipient side of an x402 settlement (`client.x402.settle`) confirmed on-chain and credited (`status=CONFIRMED`, `transaction_type=INBOUND`) |

**WebhookEvent fields:** `event_id`, `event_type`, `event_time`, `source_id`, `wallet_id`, `account_id`,
`status`, `transaction_type`, `chain`, `network`, `txhash`, `block_number`, `from_addr` (`from`),
`to_addr` (`to`), `symbol`, `contract_address`, `amount`, `decimals`, `confirmations`,
`required_confirmations`, `created_at`, `confirmed_at`, `risk_checked`, `risk_score`, `risk_level`, `data`

## Migrating from 1.6 and earlier

The package name and import path do not change (`pip install -U paratro-sdk`, `from paratro import …`).

| 1.6 | 1.8.1 |
|---|---|
| `client.create_transfer(CreateTransferRequest(...))` → `POST /api/v1/transfer` | still works, now sends `POST /api/v1/transactions` with `operation=TRANSFER`. New code: `client.transactions.create(TransferRequest(...))` |
| `POST /api/v1/x402/sign` | retired by the gateway (410). No replacement in the API; `operation=X402` on the unified entry answers `400 Unsupported operation` |
| `Transaction.direction / block_number / confirmations` | removed (never returned by the gateway); `risk_score`, `risk_level` added |
| `list_security_factors / add_security_factor / delete_security_factor / set_security_factor_status` | removed — these are portal (`appapi`) endpoints authenticated with a portal user session, not gateway API-key endpoints; they never worked against `Config.sandbox()/production()` |
| `TransferResponse` | alias of `CreateTransactionResponse` (adds `tx_hash`, `http_status`, `operation`, `accepted`) |
| `MPCClient(..., timeout=30)` implicit 1.6 default | default is now `200` (`paratro.DEFAULT_TIMEOUT`, above the gateway's 180 s write timeout); pass `timeout=` to change it |
| `APIError` | unchanged attributes; typed subclasses and `reason_tag` added |

See [CHANGELOG.md](CHANGELOG.md) for the full list.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e . pytest
python -m pytest -q          # unit tests + examples against a loopback fake gateway (no network)
```

## Related SDKs

| Language | Package | Repository |
|----------|---------|------------|
| Go | `github.com/paratro/paratro-sdk-go` | [paratro-sdk-go](https://github.com/paratro/paratro-sdk-go) |
| Rust | `paratro-sdk` | [paratro-sdk-rust](https://github.com/paratro/paratro-sdk-rust) |
| Python | `paratro-sdk` | [paratro-sdk-python](https://github.com/paratro/paratro-sdk-python) |

## Support

- Documentation: https://docs.paratro.com
- Email: hello@paratro.com
- Issues: https://github.com/paratro/paratro-sdk-python/issues

## License

MIT — see [LICENSE](LICENSE).
