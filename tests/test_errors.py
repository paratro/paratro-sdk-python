"""APIError parsing, typed subclasses and reason tags (no HTTP)."""

from __future__ import annotations

import re

import pytest

from paratro import (
    APIError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    EndpointRetiredError,
    ErrorCode,
    ErrorType,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    RejectedError,
    RejectionReason,
    ServiceUnavailableError,
    is_auth_error,
    is_endpoint_retired,
    is_engine_busy,
    is_forbidden,
    is_not_found,
    is_rate_limited,
    is_rejected,
    is_service_unavailable,
)


def body(code, type_, message):
    return {"code": code, "type": type_, "message": message}


@pytest.mark.parametrize("status, payload, cls", [
    (400, body("invalid_parameter", "invalid_request_error", "Invalid request parameters"), BadRequestError),
    (400, body("invalid_parameter", "invalid_request_error", "Rejected: shape: transaction has no signers"), RejectedError),
    (401, body("token_expired", "authentication_error", "Token expired"), AuthenticationError),
    (403, body("forbidden", "permission_error", "operation not authorized by policy"), ForbiddenError),
    (404, body("resource_not_found", "not_found_error", "account not found"), NotFoundError),
    (409, body("resource_exists", "conflict_error", "exists"), ConflictError),
    (410, body("invalid_parameter", "endpoint_retired", "This endpoint has been retired. Use POST /api/v1/transactions (operation=X402)."), EndpointRetiredError),
    (429, body("too_many_requests", "rate_limit_error", "slow down"), RateLimitError),
    (503, body("service_unavailable", "api_error", "Chain RPC unavailable; cannot verify request"), ServiceUnavailableError),
    (500, body("internal_error", "api_error", "Failed to create CONTRACT_CALL"), APIError),
])
def test_from_response_picks_subclass(status, payload, cls):
    err = APIError.from_response(status, payload)
    assert type(err) is cls
    assert isinstance(err, APIError)
    assert (err.http_status, err.code, err.error_type, err.message) == (
        status, payload["code"], payload["type"], payload["message"])
    assert str(err) == f"[{status}] {payload['code']}: {payload['message']}"


def test_from_response_without_body():
    err = APIError.from_response(502, None, "bad gateway")
    assert (err.code, err.error_type, err.message) == ("unknown", "unknown", "bad gateway")


@pytest.mark.parametrize("message, tag", [
    ("Rejected: expiration_passed: quote expired", "expiration_passed"),
    ("Rejected: limit_daily: outgoing amount 5 exceeds remaining daily allowance 1", "limit_daily"),
    ("Rejected: shape", "shape"),
    ("Rejected: abi: cannot pack", "abi"),
    ("CONTRACT_CALL failed: request_digest_mismatch", "request_digest_mismatch"),
    ("PROGRAM_CALL failed: limit_daily", "limit_daily"),
    ("PROGRAM_CALL failed: engine rejected the transaction", None),
    ("Duplicate reference_id: this reference has already been used", None),
    ("Rejected: Not A Tag: detail", None),
    ("Insufficient balance", None),
    ("", None),
])
def test_reason_tag_extraction(message, tag):
    err = APIError(400, "invalid_parameter", "invalid_request_error", message)
    assert err.reason_tag == tag


def test_rejected_flags():
    rej = APIError.from_response(400, body("invalid_parameter", "invalid_request_error", "Rejected: fee_payer: x"))
    assert rej.is_rejected and is_rejected(rej) and not rej.is_duplicate_reference
    dup = APIError.from_response(400, body("invalid_parameter", "invalid_request_error", "Duplicate reference_id: used"))
    assert dup.is_duplicate_reference and not dup.is_rejected and not is_rejected(dup)
    # A 500 whose message happens to start with "Rejected:" is not a rejection.
    assert not APIError(500, "internal_error", "api_error", "Rejected: x").is_rejected


def test_predicates():
    assert is_not_found(APIError(404, "not_found", "not_found_error", "m"))
    assert is_rate_limited(APIError(429, "too_many_requests", "rate_limit_error", "m"))
    assert is_auth_error(APIError(401, "unauthorized", "authentication_error", "m"))
    assert is_auth_error(APIError(403, "forbidden", "permission_error", "m"))
    assert is_forbidden(APIError(403, "forbidden", "permission_error", "m"))
    assert is_endpoint_retired(APIError(410, "invalid_parameter", "endpoint_retired", "m"))
    assert is_service_unavailable(APIError(503, "service_unavailable", "api_error", "m"))
    assert not is_not_found(ValueError("other"))
    assert not is_rejected(ValueError("other"))


