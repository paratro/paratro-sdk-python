# Changelog

## Unreleased

### ⚠️ Breaking

- **The gateway base URL is required and always explicit.** `Config.sandbox()`, `Config.production()`
  and `Config.custom()` are removed; `Config(base_url)` is the only constructor. Paratro now runs
  private deployments next to its cloud, so the SDK carries no gateway address of its own — the
  Paratro cloud endpoints are listed only in the README (Configuration) and in this migration table:

  | 1.8.1 | 1.9.0 |
  |---|---|
  | `Config.sandbox()` | `Config("https://api-sandbox.paratro.com")` |
  | `Config.production()` | `Config("https://api.paratro.com")` |
  | `Config.custom("https://your-gateway")` | `Config("https://your-gateway")` |
  | private deployment | `Config("https://<gateway-host>")` — the address your operations team gives you |

- `MPCClient(...)` validates the base URL: it must be non-empty and start with `http://` or `https://`
  (a trailing slash is dropped); otherwise the constructor raises
  `ValueError("base URL must be an absolute http(s) URL, e.g. https://<gateway-host> (Paratro cloud or your private gateway)")`
  (`paratro.config.BASE_URL_ERROR`). Building the `Config` itself never raises. Same rule in the Go
  and Rust SDKs (`paratro.NewConfig(baseURL)` / `Config::new(base_url)`).
- `examples/_env.py` requires `PARATRO_BASE_URL` (it used to default to the Paratro sandbox).

### Added

- `WebhookEvent.operation` — the message service now puts `operation` on every webhook event
  (`TRANSFER` / `PROGRAM_CALL` / `CONTRACT_CALL` for `OUTBOUND`, `DEPOSIT` for deposits, `X402` for
  `x402.settlement.confirmed`, `TRANSFER` for `transfer.credited`); `WebhookOperation` names the values.
- `WebhookEvent.swap_incoming: Optional[SwapIncoming]` — the counter-asset leg of a `PROGRAM_CALL` /
  `CONTRACT_CALL` swap on `transaction.confirmed` / `transaction.failed`: `token_address`, `symbol`,
  `amount`, `decimals`, `booked`, `accounting_status` (`SwapAccountingStatus.APPLIED` /
  `REVIEW_REQUIRED` / `NOT_APPLICABLE`) plus `reason` / `audit_type` when not booked. `None` on every
  other event. `SwapIncoming`, `SwapAccountingStatus` and `WebhookOperation` are exported from `paratro`.

Both fields are additive: payloads without them still parse (`operation == ""`, `swap_incoming is None`).

## 1.8.1 — 2026-09-15

Aligns the SDK with the gateway's unified transactions entry. Everything below was verified against the
gateway source (`paratro-mpc-gateway` develop, `api/dto/dto.go`, `api/handler/transaction_handler.go`,
`api/router/*.go`, `common/errors.go`, `middleware/`). The package keeps its name and import path
(`paratro-sdk` / `from paratro import …`) and stays in the 1.x line, but **1.8.1 is not a purely
additive release** — read the ⚠️ Breaking section before upgrading.

### ⚠️ Breaking

- **`POST /api/v1/transfer` is retired (HTTP 410).** `MPCClient.create_transfer()` is kept as a
  compatibility wrapper and now sends `POST /api/v1/transactions` with `operation=TRANSFER`. The request
  shape is unchanged; `reference_id` was added.
- **`POST /api/v1/x402/sign` is retired (HTTP 410).** There is no payer-side x402 signing in the API any
  more; `operation=X402` on the unified entry answers `400 Unsupported operation`. This SDK never exposed a
  sign method, and 1.8.1 deliberately does not add one. The facilitator endpoints (`verify`, `settle`,
  `settle/{tx_id}`, `settlements`) are now available under `client.x402`.
- **`Transaction`** lost `direction`, `block_number`, `confirmations` (the gateway never returned them) and
  gained `risk_score`, `risk_level` — matching `dto.TransactionResponse`.
- **Security-factor methods removed** (`list_security_factors`, `add_security_factor`,
  `delete_security_factor`, `set_security_factor_status`, `SecurityFactorItem`,
  `ListSecurityFactorResponse`). `/api/v1/client/security-factors` lives on the portal API (`appapi`) behind a
  portal user session + MFA, not on the gateway; calling it with a gateway JWT could never succeed.
