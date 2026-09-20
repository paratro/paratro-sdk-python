"""Authentication: token exchange, caching, token_expired retry, redirect safety."""

from __future__ import annotations

import pytest

from paratro import APIError, AuthenticationError, Config, MPCClient, is_auth_error, is_token_expired


def test_token_exchange_headers_and_bearer(gateway, client):
    gateway.queue.append((200, {"wallet_id": "w1"}))
    client.get_wallet("w1")

    token_call = gateway.token_calls()[0]
    assert token_call["method"] == "POST"
    assert token_call["headers"]["x-api-key"] == "fixture-key"
    assert token_call["headers"]["x-api-secret"] == "fixture-secret"
    assert token_call["headers"].get("authorization") is None

    api_call = gateway.api_calls()[0]
    assert api_call["headers"]["authorization"] == "Bearer tok-1"
    assert api_call["headers"]["user-agent"].startswith("paratro-sdk-python/")


def test_token_is_cached_across_requests(gateway, client):
    gateway.queue.extend([(200, {"wallet_id": "w1"}), (200, {"wallet_id": "w2"})])
    client.get_wallet("w1")
    client.get_wallet("w2")
    assert len(gateway.token_calls()) == 1
    assert len(gateway.api_calls()) == 2


def test_token_refreshed_before_expiry_buffer(gateway, client):
    gateway.default_expires_in = 60  # below the 120 s refresh buffer → refresh every call
    gateway.queue.extend([(200, {"wallet_id": "w1"}), (200, {"wallet_id": "w2"})])
    client.get_wallet("w1")
    client.get_wallet("w2")
    assert len(gateway.token_calls()) == 2


def test_401_token_expired_reauths_once_and_retries_once(gateway, client):
    gateway.queue.extend([
        (401, {"code": "token_expired", "type": "authentication_error", "message": "Token expired"}),
        (200, {"wallet_id": "w1"}),
    ])
    wallet = client.get_wallet("w1")
    assert wallet.wallet_id == "w1"
    paths = [(c["method"], c["path"], c["headers"].get("authorization")) for c in gateway.calls]
    assert paths == [
        ("POST", "/api/v1/auth/token", None),
        ("GET", "/api/v1/wallets/w1", "Bearer tok-1"),
        ("POST", "/api/v1/auth/token", None),
        ("GET", "/api/v1/wallets/w1", "Bearer tok-2"),
    ]


def test_401_token_expired_twice_raises_without_looping(gateway, client):
    expired = (401, {"code": "token_expired", "type": "authentication_error", "message": "Token expired"})
    gateway.queue.extend([expired, expired])
    with pytest.raises(AuthenticationError) as ei:
        client.get_wallet("w1")
    assert ei.value.is_token_expired and is_token_expired(ei.value) and is_auth_error(ei.value)
    assert len(gateway.token_calls()) == 2
    assert len(gateway.api_calls()) == 2


def test_401_invalid_token_is_not_retried(gateway, client):
    gateway.queue.append((401, {"code": "invalid_token", "type": "authentication_error", "message": "Invalid token"}))
    with pytest.raises(AuthenticationError) as ei:
        client.get_wallet("w1")
    assert not ei.value.is_token_expired
    assert len(gateway.token_calls()) == 1 and len(gateway.api_calls()) == 1


def test_token_endpoint_401_surfaces_as_authentication_error(gateway, client):
    gateway.token_replies.append((401, {"code": "unauthorized", "type": "authentication_error",
                                        "message": "Invalid API key or secret. Please check your credentials."}))
    with pytest.raises(AuthenticationError) as ei:
        client.get_wallet("w1")
    assert ei.value.code == "unauthorized"
    assert gateway.api_calls() == []


def test_token_endpoint_403_ip_not_allowed(gateway, client):
    gateway.token_replies.append((403, {"code": "forbidden", "type": "permission_error", "message": "IP not allowed: 10.0.0.1"}))
    with pytest.raises(APIError) as ei:
        client.get_wallet("w1")
    assert ei.value.http_status == 403


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("phase", ["authentication", "request"])
def test_redirects_are_not_followed(gateway, client, status, phase):
    location = f"{gateway.base_url}/elsewhere?secret=do-not-log"
    if phase == "authentication":
        gateway.token_replies.append((status, location))
    else:
        gateway.queue.append((status, location))
    with pytest.raises(APIError) as ei:
        client.get_wallet("w1")
    assert ei.value.http_status == status
    assert "do-not-log" not in str(ei.value)
    assert all(c["path"] != "/elsewhere" for c in gateway.calls)


def test_non_json_error_body(gateway, client):
    # Fake gateway always emits JSON; craft the branch through the static helper instead.
    class Resp:
        status_code = 502
        text = "<html>bad gateway</html>"
        content = text.encode()

        def json(self):
            raise ValueError("not json")

    with pytest.raises(APIError) as ei:
        MPCClient._raise_for_error(Resp())  # type: ignore[arg-type]
    assert ei.value.http_status == 502 and ei.value.code == "unknown" and "bad gateway" in ei.value.message


def test_constructor_validation():
    with pytest.raises(ValueError, match="api_key"):
        MPCClient("", "secret", Config("https://gateway.example"))
    with pytest.raises(ValueError, match="api_secret"):
        MPCClient("key", "", Config("https://gateway.example"))
    with pytest.raises(ValueError, match="config"):
        MPCClient("key", "secret", None)  # type: ignore[arg-type]


def test_default_timeout_covers_the_gateway_engine_budget():
    # Gateway: PROGRAM_CALL / CONTRACT_CALL wait synchronously for the engine
    # (it answers 202 after 150 s = 120 s budget + 30 s margin, and its server
    # WriteTimeout closes the connection at 180 s). The SDK default must sit
    # above the WriteTimeout so the gateway, not the SDK, gives up first.
    # Same default as Go (paratro.DefaultTimeout) / Rust (config::DEFAULT_TIMEOUT).
    from paratro import DEFAULT_TIMEOUT
    assert DEFAULT_TIMEOUT == 200
    assert DEFAULT_TIMEOUT > 180
    assert MPCClient("key", "secret", Config("https://gateway.example"))._timeout == 200
    assert MPCClient("key", "secret", Config("https://gateway.example"), timeout=7)._timeout == 7


def test_configured_timeout_bounds_the_request():
    # A listener that accepts but never answers: the SDK must give up after
    # ``timeout`` seconds (applies to the auth call as well).
    import socket
    import time

    import requests

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        client = MPCClient("key", "secret", Config(f"http://127.0.0.1:{srv.getsockname()[1]}"), timeout=0.3)
        started = time.monotonic()
        with pytest.raises(requests.exceptions.Timeout):
            client.transactions.get("tx-timeout")
        assert time.monotonic() - started < 5
    finally:
        srv.close()
