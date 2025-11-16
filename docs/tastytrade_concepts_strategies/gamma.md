# Gamma

Source: https://www.tastylive.com/concepts-strategies/gamma

Gamma measures the sensitivity of an option's delta to price changes in the underlying asset. It indicates how much an option's delta will adjust when the underlying asset's price increases or decreases by $1.

**How Gamma Works:**
Gamma is a crucial concept in options trading, signifying the rate at which an option's delta changes with a $1 movement in the underlying stock's price. Its value ranges between 0 and +1.

*   **Long Options (Calls or Puts):** Have "positive gamma." When the stock price rises, gamma is added to the option's delta. When the stock price falls, gamma is subtracted from the delta.
    *   *Example:* A long call option with a delta of 0.40 and a gamma of 0.10. If the stock price increases by $1, the new delta becomes 0.50 (0.40 + 0.10). If the stock price decreases by $1, the new delta becomes 0.30 (0.40 - 0.10).
*   **Short Options:** Have "negative gamma." When the stock price increases, gamma is subtracted from the option's delta. When the stock price declines, gamma is added to the delta.
    *   *Example:* A short call option with a delta of -0.25 and a gamma of 0.05. If the stock price increases by $1, the new delta becomes -0.30 (-0.25 - 0.05). If the stock price decreases by $1, the new delta becomes -0.20 (-0.25 + 0.05).

Gamma is generally higher for at-the-money (ATM) and in-the-money (ITM) options because they are more sensitive to underlying price movements than out-of-the-money (OTM) options. Options with higher gamma are more responsive to price changes, meaning their deltas can change more quickly.

**How to Calculate Gamma:**
Gamma is calculated by dividing the change in delta by the change in the underlying price:
Gamma = (D1 - D2) / (P1 - P2)
Where P1 is the original underlying stock price, P2 is the new price, D1 is the delta at P1, and D2 is the delta at P2.

**What Gamma Tells You:**
Gamma quantifies how much an option's delta will change when the underlying stock price moves up or down by $1. A higher gamma indicates that an option's delta will be more responsive to changes in the underlying stock price, while a lower gamma suggests less sensitivity.

**Gamma Hedging:**
Some options traders use gamma hedging in conjunction with delta-neutral hedging to reduce directional risk. This involves adjusting stock hedges (which are used to make a position delta-neutral) as stock prices change. Gamma hedging is typically part of a volatility-based trading approach.

**Key Takeaways:**
*   Gamma is a measure of the rate of change of an option's delta.
*   Long options have positive gamma, while short options have negative gamma.
*   Higher gamma means delta will change more rapidly with underlying price movements.
*   Gamma is highest for ATM and ITM options.
*   Gamma hedging is used to manage the maintenance of delta hedges.
