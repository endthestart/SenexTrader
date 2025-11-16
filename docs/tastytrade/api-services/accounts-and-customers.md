# Accounts and Customers API Service

The Accounts and Customers API provides access to account information, customer details, and account-level operations.

## Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/customers/me` | Get customer information |
| GET | `/customers/me/accounts` | Get customer accounts |
| GET | `/accounts/{account_number}` | Get specific account |
| GET | `/accounts/{account_number}/balances` | Get account balances |
| GET | `/accounts/{account_number}/positions` | Get account positions |
| GET | `/accounts/{account_number}/trading-status` | Get trading permissions |

## Customer Information

### Get Current Customer
```python
from tastytrade import Customer

# Get current customer details
customer = Customer.get_me(session)

print(f"Customer ID: {customer.id}")
print(f"Username: {customer.username}")
print(f"Email: {customer.email}")
print(f"First Name: {customer.first_name}")
print(f"Last Name: {customer.last_name}")
print(f"Account Count: {len(customer.accounts)}")
```

### Customer Accounts
```python
# Get all accounts for customer
accounts = customer.accounts

for account in accounts:
    print(f"Account: {account.account_number}")
    print(f"  Type: {account.account_type}")
    print(f"  Status: {account.status}")
    print(f"  Nickname: {account.nickname}")
```

## Account Management

### Get Specific Account
```python
from tastytrade import Account

# Get account by number
account_number = 'ABC123456'
account = await Account.a_get(session, account_number)

print(f"Account Details:")
print(f"  Number: {account.account_number}")
print(f"  Type: {account.account_type}")
print(f"  Status: {account.status}")
print(f"  Opened: {account.opened_at}")
print(f"  Day Trading Buying Power: ${account.day_trading_buying_power:,.2f}")
print(f"  Margin Buying Power: ${account.margin_buying_power:,.2f}")
```

### Account Balances
```python
# Get current account balances
balances = await account.a_get_balances(session)

print(f"Account Balances:")
print(f"  Net Liquidating Value: ${balances.net_liquidating_value:,.2f}")
print(f"  Cash Balance: ${balances.cash_balance:,.2f}")
print(f"  Long Equity Value: ${balances.long_equity_value:,.2f}")
print(f"  Short Equity Value: ${balances.short_equity_value:,.2f}")
print(f"  Long Derivative Value: ${balances.long_derivative_value:,.2f}")
print(f"  Short Derivative Value: ${balances.short_derivative_value:,.2f}")
print(f"  Buying Power: ${balances.buying_power:,.2f}")
print(f"  Equity Buying Power: ${balances.equity_buying_power:,.2f}")
print(f"  Derivative Buying Power: ${balances.derivative_buying_power:,.2f}")
print(f"  Day Trading Buying Power: ${balances.day_trading_buying_power:,.2f}")
print(f"  Maintenance Requirement: ${balances.maintenance_requirement:,.2f}")
```

### Balance History
```python
from datetime import datetime, timedelta

# Get balance history
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

balance_history = await account.a_get_balance_snapshots(
    session,
    start_time=start_date,
    end_time=end_date
)

for snapshot in balance_history[-5:]:  # Last 5 snapshots
    print(f"{snapshot.snapshot_date}: NLV=${snapshot.net_liquidating_value:,.2f}")
```

## Positions Management

### Current Positions
```python
# Get all current positions
positions = await account.a_get_positions(session)

print(f"Current Positions ({len(positions)}):")
for position in positions:
    print(f"\n{position.symbol}:")
    print(f"  Quantity: {position.quantity:,}")
    print(f"  Average Open Price: ${position.average_open_price:.2f}")
    print(f"  Mark Price: ${position.mark_price:.2f}")
    print(f"  Market Value: ${position.market_value:,.2f}")
    print(f"  Multiplier: {position.multiplier}")
    print(f"  Realized P&L Today: ${position.realized_day_gain:,.2f}")
    print(f"  Unrealized P&L: ${position.unrealized_day_gain:,.2f}")
    print(f"  Instrument Type: {position.instrument_type}")
```

### Position Filtering
```python
# Filter positions by type
stock_positions = [p for p in positions if p.instrument_type == 'Equity']
option_positions = [p for p in positions if p.instrument_type == 'Equity Option']

print(f"Stock Positions: {len(stock_positions)}")
for position in stock_positions:
    pnl = position.market_value - (position.average_open_price * position.quantity)
    pnl_pct = (pnl / (position.average_open_price * position.quantity)) * 100
    print(f"  {position.symbol}: {position.quantity} shares, P&L: ${pnl:.2f} ({pnl_pct:+.1f}%)")

print(f"\nOption Positions: {len(option_positions)}")
for position in option_positions:
    print(f"  {position.symbol}: {position.quantity} contracts @ ${position.mark_price:.2f}")
```