- `CreateTransferRequest.amount` default changed from `"0"` to `""`; `amount` is required and validated
  client-side before any request is sent.
- **Default HTTP timeout is 200 s (`paratro.DEFAULT_TIMEOUT`), was 30 s.** `PROGRAM_CALL` /
  `CONTRACT_CALL` are synchronous: the gateway's engine budget is 120 s, it waits 150 s (budget + 30 s
  broadcast margin) for the engine before answering `202`, and its server write timeout closes the
  connection at 180 s. A client that gives up before the gateway loses the `tx_id` while the row
  already exists under the `reference_id`, so the default sits above the write timeout (150 s would
  be cut off exactly when the gateway answers `202`). Pass `MPCClient(..., timeout=...)` to change it;
  the same timeout applies to `POST /api/v1/auth/token`. Same default as the Go
  (`paratro.DefaultTimeout`) and Rust (`config::DEFAULT_TIMEOUT`) SDKs.

### Added

- `client.transactions` service: `create(request, idempotency_key=None)`, `get(tx_id)`, `list(req)`.
- Request types, field names identical to the JSON:
  - `TransferRequest(from_address, to_address, chain, token_symbol, amount, memo, reference_id)`
  - `ProgramCallRequest(from_address, chain, signed_transaction, receive_address, reference_id, memo)`
  - `ContractCallRequest(from_address, chain, contract_call, receive_address, reference_id, memo)` with
    `ContractCall(quote_id, expiration, incoming{to,token,amount}, outgoing{from,to,token,amount},
    counterparty_signature, permit_deadline)`
- `CreateTransactionResponse(tx_id, status, message, tx_hash, http_status, operation)` with `.accepted`
  (engine outcome unknown, poll by `tx_id`, do not resubmit the same `reference_id`) and `.broadcast`.
  `TransferResponse` is an alias. `.accepted` is `http_status == 202` **or** a `PROGRAM_CALL` /
  `CONTRACT_CALL` whose `status` is `PENDING` — the gateway replays an `Idempotency-Key` hit with HTTP
  200 even when the original answer was 202, and those operations never answer `PENDING` otherwise.
  `operation` is SDK-filled from the request. Same rule as `Accepted()` in the Go SDK.
- `Operation` and `TransactionStatus` constants. `TransactionStatus` also carries the portal / chain-watcher
  values that `GET /transactions` can return (`PENDING_APPROVAL`, `REJECTED`, `CANCELLED`,
  `COMPLIANCE_BLOCKED`) and `TransactionStatus.is_in_flight(status)` for poll loops — the status set is not
  closed, poll while in flight instead of switching on an exhaustive "done" set.
- Optional `Idempotency-Key` header support on `transactions.create` and `x402.settle`.
- Typed errors: `RejectedError` (400 `"Rejected: <tag>: …"`), `BadRequestError`, `AuthenticationError`,
  `ForbiddenError` (403), `NotFoundError` (404), `ConflictError` (409), `EndpointRetiredError` (410),
  `RateLimitError` (429), `ServiceUnavailableError` (503). All subclass `APIError`.
- `APIError.reason_tag` (machine tag from `Rejected: <tag>` and `<OPERATION> failed: <tag>` messages),
  `APIError.is_rejected`, `APIError.is_duplicate_reference`.
- `ServiceUnavailableError.is_engine_busy` / `.reference_id_consumed` and the `is_engine_busy()` predicate.
  The gateway inserts the transaction row **before** calling the engine and `uk_client_reference` covers
  FAILED rows, so the engine-busy 503 (`"Signing service is busy, retry later"`) and
  `400 transaction_failed` leave your `reference_id` taken — resubmit with a new one. That row ends up FAILED, or —
  for a CONTRACT_CALL whose EIP-2612 permit was already signed — held PENDING with the reservation locked
  until the permit deadline (a retry can see `insufficient_balance` meanwhile). Only the chain-RPC /
  not-enabled 503s happen before the insert and may be retried with the same `reference_id`. README section
  "Which errors consume `reference_id`" spells out every case.