def test_rejection_reason_constants_are_consistent():
    consts = {v for k, v in vars(RejectionReason).items()
              if k.isupper() and isinstance(v, str)}
    assert consts == RejectionReason.ALL_TAGS
    assert RejectionReason.REJECTED_TAGS == RejectionReason.CONTRACT_CALL_TAGS | RejectionReason.PROGRAM_CALL_TAGS
    assert RejectionReason.ALL_TAGS == RejectionReason.REJECTED_TAGS | RejectionReason.ENGINE_FAILURE_TAGS
    # Spot-check against the gateway / verifier sources.
    assert {"expiration_passed", "permit_owner", "value_not_zero", "selector"} <= RejectionReason.CONTRACT_CALL_TAGS
    assert {"fee_payer", "alt_not_allowed", "payer_signature_present", "shape"} <= RejectionReason.PROGRAM_CALL_TAGS
    # receiver_not_ours is an engine verdict (syncsettle), never a gateway "Rejected:" tag.
    assert "receiver_not_ours" not in RejectionReason.REJECTED_TAGS
    assert "receiver_not_ours" in RejectionReason.ENGINE_FAILURE_TAGS
    # Every tag has the shape the gateway forwards (publicEngineReason).
    for tag in RejectionReason.ALL_TAGS:
        assert re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", tag) and len(tag) <= 64, tag


def test_engine_failure_tags_pin_the_engine_literals():
    # 24 reject("…") literals in mpc-engine internal/syncsettle + 14 more
    # rejectPermit("…") literals in internal/syncsign/permit.go (10 permit_* plus
    # four verifier tags the permit path emits by name). Same 38 in Go and Rust.
    assert len(RejectionReason.ENGINE_FAILURE_TAGS) == 38
    assert {
        "permit_digest_mismatch", "permit_digest_missing", "permit_domain_mismatch",
        "permit_domain_unverified", "permit_owner_mismatch", "permit_params_invalid",
        "permit_spender_mismatch", "permit_token_mismatch", "permit_token_not_registered",
        "permit_value_mismatch",
    } <= RejectionReason.ENGINE_FAILURE_TAGS
    assert {"request_digest_mismatch", "payer_mismatch", "cosignature_invalid", "signer_slot",
            "internal"} <= RejectionReason.ENGINE_FAILURE_TAGS
    assert RejectionReason.PERMIT_OWNER_MISMATCH == "permit_owner_mismatch"
    err = APIError(400, "transaction_failed", "business_error",
                   "CONTRACT_CALL failed: permit_owner_mismatch: row from_address 0x… : mismatch")
    assert err.reason_tag == RejectionReason.PERMIT_OWNER_MISMATCH
    assert err.reason_tag in RejectionReason.ENGINE_FAILURE_TAGS


def test_error_code_and_type_constants():
    assert ErrorCode.TOKEN_EXPIRED == "token_expired"
    assert ErrorCode.INSUFFICIENT_BALANCE == "insufficient_balance"
    assert ErrorCode.TRANSACTION_FAILED == "transaction_failed"
    assert ErrorType.ENDPOINT_RETIRED == "endpoint_retired"
    assert ErrorType.PERMISSION == "permission_error"


# ── 503: which variant consumes the reference_id ──
#
# The gateway writes exactly three 503 messages (api/handler/transaction_handler.go
# createOperation / writeOperationError). Only the engine-busy one is emitted after
# CreateOperationWithLock inserted the row (internal/service/contract_call.go:441,
# operation_service.go:477 → failOperation), and uk_client_reference does not
# exclude FAILED rows, so only that one leaves the reference_id taken.


@pytest.mark.parametrize("message, busy", [
    ("Signing service is busy, retry later", True),
    ("Chain RPC unavailable; cannot verify request", False),
    ("CONTRACT_CALL is not enabled on this gateway", False),
    ("PROGRAM_CALL is not enabled on this gateway", False),
])
def test_503_engine_busy_is_the_only_reference_consuming_variant(message, busy):
    err = APIError.from_response(503, body("service_unavailable", "api_error", message))
    assert type(err) is ServiceUnavailableError
    assert err.is_engine_busy is busy
    assert err.reference_id_consumed is busy
    assert is_engine_busy(err) is busy
    assert is_service_unavailable(err)


def test_engine_busy_predicate_requires_a_503():
    # Same text on another status is not the engine-busy 503.
    assert not is_engine_busy(APIError(500, "internal_error", "api_error", "Signing service is busy, retry later"))
    assert not is_engine_busy(ValueError("Signing service is busy, retry later"))


def test_403_address_blacklisted_is_forbidden_error():
    # TRANSFER to a blacklisted destination: handler → CodeAddressBlacklisted, httpStatusMap → 403 / permission_error.
    err = APIError.from_response(403, body("address_blacklisted", "permission_error", "Destination address is blacklisted"))
    assert type(err) is ForbiddenError and err.is_address_blacklisted
    policy = APIError.from_response(403, body("forbidden", "permission_error", "operation not authorized by policy"))
    assert type(policy) is ForbiddenError and not policy.is_address_blacklisted


def test_service_unavailable_docstring_does_not_promise_same_reference_for_engine_busy():
    doc = ServiceUnavailableError.__doc__ or ""
    assert "new" in doc.lower() and "Duplicate reference_id" in doc
    assert "No transaction row was created" not in doc