### Position Aggregation
```python
def aggregate_positions_by_underlying(positions):
    """Group positions by underlying symbol"""
    aggregated = {}
    
    for position in positions:
        # Extract underlying symbol (for options)
        underlying = position.underlying_symbol or position.symbol
        
        if underlying not in aggregated:
            aggregated[underlying] = {
                'positions': [],
                'total_market_value': 0,
                'total_pnl': 0
            }
        
        aggregated[underlying]['positions'].append(position)
        aggregated[underlying]['total_market_value'] += position.market_value
        aggregated[underlying]['total_pnl'] += position.realized_day_gain + position.unrealized_day_gain
    
    return aggregated

# Usage
aggregated = aggregate_positions_by_underlying(positions)

for underlying, data in aggregated.items():
    print(f"\n{underlying}:")
    print(f"  Total Value: ${data['total_market_value']:,.2f}")
    print(f"  Total P&L: ${data['total_pnl']:,.2f}")
    print(f"  Position Count: {len(data['positions'])}")
    
    for position in data['positions']:
        print(f"    {position.symbol}: {position.quantity}")
```

## Trading Status and Permissions

### Get Trading Status
```python
# Get account trading permissions
trading_status = await account.a_get_trading_status(session)

print(f"Trading Status:")
print(f"  Day Trading: {trading_status.is_day_trading_enabled}")
print(f"  Options Level: {trading_status.options_level}")
print(f"  Margin: {trading_status.is_margin_enabled}")
print(f"  Futures: {trading_status.is_futures_enabled}")
print(f"  Crypto: {trading_status.is_crypto_enabled}")
print(f"  International: {trading_status.is_international_enabled}")
```

### Account Restrictions
```python
# Check for account restrictions
if hasattr(trading_status, 'restrictions'):
    restrictions = trading_status.restrictions
    
    if restrictions:
        print("\nAccount Restrictions:")
        for restriction in restrictions:
            print(f"  - {restriction.type}: {restriction.description}")
            if restriction.expires_at:
                print(f"    Expires: {restriction.expires_at}")
    else:
        print("\nNo account restrictions")
```

## Account Types and Features

### Account Type Detection
```python
def get_account_features(account):
    """Determine account features based on type"""
    account_type = account.account_type.upper()
    
    features = {
        'margin_trading': False,
        'options_trading': False,
        'day_trading': False,
        'futures_trading': False,
        'international': False,
        'tax_advantaged': False
    }
    
    if account_type in ['INDIVIDUAL', 'JOINT', 'ENTITY']:
        features['margin_trading'] = True
        features['options_trading'] = True
        features['day_trading'] = True
        features['futures_trading'] = True
        features['international'] = True
    
    elif account_type in ['IRA', 'ROTH_IRA', 'SEP_IRA', 'SIMPLE_IRA']:
        features['tax_advantaged'] = True
        features['options_trading'] = True  # Limited
        # No margin or day trading in IRAs
    
    return features

# Usage
features = get_account_features(account)
print(f"\nAccount Features for {account.account_type}:")
for feature, enabled in features.items():
    print(f"  {feature.replace('_', ' ').title()}: {'✓' if enabled else '✗'}")
```

## Multi-Account Management

