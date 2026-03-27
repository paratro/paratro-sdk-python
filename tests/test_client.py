"""Basic tests for the Paratro SDK."""

import pytest

from paratro import (
    MPCClient,
    Config,
    APIError,
    is_not_found,
    is_rate_limited,
    is_auth_error,
    VERSION,
)


def test_version():
    assert VERSION == "1.1.3"


def test_config_sandbox():
    config = Config.sandbox()
    assert config.base_url == "https://api-sandbox.paratro.com"


def test_config_production():
    config = Config.production()
    assert config.base_url == "https://api.paratro.com"


def test_config_custom():
    config = Config.custom("http://localhost:8080")
    assert config.base_url == "http://localhost:8080"


def test_config_custom_strips_trailing_slash():
    config = Config.custom("http://localhost:8080/")
    assert config.base_url == "http://localhost:8080"


def test_client_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        MPCClient("", "secret", Config.sandbox())


def test_client_requires_api_secret():
    with pytest.raises(ValueError, match="api_secret"):
        MPCClient("key", "", Config.sandbox())


def test_client_requires_config():
    with pytest.raises(ValueError, match="config"):
        MPCClient("key", "secret", None)  # type: ignore[arg-type]


def test_api_error():
    err = APIError(404, "not_found", "business_error", "Wallet not found")
    assert err.http_status == 404
    assert err.code == "not_found"
    assert err.error_type == "business_error"
    assert "not_found" in str(err)


def test_is_not_found():
    assert is_not_found(APIError(404, "not_found", "err", "msg"))
    assert not is_not_found(APIError(400, "bad", "err", "msg"))
    assert not is_not_found(ValueError("other"))


def test_is_rate_limited():
    assert is_rate_limited(APIError(429, "rate_limited", "err", "msg"))
    assert not is_rate_limited(APIError(400, "bad", "err", "msg"))


def test_is_auth_error():
    assert is_auth_error(APIError(401, "unauthorized", "err", "msg"))
    assert is_auth_error(APIError(403, "forbidden", "err", "msg"))
    assert not is_auth_error(APIError(404, "not_found", "err", "msg"))
