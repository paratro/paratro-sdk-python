"""Config, version, and the wallet / account / asset / webhook surface."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from paratro import (
    APIError,
    Config,
    CreateAccountRequest,
    CreateAssetRequest,
    CreateWalletRequest,
    ListAccountsRequest,
    ListAssetsRequest,
    MPCClient,
    WebhookEventType,
    __version__,
    parse_event,
    verify_signature,
)
from paratro.config import BASE_URL_ERROR


def test_version():
    assert __version__ == "1.9.0"


def test_config_has_no_environment_presets():
    # 1.9.0: the gateway base URL is always passed explicitly — Paratro cloud and private
    # deployments alike — so the SDK carries no address and no preset.
    for preset in ("sandbox", "production", "custom"):
        assert not hasattr(Config, preset), preset


def test_config_strips_trailing_slash():
    assert Config("http://localhost:8080/").base_url == "http://localhost:8080"
    assert Config("http://localhost:8080///").base_url == "http://localhost:8080"
    assert Config("https://gateway.example").base_url == "https://gateway.example"
    assert repr(Config("https://gateway.example")) == "Config(base_url='https://gateway.example')"


@pytest.mark.parametrize("bad", ["", "gateway.example", "//gateway.example", "ftp://gateway.example",
                                 "https://", "http:/gateway.example", None])
def test_client_rejects_a_base_url_that_is_not_absolute_http(bad):
    config = Config(bad)  # building the Config never raises …
    with pytest.raises(ValueError) as ei:
        MPCClient("key", "secret", config)  # … creating the client does
    assert str(ei.value) == BASE_URL_ERROR
    assert str(ei.value).startswith("base URL must be an absolute http(s) URL")


@pytest.mark.parametrize("url", ["http://127.0.0.1:1", "https://gateway.example/", "https://gateway.example/v1"])
def test_client_accepts_absolute_http_urls_without_touching_the_network(url):
    client = MPCClient("key", "secret", Config(url))
    assert client._config.base_url == url.rstrip("/")
    client._session.close()


# ── wallets / accounts / assets ──


def test_create_wallet(gateway, client):
    gateway.queue.append((200, {"wallet_id": "w1", "wallet_name": "Treasury", "status": "CREATING", "key_status": "PENDING"}))
    w = client.create_wallet(CreateWalletRequest(wallet_name="Treasury", description="Primary"))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/wallets")
    assert call["body"] == {"wallet_name": "Treasury", "description": "Primary"}
    assert w.wallet_id == "w1" and w.status == "CREATING"


def test_create_wallet_with_signing_quorum(gateway, client):
    # dto.CreateWalletRequest: threshold / total_shares / signing_party_ids are optional; the handler
    # defaults to 2-of-3 and requires len(signing_party_ids) == threshold.
    gateway.queue.append((200, {"wallet_id": "w2", "wallet_name": "Treasury", "status": "CREATING", "key_status": "PENDING"}))
    client.create_wallet(CreateWalletRequest(wallet_name="Treasury", threshold=3, total_shares=5,
                                             signing_party_ids=["n1", "n2", "n3"]))
    assert gateway.api_calls()[0]["body"] == {
        "wallet_name": "Treasury", "threshold": 3, "total_shares": 5, "signing_party_ids": ["n1", "n2", "n3"],
    }


def test_list_wallets_pagination(gateway, client):
    from paratro import ListWalletsRequest
    gateway.queue.append((200, {"data": [{"wallet_id": "w1"}], "total": 1, "has_more": False}))
    out = client.list_wallets(ListWalletsRequest(page=1, page_size=10))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("GET", "/api/v1/wallets")
    assert sorted(call["query"].split("&")) == ["page=1", "page_size=10"]
    assert out.items[0].wallet_id == "w1" and out.total == 1


def test_create_account(gateway, client):
    gateway.queue.append((200, {"account_id": "a1", "address": "0xabc", "network": "testnet"}))
    a = client.create_account(CreateAccountRequest(wallet_id="w1", chain="ethereum", account_type="OUTBOUND", label="Hot"))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/accounts")
    assert call["body"] == {"wallet_id": "w1", "chain": "ethereum", "account_type": "OUTBOUND", "label": "Hot"}
    assert a.account_id == "a1" and a.address == "0xabc"


def test_list_accounts_filter(gateway, client):
    gateway.queue.append((200, {"data": [], "total": 0, "has_more": False}))
    client.list_accounts(ListAccountsRequest(wallet_id="w1", page=2, page_size=5))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("GET", "/api/v1/accounts")
    assert sorted(call["query"].split("&")) == ["page=2", "page_size=5", "wallet_id=w1"]


def test_create_asset(gateway, client):
    gateway.queue.append((200, {"asset_id": "as1", "symbol": "USDC", "balance": "0", "decimals": 6}))
    a = client.create_asset(CreateAssetRequest(account_id="a1", symbol="USDC", chain="ethereum"))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("POST", "/api/v1/assets")
    assert call["body"] == {"account_id": "a1", "symbol": "USDC", "chain": "ethereum"}
    assert a.asset_id == "as1" and a.decimals == 6


def test_list_assets_filter(gateway, client):
    gateway.queue.append((200, {"data": [{"asset_id": "as1", "symbol": "USDC"}], "total": 1, "has_more": False}))
    out = client.list_assets(ListAssetsRequest(account_id="a1"))
    call = gateway.api_calls()[0]
    assert (call["method"], call["path"]) == ("GET", "/api/v1/assets")
    assert call["query"] == "account_id=a1"
    assert out.items[0].symbol == "USDC"


def test_get_helpers_paths(gateway, client):
    gateway.queue.extend([(200, {"wallet_id": "w1"}), (200, {"account_id": "a1"}), (200, {"asset_id": "as1"})])
    client.get_wallet("w1")
    client.get_account("a1")
    client.get_asset("as1")
    assert [c["path"] for c in gateway.api_calls()] == ["/api/v1/wallets/w1", "/api/v1/accounts/a1", "/api/v1/assets/as1"]


# ── webhook ──


def _sign(secret: str, ts: str, payload: bytes) -> str:
    return "v1=" + hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()


def test_webhook_verify_and_parse_transfer_credited():
    payload = {
        "event_id": "evt-1", "event_type": "transfer.credited", "event_time": "2026-09-15T00:00:00Z",
        "source_id": "tx-1", "wallet_id": "w", "account_id": "a", "status": "CONFIRMED",
        "transaction_type": "INTERNAL", "chain": "ethereum", "network": "testnet", "txhash": "0xh",
        "block_number": 10, "from": "0xfrom", "to": "0xto", "symbol": "USDC", "contract_address": "0xusdc",
        "amount": "1000000", "decimals": 6, "confirmations": 12, "required_confirmations": 12,
        "created_at": "2026-09-15T00:00:00Z", "confirmed_at": "2026-09-15T00:01:00Z",
        "risk_checked": True, "risk_score": 1.5, "risk_level": "LOW", "data": "",
    }
    raw = json.dumps(payload).encode()
    ts = str(int(time.time()))
    verify_signature("whsec", ts, raw, _sign("whsec", ts, raw))
    event = parse_event(payload)
    assert event.event_type == WebhookEventType.TRANSFER_CREDITED == "transfer.credited"
    assert event.from_addr == "0xfrom" and event.to_addr == "0xto" and event.transaction_type == "INTERNAL"
    assert event.risk_level == "LOW" and event.risk_score == 1.5

    with pytest.raises(APIError):
        verify_signature("whsec", ts, raw, "v1=deadbeef")
    with pytest.raises(APIError):
        verify_signature("whsec", str(int(time.time()) - 3600), raw, _sign("whsec", str(int(time.time()) - 3600), raw))


def test_webhook_event_types_are_the_emitted_set():
    # paratro-mpc-message: webhook EventType literals in internal/ (grep '"(transaction|transfer|x402)\.' ),
    # x402.settlement.confirmed from dispatcher/x402_credit.go via the same webhook.Sender.
    emitted = {v for k, v in vars(WebhookEventType).items() if k.isupper()}
    assert emitted == {"transaction.confirming", "transaction.confirmed", "transaction.failed",
                       "transfer.credited", "x402.settlement.confirmed"}
    assert WebhookEventType.X402_SETTLEMENT_CONFIRMED == "x402.settlement.confirmed"


def test_base_url_requires_a_host() -> None:
    """Same strictness as the Go/Rust SDKs: a scheme alone or an empty host is rejected."""
    import pytest

    from paratro.config import BASE_URL_ERROR, validate_base_url

    for bad in ("https://", "https:///path", "http://", "https://gw example"):
        with pytest.raises(ValueError, match="absolute http\\(s\\) URL"):
            validate_base_url(bad)
    for ok in ("https://gateway.example", "http://127.0.0.1:8080/", "https://mpcapi.example/api"):
        validate_base_url(ok)
    assert "paratro.com" not in BASE_URL_ERROR
