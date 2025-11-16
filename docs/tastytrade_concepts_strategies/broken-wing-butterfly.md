# Broken Wing Butterfly

Source: https://www.tastylive.com/concepts-strategies/broken-wing-butterfly

A broken wing butterfly is a long butterfly spread where the long strikes are not equidistant from the short strike, making the trade slightly more directional than a standard long butterfly spread. This strategy can also be viewed as a ratio spread with defined risk. The widest out-of-the-money (OTM) wing, known as the "broken wing," eliminates risk on the OTM side when the trade is executed for a net credit. It essentially combines a debit spread and a credit spread with short options on the same strike, where the credit spread is wider and fully finances the debit spread portion.

The main objective of this net credit strategy is to increase the probability of profit (POP) by taking a credit on entry, thus eliminating the risk of losing money if the entire spread expires OTM.

Compared to a regular butterfly, a broken wing butterfly ensures the debit spread portion is narrower than the credit spread portion, allowing for an upfront credit and no risk to the OTM side.

**Key characteristics of a Broken Wing Butterfly:**
*   **Definition:** A net credit, high probability trade that can be profitable even if the directional speculation is wrong.
*   **Directional Assumption:** Neutral to slightly directional.
*   **Ideal Implied Volatility Environment:** High.
*   **Setup:** Preferable in high implied volatility (IV) environments, looking for underlyings with high IV rank and IV%. It's constructed with either all calls or all puts, comprising two short options and a long option above and below the short strike.
    *   Buy call or put (above short strike)
    *   Sell two calls or puts
    *   Buy call or put (below short strike)
*   **tastylive Approach:** Always route for a credit to eliminate downside risk if the spread expires OTM, which significantly improves the probability of profit.
*   **Closing & Managing:** Aim to close when 50% of the max profit is achieved, typically when the closest long option goes in-the-money (ITM) near expiration. If the spread moves unfavorably, the long spread aspect can be closed for max profit, and the remaining short spread can potentially be rolled out in time for a credit.
*   **Profit & Loss:** Profits when the stock price stays the same, IV decreases, or the stock moves towards the short strikes. Max profit is calculated as the width of the narrower debit spread plus the credit received. Max loss is capped at the furthest OTM long option and can be calculated as the width of the credit spread minus the width of the narrow debit spread minus the credit received.
*   **Breakevens:** Slightly wider than a regular butterfly due to the collected credit offsetting the breakeven price past the short strike.

**Comparison with Credit Spread:**
Both broken wing butterflies and credit spreads offer defined-risk ways to profit from options trading. While a credit spread can be profitable, a broken wing butterfly also has a high probability of profit. The broken wing butterfly involves two short and two long options, while a credit spread involves one long and one short option.