- `ForbiddenError.is_address_blacklisted` — a TRANSFER to a blacklisted destination answers
  `403 code=address_blacklisted`, not a policy problem.
- `RejectionReason` constants: `CONTRACT_CALL_TAGS`, `PROGRAM_CALL_TAGS`, `REJECTED_TAGS` (their union —
  the `400 "Rejected: <tag>"` vocabulary), `ENGINE_FAILURE_TAGS` (38 engine verdicts behind
  `400 transaction_failed "<OPERATION> failed: <tag>"`: every literal in `mpc-engine internal/syncsettle`
  plus the `CONTRACT_CALL` permit step `internal/syncsign/permit.go` — `permit_owner_mismatch`,
  `permit_spender_mismatch`, `permit_value_mismatch`, `permit_digest_mismatch`, `permit_digest_missing`,
  `permit_domain_mismatch`, `permit_domain_unverified`, `permit_params_invalid`, `permit_token_mismatch`,
  `permit_token_not_registered`, …) and `ALL_TAGS` (everything). The sets are the literals in the code
  at release time, not a closed vocabulary. Same values as the Go `Reason*` constants and
  `paratro_sdk::reason_tag` in Rust. `ErrorCode`, `ErrorType`.
- `RejectedError` docstring / README: a `400 Rejected` is normally pre-insert, but the `CONTRACT_CALL`
  post-sign re-verification rejects after the row was inserted (held `PENDING` until the permit
  deadline, `reference_id` consumed) — retry a rejected `CONTRACT_CALL`, if at all, with a new
  `reference_id`.
- Predicates `is_rejected`, `is_forbidden`, `is_endpoint_retired`, `is_service_unavailable`,
  `is_engine_busy`, `is_token_expired`.
- `client.x402`: `verify`, `settle`, `settle_status`, `list_settlements` + `X402VerifyResponse`,
  `X402SettleResponse`, `X402SettleStatusResponse`, `X402Settlement`, `ListX402SettlementsRequest`.
- `WebhookEventType.TRANSFER_CREDITED` (`transfer.credited`) and `WebhookEventType.X402_SETTLEMENT_CONFIRMED`
  (`x402.settlement.confirmed`, recipient side of an x402 settlement) — the complete set emitted by
  paratro-mpc-message.
- `CreateWalletRequest.threshold` / `total_shares` / `signing_party_ids` (optional, omitted when `None`;
  gateway default 2-of-3).
- Automatic re-authentication + single retry on `401 token_expired`.
- HTTP redirects are no longer followed (credentials / signed bodies are never forwarded).
- `MPCClient(..., timeout=200)` parameter and `paratro.DEFAULT_TIMEOUT`.
- `examples/` (transfer, program_call, contract_call) executed by the test suite against a loopback fake
  gateway; `tests/` rewritten around that fake gateway. `tests/test_docs.py` guards the README / docstrings
  against re-introducing the "a 503 leaves the same `reference_id` retryable" claim.

### Not covered

- x402 resource endpoints (`GET /api/v1/x402/paid-resources/{id}`, `/x402/resources`,
  `/x402/resources/{id}/receipts`) are not wrapped; use `client._request` or plain HTTP.

### Migration 1.6 → 1.8.1

```python
# 1.6
from paratro import CreateTransferRequest
resp = client.create_transfer(CreateTransferRequest(from_address=..., to_address=..., chain=...,
                                                    token_symbol=..., amount="10.5"))

# 1.8.1 — identical wire behaviour, preferred spelling
from paratro import TransferRequest
resp = client.transactions.create(TransferRequest(from_address=..., to_address=..., chain=...,
                                                  token_symbol=..., amount="10.5", reference_id="order-1"))
```

- If you called `POST /api/v1/x402/sign` through your own HTTP code: it now returns 410 and there is no
  replacement — the gateway no longer issues x402 payer authorizations.
- If you read `Transaction.direction`, switch to `transaction_type`; drop `block_number` /
  `confirmations` (use webhooks for confirmation progress).
- If you used the security-factor methods, call the portal API with a portal session instead.
- New callers of PROGRAM_CALL / CONTRACT_CALL must handle `result.accepted` (202) and `RejectedError`.

## 1.6.0

- Renamed whitelist → security factors.

## 1.5.0 and earlier

See git history.
