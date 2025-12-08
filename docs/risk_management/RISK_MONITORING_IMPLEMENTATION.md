# Risk Monitoring Implementation Guide

## Monte Carlo Simulation Framework

```python
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple
import pandas as pd

@dataclass
class TradeResult:
    """Track trades in R-multiples"""
    entry_price: float
    exit_price: float
    position_size: int
    risk_amount: float  # 1R in dollars

    @property
    def r_multiple(self) -> float:
        pnl = (self.exit_price - self.entry_price) * self.position_size
        return pnl / self.risk_amount


class MonteCarloRiskSimulator:
    """
    Stress test trading strategy using historical R-multiples
    """

    def __init__(self, historical_trades: List[TradeResult]):
        self.r_multiples = [t.r_multiple for t in historical_trades]
        self.win_rate = sum(1 for r in self.r_multiples if r > 0) / len(self.r_multiples)
        self.avg_win = np.mean([r for r in self.r_multiples if r > 0])
        self.avg_loss = np.mean([r for r in self.r_multiples if r < 0])
        self.expectancy = np.mean(self.r_multiples)

    def simulate_portfolio(self,
                          starting_capital: float = 10000,
                          risk_per_trade: float = 0.01,
                          num_trades: int = 100,
                          num_simulations: int = 1000) -> dict:
        """
        Run Monte Carlo simulation on portfolio growth
        """
        results = []

        for _ in range(num_simulations):
            capital = starting_capital
            equity_curve = [capital]
            drawdown_curve = []
            peak_capital = capital

            for _ in range(num_trades):
                # Random sample from historical R-multiples
                r_multiple = np.random.choice(self.r_multiples)

                # Calculate position size based on current capital
                risk_amount = capital * risk_per_trade
                pnl = risk_amount * r_multiple

                # Update capital
                capital += pnl
                equity_curve.append(capital)

                # Track drawdown
                if capital > peak_capital:
                    peak_capital = capital
                drawdown = (peak_capital - capital) / peak_capital
                drawdown_curve.append(drawdown)

            results.append({
                'final_capital': capital,
                'total_return': (capital - starting_capital) / starting_capital,
                'max_drawdown': max(drawdown_curve) if drawdown_curve else 0,
                'equity_curve': equity_curve
            })

        # Calculate statistics
        final_capitals = [r['final_capital'] for r in results]
        max_drawdowns = [r['max_drawdown'] for r in results]

        return {
            'expectancy_r': self.expectancy,
            'win_rate': self.win_rate,
            'avg_win_r': self.avg_win,
            'avg_loss_r': self.avg_loss,
            'median_final_capital': np.median(final_capitals),
            'percentile_5': np.percentile(final_capitals, 5),  # 95% confidence
            'percentile_95': np.percentile(final_capitals, 95),
            'probability_of_profit': sum(1 for c in final_capitals if c > starting_capital) / num_simulations,
            'probability_of_50_loss': sum(1 for c in final_capitals if c < starting_capital * 0.5) / num_simulations,
            'median_max_drawdown': np.median(max_drawdowns),
            'percentile_95_drawdown': np.percentile(max_drawdowns, 95),
            'results': results
        }

    def calculate_kelly_criterion(self) -> float:
        """
        Calculate optimal position sizing using Kelly Criterion
        Modified for options trading (capped at 25% for safety)
        """
        if self.avg_loss == 0:
            return 0

        # Kelly % = (p * b - q) / b
        # Where p = win rate, q = loss rate, b = win/loss ratio
        b = abs(self.avg_win / self.avg_loss)
        p = self.win_rate
        q = 1 - p

        kelly_percent = (p * b - q) / b

        # Cap at 25% for safety (full Kelly is too aggressive)
        return min(kelly_percent * 0.25, 0.25)  # Use 1/4 Kelly

    def risk_of_ruin(self,
                     starting_capital: float = 10000,
                     ruin_threshold: float = 0.5,
                     risk_per_trade: float = 0.01,
                     num_trades: int = 100) -> float:
        """
        Calculate probability of hitting ruin threshold
        """
        ruin_count = 0
        num_simulations = 1000

        for _ in range(num_simulations):
            capital = starting_capital
            min_capital = starting_capital * ruin_threshold

            for _ in range(num_trades):
                r_multiple = np.random.choice(self.r_multiples)
                risk_amount = capital * risk_per_trade
                capital += risk_amount * r_multiple

                if capital <= min_capital:
                    ruin_count += 1
                    break

        return ruin_count / num_simulations
```

## Position Sizing Calculator

