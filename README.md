# Paratro Python SDK

Official Python SDK for [Paratro](https://paratro.com) MPC Wallet Infrastructure.

## Installation

```bash
pip install paratro-sdk
```

## Quick Start

```python
from paratro import MPCClient, Config, CreateWalletRequest, CreateAccountRequest

# Initialize client
client = MPCClient("your_api_key", "your_api_secret", Config.sandbox())

# Create a wallet
wallet = client.create_wallet(CreateWalletRequest(wallet_name="My Wallet"))
print(f"Wallet ID: {wallet.wallet_id}")

# Wait for wallet to be ready (status=ACTIVE, key_status=ACTIVE)
# Then create an account
account = client.create_account(CreateAccountRequest(
    wallet_id=wallet.wallet_id,
    chain="ethereum",
))
print(f"Address: {account.address}")

# Clean up
client.logout()
```

## Configuration

```python
# Sandbox (testnet)
config = Config.sandbox()

# Production
config = Config.production()

# Custom endpoint
config = Config.custom("http://localhost:8080")
```

## API Reference

### Wallets

```python
# Create
wallet = client.create_wallet(CreateWalletRequest(wallet_name="Treasury"))

# Get by ID
wallet = client.get_wallet("wallet_id")

# List
resp = client.list_wallets(ListWalletsRequest(page=1, page_size=10))
for w in resp.items:
    print(w.wallet_name)
```

### Accounts

```python
from paratro import CreateAccountRequest, ListAccountsRequest

# Create
account = client.create_account(CreateAccountRequest(
    wallet_id="wallet_id",
    chain="ethereum",       # ethereum, bsc, polygon, avalanche, tron, bitcoin, solana
    label="Deposit",
))

# Get by ID
account = client.get_account("account_id")

# List by wallet
resp = client.list_accounts(ListAccountsRequest(wallet_id="wallet_id"))
```

### Assets

```python
from paratro import CreateAssetRequest, ListAssetsRequest

# Add asset to account
asset = client.create_asset(CreateAssetRequest(
    account_id="account_id",
    symbol="USDC",
    chain="ethereum",       # Required for EVM accounts
))

# Get by ID
asset = client.get_asset("asset_id")

# List by account
resp = client.list_assets(ListAssetsRequest(account_id="account_id"))
```

### Transfers

```python
from paratro import CreateTransferRequest

result = client.create_transfer(CreateTransferRequest(
    from_address="0xSender...",
    to_address="0xRecipient...",
    chain="ethereum",
    token_symbol="USDC",
    amount="10.5",
))
print(f"TX: {result.tx_id}, Status: {result.status}")
```

### Transactions

```python
from paratro import ListTransactionsRequest

# Get by ID
tx = client.get_transaction("tx_id")

# List with filters
resp = client.list_transactions(ListTransactionsRequest(
    wallet_id="wallet_id",
    chain="ethereum",
    page=1,
    page_size=20,
))
```

## Error Handling

```python
from paratro import APIError, is_not_found, is_rate_limited, is_auth_error

try:
    wallet = client.get_wallet("nonexistent")
except APIError as e:
    print(f"HTTP {e.http_status}: [{e.code}] {e.message}")

    if is_not_found(e):
        print("Resource not found")
    elif is_rate_limited(e):
        print("Rate limited, try again later")
    elif is_auth_error(e):
        print("Authentication failed")
```

## Supported Chains

| Chain | Value |
|-------|-------|
| Ethereum | `ethereum` |
| BNB Smart Chain | `bsc` |
| Polygon | `polygon` |
| Avalanche | `avalanche` |
| Arbitrum | `arbitrum` |
| Optimism | `optimism` |
| Tron | `tron` |
| Bitcoin | `bitcoin` |
| Solana | `solana` |

## Requirements

- Python 3.9+
- `requests` >= 2.28.0

## License

MIT
