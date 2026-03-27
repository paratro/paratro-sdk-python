# Paratro MPC Wallet Gateway Python SDK

[![PyPI version](https://img.shields.io/pypi/v/paratro-sdk.svg)](https://pypi.org/project/paratro-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/paratro-sdk.svg)](https://pypi.org/project/paratro-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Official Python SDK for [Paratro](https://paratro.com) MPC Wallet Gateway — a comprehensive Multi-Party Computation wallet management platform.

## Features

- **MPC Wallets** — Create and manage MPC wallets with threshold-signature security
- **Multi-Chain Support** — Ethereum, BSC, Polygon, Avalanche, Arbitrum, Optimism, Tron, Bitcoin, Solana
- **Account Management** — Create and manage multiple accounts per wallet
- **Asset Management** — Support for native tokens and ERC20/TRC20 tokens
- **Transfer** — Send funds to external addresses with automatic asset resolution
- **Transaction Tracking** — Complete transaction history and status tracking
- **x402 Payments** — Native support for HTTP 402 payment protocol (X402_SIGN, X402_SETTLE)
- **Secure** — Built-in JWT authentication with automatic token refresh
- **Thread-Safe** — Token management with thread-safe locking for concurrent usage

## Installation

```bash
pip install paratro-sdk
```

**Requirements:** Python 3.9+

## Quick Start

```python
from paratro import (
    MPCClient, Config,
    CreateWalletRequest, CreateAccountRequest,
    CreateAssetRequest, CreateTransferRequest,
)

# 1. Initialize client
client = MPCClient("your-api-key", "your-api-secret", Config.sandbox())

# 2. Create a wallet
wallet = client.create_wallet(CreateWalletRequest(wallet_name="My Wallet"))
print(f"Wallet ID: {wallet.wallet_id}, Status: {wallet.status}")

# 3. Wait for wallet to be ready (status=ACTIVE, key_status=ACTIVE)
#    New wallets are created asynchronously. Poll get_wallet() until ready.
wallet = client.get_wallet(wallet.wallet_id)
assert wallet.status == "ACTIVE" and wallet.key_status == "ACTIVE"

# 4. Create an account
account = client.create_account(CreateAccountRequest(
    wallet_id=wallet.wallet_id,
    chain="ethereum",
    label="Deposit Account",
))
print(f"Account: {account.account_id}, Address: {account.address}")

# 5. Add an asset
asset = client.create_asset(CreateAssetRequest(
    account_id=account.account_id,
    symbol="USDT",
    chain="ethereum",
))
print(f"Asset: {asset.asset_id}, Symbol: {asset.symbol}")

# 6. Create a transfer
transfer = client.create_transfer(CreateTransferRequest(
    from_address=account.address,
    to_address="0xRecipient...",
    chain="ethereum",
    token_symbol="USDT",
    amount="10.5",
))
print(f"Transfer: {transfer.tx_id}, Status: {transfer.status}")

# 7. List transactions
resp = client.list_transactions()
for tx in resp.items:
    print(f"TX: {tx.tx_hash} {tx.amount} {tx.token_symbol} ({tx.status})")

# 8. Clean up
client.logout()
```

## Configuration

```python
from paratro import Config

# Sandbox (for testing)
config = Config.sandbox()     # https://api-sandbox.paratro.com

# Production
config = Config.production()  # https://api.paratro.com

# Custom environment
config = Config.custom("https://your-api.example.com")
```

## API Reference

### Wallets

Create and manage MPC wallets. New wallets are created asynchronously — wait until both `status` and `key_status` are `ACTIVE` before creating accounts.

```python
from paratro import CreateWalletRequest, ListWalletsRequest

# Create a wallet
wallet = client.create_wallet(CreateWalletRequest(
    wallet_name="Treasury",
    description="Primary treasury wallet",
))

# Get wallet by ID
wallet = client.get_wallet("wallet_id")

# List wallets with pagination
resp = client.list_wallets(ListWalletsRequest(page=1, page_size=10))
print(f"Total: {resp.total}, Has more: {resp.has_more}")
for w in resp.items:
    print(f"  {w.wallet_id}: {w.wallet_name} ({w.status})")
```

**Wallet fields:** `wallet_id`, `client_id`, `wallet_name`, `description`, `status`, `key_status`, `created_at`, `updated_at`

### Accounts

Create blockchain accounts under a wallet. The gateway derives the account `network` automatically from the selected `chain`. EVM-compatible chains share the same key derivation and produce the same address.

```python
from paratro import CreateAccountRequest, ListAccountsRequest

# Create an account
account = client.create_account(CreateAccountRequest(
    wallet_id="wallet_id",
    chain="ethereum",       # See supported chains below
    account_type="DEPOSIT", # Optional
    label="Hot Wallet",     # Optional
))

# Get account by ID
account = client.get_account("account_id")

# List accounts filtered by wallet
resp = client.list_accounts(ListAccountsRequest(
    wallet_id="wallet_id",
    page=1,
    page_size=20,
))
```

**Account fields:** `account_id`, `wallet_id`, `client_id`, `address`, `network`, `address_type`, `label`, `status`, `created_at`

### Assets

Add tokens to an account. Asset configuration (contract address, decimals, etc.) is resolved automatically by the gateway.

```python
from paratro import CreateAssetRequest, ListAssetsRequest

# Add USDC on Ethereum to an account
asset = client.create_asset(CreateAssetRequest(
    account_id="account_id",
    symbol="USDC",
    chain="ethereum",  # Required for EVM accounts to specify target chain
))

# Get asset by ID
asset = client.get_asset("asset_id")
print(f"Balance: {asset.balance} {asset.symbol}")

# List assets for an account
resp = client.list_assets(ListAssetsRequest(account_id="account_id"))
for a in resp.items:
    print(f"  {a.symbol}: {a.balance} (locked: {a.locked_balance})")
```

**Asset fields:** `asset_id`, `account_id`, `wallet_id`, `client_id`, `chain`, `network`, `symbol`, `name`, `contract_address`, `decimals`, `asset_type`, `balance`, `locked_balance`, `is_active`, `created_at`

**Supported symbols:** `ETH`, `BNB`, `MATIC`, `AVAX`, `TRX`, `BTC`, `SOL`, `USDT`, `USDC`, and other ERC20/TRC20 tokens

### Transfers

Send funds to external addresses. The API automatically resolves the asset using chain + token symbol.

```python
from paratro import CreateTransferRequest

result = client.create_transfer(CreateTransferRequest(
    from_address="0xYourAddress...",
    to_address="0xRecipient...",
    chain="ethereum",
    token_symbol="USDC",
    amount="100.50",
    memo="Invoice #1234",  # Optional
))
print(f"TX ID: {result.tx_id}, Status: {result.status}")
```

**Transfer response fields:** `tx_id`, `status`, `message`

### Transactions

Query transaction history. Supports filtering by wallet, account, and chain.

```python
from paratro import ListTransactionsRequest

# Get a single transaction
tx = client.get_transaction("tx_id")
print(f"Type: {tx.transaction_type}, Hash: {tx.tx_hash}")

# List transactions with filters
resp = client.list_transactions(ListTransactionsRequest(
    wallet_id="wallet_id",      # Optional filter
    account_id="account_id",    # Optional filter
    chain="ethereum",           # Optional filter
    page=1,
    page_size=20,
))
for tx in resp.items:
    print(f"  {tx.tx_id}: {tx.transaction_type} {tx.amount} {tx.token_symbol} -> {tx.status}")
```

**Transaction fields:** `tx_id`, `wallet_id`, `client_id`, `chain`, `transaction_type`, `from_address`, `to_address`, `token_symbol`, `amount`, `status`, `tx_hash`, `created_at`

**Transaction types:** `TRANSFER`, `X402_SIGN`, `X402_SETTLE`

## Error Handling

The SDK raises `APIError` for all API failures with structured error information:

```python
from paratro import APIError, is_not_found, is_rate_limited, is_auth_error

try:
    wallet = client.get_wallet("nonexistent_id")
except APIError as e:
    print(f"HTTP {e.http_status}: [{e.code}] {e.message}")
    print(f"Error type: {e.error_type}")

    # Convenience helpers
    if is_not_found(e):
        print("Resource not found")
    elif is_rate_limited(e):
        print("Rate limited — retry after backoff")
    elif is_auth_error(e):
        print("Authentication failed — check API key/secret")
```

**Error attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `http_status` | `int` | HTTP status code (400, 401, 403, 404, 429, 500, etc.) |
| `code` | `str` | Machine-readable error code (e.g. `not_found`, `invalid_parameter`) |
| `error_type` | `str` | Error category (e.g. `business_error`, `validation_error`) |
| `message` | `str` | Human-readable error description |

## Supported Chains

| Chain | Value | Type |
|-------|-------|------|
| Ethereum | `ethereum` | EVM |
| BNB Smart Chain | `bsc` | EVM |
| Polygon | `polygon` | EVM |
| Avalanche | `avalanche` | EVM |
| Arbitrum | `arbitrum` | EVM |
| Optimism | `optimism` | EVM |
| Tron | `tron` | TVM |
| Bitcoin | `bitcoin` | UTXO |
| Solana | `solana` | SVM |

> **Note:** EVM-compatible chains (`ethereum`, `bsc`, `polygon`, `avalanche`, `arbitrum`, `optimism`) share the same key derivation and produce the same address per wallet.

## Authentication

The SDK handles authentication automatically:

1. On the first API call, the client exchanges your `api_key` and `api_secret` for a JWT token
2. The token is cached and reused for subsequent requests
3. When the token approaches expiration (< 5 minutes remaining), it is automatically refreshed
4. Token management is thread-safe for concurrent usage
5. Call `client.logout()` to explicitly invalidate the token

## Project Structure

```
paratro-sdk-python/
├── paratro/
│   ├── __init__.py     # Public API exports
│   ├── client.py       # MPCClient with all API methods
│   ├── config.py       # Environment configuration
│   ├── errors.py       # APIError and helper functions
│   ├── models.py       # Request/response dataclasses
│   └── version.py      # SDK version
├── tests/
│   └── test_client.py  # Unit tests
├── pyproject.toml      # Package metadata
├── LICENSE             # MIT License
└── README.md
```

## Development

```bash
# Install dev dependencies
pip install pytest requests

# Run tests
python -m pytest tests/ -v

# Type checking (optional)
pip install mypy
mypy paratro/
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

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