```python
class PositionSizeCalculator:
    """
    Calculate optimal position sizes based on risk parameters
    """

    def __init__(self, account_value: float, max_risk_percent: float = 0.01):
        self.account_value = account_value
        self.max_risk_percent = max_risk_percent

    def calculate_iron_condor_size(self,
                                   max_loss_per_contract: float,
                                   current_positions: int = 0,
                                   max_positions: int = 5) -> int:
        """
        Calculate position size for iron condor
        """
        # Check position limits
        if current_positions >= max_positions:
            return 0

        # Calculate based on risk
        max_risk_dollars = self.account_value * self.max_risk_percent
        contracts = int(max_risk_dollars / max_loss_per_contract)

        # Apply limits
        contracts = min(contracts, max_positions - current_positions)

        return max(contracts, 0)

    def calculate_spread_size(self,
                            spread_width: float,
                            credit_received: float,
                            current_positions: int = 0,
                            max_positions: int = 10) -> int:
        """
        Calculate position size for vertical spread
        """
        # Max loss = spread width - credit received
        max_loss = (spread_width - credit_received) * 100  # Convert to dollars

        if max_loss <= 0:
            return 0  # Invalid spread

        return self.calculate_iron_condor_size(max_loss, current_positions, max_positions)

    def adjust_for_correlation(self,
                              base_size: int,
                              correlation_factor: float) -> int:
        """
        Reduce position size for correlated positions
        correlation_factor: 0 = uncorrelated, 1 = perfectly correlated
        """
        # Reduce size by correlation factor
        # If correlation is 0.5, reduce size by 25% (0.5 * 0.5)
        reduction_factor = 1 - (correlation_factor * 0.5)
        adjusted_size = int(base_size * reduction_factor)

        return max(adjusted_size, 1)  # Minimum 1 contract
```

## Correlation Matrix Calculator

```python
class CorrelationAnalyzer:
    """
    Analyze correlations between positions for risk management
    """

    def __init__(self):
        self.sector_correlations = {
            ('TECH', 'TECH'): 0.8,
            ('TECH', 'FINANCE'): 0.5,
            ('TECH', 'ENERGY'): 0.3,
            ('FINANCE', 'FINANCE'): 0.7,
            ('FINANCE', 'ENERGY'): 0.4,
            ('ENERGY', 'ENERGY'): 0.9,
            # Add more sector correlations
        }

    def calculate_position_correlation(self,
                                      symbol1: str,
                                      symbol2: str,
                                      lookback_days: int = 60) -> float:
        """
        Calculate correlation between two symbols
        """
        # In production, fetch historical prices
        # For now, use sector-based estimates
        sector1 = self.get_sector(symbol1)
        sector2 = self.get_sector(symbol2)

        key = tuple(sorted([sector1, sector2]))
        return self.sector_correlations.get(key, 0.3)  # Default low correlation

    def build_correlation_matrix(self, positions: List[str]) -> np.ndarray:
        """
        Build correlation matrix for all positions
        """
        n = len(positions)
        matrix = np.ones((n, n))

        for i in range(n):
            for j in range(i + 1, n):
                corr = self.calculate_position_correlation(positions[i], positions[j])
                matrix[i, j] = corr
                matrix[j, i] = corr

        return matrix

    def calculate_portfolio_var(self,
                               positions: List[dict],
                               confidence_level: float = 0.95) -> float:
        """
        Calculate Value at Risk for portfolio
        """
        # Simplified VaR calculation
        position_risks = [p['max_loss'] for p in positions]
        correlations = self.build_correlation_matrix([p['symbol'] for p in positions])

        # Portfolio variance considering correlations
        portfolio_variance = 0
        for i in range(len(positions)):
            for j in range(len(positions)):
                portfolio_variance += (position_risks[i] * position_risks[j] *
                                      correlations[i, j])

        # Calculate VaR
        portfolio_std = np.sqrt(portfolio_variance)
        z_score = 1.645 if confidence_level == 0.95 else 2.326  # 95% or 99%
        var = portfolio_std * z_score

        return var

    def get_sector(self, symbol: str) -> str:
        """Map symbols to sectors"""
        # Simplified mapping - in production use proper data source
        tech_symbols = ['AAPL', 'GOOGL', 'MSFT', 'NVDA', 'AMD']
        finance_symbols = ['JPM', 'BAC', 'GS', 'WFC', 'C']
        energy_symbols = ['XOM', 'CVX', 'COP', 'SLB', 'OXY']

        if symbol in tech_symbols:
            return 'TECH'
        elif symbol in finance_symbols:
            return 'FINANCE'
        elif symbol in energy_symbols:
            return 'ENERGY'
        else:
            return 'OTHER'
```

## Risk Dashboard Implementation