### Working with Multiple Accounts
```python
class MultiAccountManager:
    def __init__(self, session):
        self.session = session
        self.accounts = {}
    
    async def load_all_accounts(self):
        """Load all customer accounts"""
        customer = Customer.get_me(self.session)
        
        for account_info in customer.accounts:
            account = await Account.a_get(self.session, account_info.account_number)
            self.accounts[account.account_number] = account
    
    async def get_combined_balances(self):
        """Get combined balances across all accounts"""
        combined = {
            'total_nlv': 0,
            'total_cash': 0,
            'total_buying_power': 0,
            'account_count': len(self.accounts)
        }
        
        for account_number, account in self.accounts.items():
            try:
                balances = await account.a_get_balances(self.session)
                combined['total_nlv'] += balances.net_liquidating_value
                combined['total_cash'] += balances.cash_balance
                combined['total_buying_power'] += balances.buying_power
            except Exception as e:
                print(f"Error getting balances for {account_number}: {e}")
        
        return combined
    
    async def get_all_positions(self):
        """Get positions from all accounts"""
        all_positions = []
        
        for account_number, account in self.accounts.items():
            try:
                positions = await account.a_get_positions(self.session)
                for position in positions:
                    position.account_number = account_number  # Add account reference
                all_positions.extend(positions)
            except Exception as e:
                print(f"Error getting positions for {account_number}: {e}")
        
        return all_positions
    
    def get_account_summary(self):
        """Get summary of all accounts"""
        summary = []
        
        for account_number, account in self.accounts.items():
            summary.append({
                'account_number': account_number,
                'account_type': account.account_type,
                'status': account.status,
                'nickname': account.nickname
            })
        
        return summary

# Usage
manager = MultiAccountManager(session)
await manager.load_all_accounts()

# Get combined overview
combined_balances = await manager.get_combined_balances()
print(f"Combined Portfolio:")
print(f"  Total NLV: ${combined_balances['total_nlv']:,.2f}")
print(f"  Total Cash: ${combined_balances['total_cash']:,.2f}")
print(f"  Accounts: {combined_balances['account_count']}")

# Get all positions across accounts
all_positions = await manager.get_all_positions()
print(f"\nTotal Positions: {len(all_positions)}")

# Group by account
by_account = {}
for position in all_positions:
    account_num = position.account_number
    if account_num not in by_account:
        by_account[account_num] = []
    by_account[account_num].append(position)

for account_num, positions in by_account.items():
    print(f"  {account_num}: {len(positions)} positions")
```

## Account Monitoring

### Balance Change Alerts
```python
class BalanceMonitor:
    def __init__(self, account, session, threshold_pct=5.0):
        self.account = account
        self.session = session
        self.threshold_pct = threshold_pct
        self.last_nlv = None
        self.alerts = []
    
    async def check_balance_changes(self):
        """Check for significant balance changes"""
        try:
            balances = await self.account.a_get_balances(self.session)
            current_nlv = balances.net_liquidating_value
            
            if self.last_nlv is not None:
                change = current_nlv - self.last_nlv
                change_pct = (change / self.last_nlv) * 100 if self.last_nlv != 0 else 0
                
                if abs(change_pct) >= self.threshold_pct:
                    alert = {
                        'timestamp': datetime.now(),
                        'account': self.account.account_number,
                        'old_nlv': self.last_nlv,
                        'new_nlv': current_nlv,
                        'change': change,
                        'change_pct': change_pct
                    }
                    self.alerts.append(alert)
                    
                    print(f"⚠️  Balance Alert: {self.account.account_number}")
                    print(f"   NLV changed by ${change:,.2f} ({change_pct:+.1f}%)")
                    print(f"   From ${self.last_nlv:,.2f} to ${current_nlv:,.2f}")
            
            self.last_nlv = current_nlv
            
        except Exception as e:
            print(f"Error monitoring balance for {self.account.account_number}: {e}")
    
    def get_alerts(self):
        """Get and clear alerts"""
        alerts = self.alerts.copy()
        self.alerts.clear()
        return alerts

# Usage
monitor = BalanceMonitor(account, session, threshold_pct=2.0)  # 2% threshold

# Run periodic checks
while True:
    await monitor.check_balance_changes()
    await asyncio.sleep(60)  # Check every minute
```

## Error Handling

### Account Access Errors
```python
from tastytrade.exceptions import TastyTradeError

async def safe_account_access(session, account_number):
    """Safely access account with comprehensive error handling"""
    try:
        account = await Account.a_get(session, account_number)
        return account
    
    except TastyTradeError as e:
        if e.status_code == 404:
            print(f"Account {account_number} not found")
            return None
        elif e.status_code == 403:
            print(f"Access denied to account {account_number}")
            return None
        elif e.status_code == 401:
            print("Authentication expired, refresh session")
            session.refresh()
            # Retry once
            return await Account.a_get(session, account_number)
        else:
            print(f"API error accessing account: {e}")
            raise
    
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None

# Usage with error handling
account = await safe_account_access(session, 'ABC123456')
if account:
    balances = await account.a_get_balances(session)
    print(f"Account loaded successfully: ${balances.net_liquidating_value:,.2f}")
else:
    print("Could not access account")
```

This Accounts and Customers API documentation provides comprehensive coverage of account management, balance monitoring, and position tracking essential for trading applications.