```python
from typing import Dict, Any
import asyncio
from datetime import datetime, timedelta

class RiskDashboard:
    """
    Real-time risk monitoring dashboard
    """

    def __init__(self, account_service, position_service):
        self.account_service = account_service
        self.position_service = position_service
        self.risk_limits = {
            'max_daily_loss': 300,  # 3R
            'max_position_loss': 200,  # 2R
            'max_portfolio_delta': 0.30,
            'max_open_positions': 5,
            'min_buying_power': 1000
        }

    async def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Fetch all risk metrics for dashboard display
        """
        account = await self.account_service.get_account_state()
        positions = await self.position_service.get_open_positions()

        metrics = {
            'timestamp': datetime.now().isoformat(),
            'account': {
                'net_liquidating_value': account['net_liquidating_value'],
                'buying_power': account['buying_power'],
                'day_pnl': account.get('day_pnl', 0),
                'total_pnl': account.get('total_pnl', 0)
            },
            'positions': {
                'count': len(positions),
                'total_risk': sum(p.get('max_loss', 0) for p in positions),
                'total_delta': sum(p.get('delta', 0) for p in positions),
                'total_gamma': sum(p.get('gamma', 0) for p in positions),
                'total_theta': sum(p.get('theta', 0) for p in positions),
                'total_vega': sum(p.get('vega', 0) for p in positions)
            },
            'risk_checks': self._perform_risk_checks(account, positions),
            'alerts': self._generate_alerts(account, positions),
            'r_multiples': self._calculate_r_multiples(positions)
        }

        return metrics

    def _perform_risk_checks(self, account: dict, positions: list) -> dict:
        """
        Check all risk limits
        """
        checks = {}

        # Daily loss check
        daily_loss = account.get('day_pnl', 0)
        checks['daily_loss_ok'] = abs(daily_loss) <= self.risk_limits['max_daily_loss']

        # Portfolio delta check
        total_delta = sum(p.get('delta', 0) for p in positions)
        checks['delta_neutral'] = abs(total_delta) <= self.risk_limits['max_portfolio_delta']

        # Position count check
        checks['position_limit_ok'] = len(positions) <= self.risk_limits['max_open_positions']

        # Buying power check
        checks['buying_power_ok'] = account['buying_power'] >= self.risk_limits['min_buying_power']

        # Individual position risk check
        max_position_risk = max([p.get('max_loss', 0) for p in positions], default=0)
        checks['position_risk_ok'] = max_position_risk <= self.risk_limits['max_position_loss']

        checks['all_checks_passed'] = all(checks.values())

        return checks

    def _generate_alerts(self, account: dict, positions: list) -> list:
        """
        Generate risk alerts
        """
        alerts = []

        # Check for positions near expiry
        for pos in positions:
            if pos.get('dte', 999) <= 7:
                alerts.append({
                    'level': 'WARNING',
                    'message': f"Position {pos['symbol']} expiring in {pos['dte']} days",
                    'action': 'Consider closing position'
                })

        # Check for high delta positions
        for pos in positions:
            if abs(pos.get('delta', 0)) > 0.25:
                alerts.append({
                    'level': 'WARNING',
                    'message': f"Position {pos['symbol']} has high delta: {pos['delta']:.2f}",
                    'action': 'Monitor for adjustment'
                })

        # Check daily loss approaching limit
        daily_loss = abs(account.get('day_pnl', 0))
        if daily_loss > self.risk_limits['max_daily_loss'] * 0.75:
            alerts.append({
                'level': 'CRITICAL',
                'message': f"Daily loss ${daily_loss:.2f} approaching limit",
                'action': 'Consider stopping trading for the day'
            })

        return alerts

    def _calculate_r_multiples(self, positions: list) -> dict:
        """
        Calculate R-multiples for current positions
        """
        r_per_position = 100  # $100 per R

        closed_today = [p for p in positions if p.get('closed_today', False)]
        open_positions = [p for p in positions if not p.get('closed_today', False)]

        return {
            'closed_today_r': sum(p.get('pnl', 0) / r_per_position for p in closed_today),
            'open_risk_r': sum(p.get('max_loss', 0) / r_per_position for p in open_positions),
            'unrealized_r': sum(p.get('unrealized_pnl', 0) / r_per_position for p in open_positions)
        }

    async def start_monitoring(self, interval_seconds: int = 30):
        """
        Start continuous risk monitoring
        """
        while True:
            try:
                metrics = await self.get_dashboard_data()

                # Check for critical alerts
                critical_alerts = [a for a in metrics['alerts'] if a['level'] == 'CRITICAL']
                if critical_alerts:
                    await self._handle_critical_alerts(critical_alerts)

                # Log metrics
                self._log_metrics(metrics)

                await asyncio.sleep(interval_seconds)

            except Exception as e:
                print(f"Error in risk monitoring: {e}")
                await asyncio.sleep(interval_seconds)

    async def _handle_critical_alerts(self, alerts: list):
        """
        Handle critical risk alerts
        """
        for alert in alerts:
            # Send notifications (email, SMS, etc.)
            print(f"CRITICAL ALERT: {alert['message']}")

            # Take automated action if configured
            if 'daily_loss' in alert['message']:
                # Could automatically close all positions
                pass

    def _log_metrics(self, metrics: dict):
        """
        Log metrics for analysis
        """
        # In production, save to database or time-series store
        print(f"Risk Metrics at {metrics['timestamp']}")
        print(f"Portfolio Delta: {metrics['positions']['total_delta']:.2f}")
        print(f"Day P&L: ${metrics['account']['day_pnl']:.2f}")
        print(f"Open Positions: {metrics['positions']['count']}")
```

## Summary

This risk management system includes:

1. **Monte Carlo Simulations** for stress testing strategies
2. **Position Sizing** using Kelly Criterion (conservative 1/4 Kelly)
3. **Correlation Analysis** to avoid concentration risk
4. **Real-time Risk Dashboard** with automated alerts
5. **R-Multiple Tracking** for performance measurement

The system prioritizes capital preservation over optimization.
