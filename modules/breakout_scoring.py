import logging

def calculate_breakout_score(
    rsi,                  # Technical indicator value
    volume_rising,        # Boolean indicating if volume is trending up
    cg_derived_whale_alert=False, # APPROXIMATION from CoinGecko sentiment
    news_sentiment="neutral", # Can be 'positive', 'negative', 'neutral'
    spread_percent=None,  # Bid-ask spread as a percentage
    btc_inflow_spike=False, # Placeholder for exchange inflow data
    orderbook_thin=False, # Boolean indicating if order book lacks depth (often high spread)
    momentum_health="strong", # Can be 'strong', 'weak', 'oversold but healthy', 'unknown'
):
    """
    Calculates a score indicating the potential strength of a breakout setup.
    Uses a combination of technical, sentiment (basic), and on-chain (proxied/placeholder) factors.

    Args:
        rsi (float | None): RSI value (e.g., from 1h).
        volume_rising (bool): True if recent volume trend is increasing.
        cg_derived_whale_alert (bool): *Approximate* whale activity flag based on CoinGecko sentiment.
        news_sentiment (str): Basic news sentiment ('positive', 'negative', 'neutral').
        spread_percent (float | None): Bid-ask spread percentage.
        btc_inflow_spike (bool): Placeholder for significant BTC exchange inflow signal.
        orderbook_thin (bool): True if the order book is considered thin (e.g., high spread).
        momentum_health (str): Overall health of momentum ('strong', 'weak', etc.).

    Returns:
        int: A score from roughly -4 to 8 (adjust ranges as needed). Higher is better.
    """
    score = 0
    score_factors = [] # Keep track of contributing factors for logging/debugging

    # --- Positive Factors ---
    if momentum_health == "strong":
        score += 2
        score_factors.append("strong_momentum(+2)")
    elif momentum_health == "oversold but healthy":
         score += 1 # Slight boost for potential reversal from oversold
         score_factors.append("oversold_healthy(+1)")

    if rsi is not None and 40 <= rsi < 70: # RSI in a healthy, non-overbought range
        score += 1
        score_factors.append("rsi_healthy_range(+1)")

    if volume_rising:
        score += 1
        score_factors.append("volume_rising(+1)")

    if news_sentiment == "positive":
        score += 1
        score_factors.append("positive_news(+1)")

    # Use the CoinGecko derived proxy flag - Use with caution!
    if cg_derived_whale_alert:
        score += 1 # Reduced score compared to original, as it's less reliable
        score_factors.append("cg_derived_whale_alert(+1)")

    if spread_percent is not None and spread_percent < 0.5: # Tight spread is favorable
        score += 1
        score_factors.append("tight_spread(<0.5%)(+1)")

    # --- Negative Factors (Cautions) ---
    if orderbook_thin: # Often correlated with high spread, but check explicitly
        score -= 1 # Penalty for thin liquidity
        score_factors.append("thin_orderbook(-1)")

    if btc_inflow_spike: # Placeholder - strong BTC inflows can sometimes precede market dumps
        score -= 2
        score_factors.append("btc_inflow_spike(-2)")

    if rsi is not None and rsi >= 75: # Overbought RSI is a caution
        score -= 1
        score_factors.append("rsi_overbought(>=75)(-1)")

    if news_sentiment == "negative":
        score -= 1
        score_factors.append("negative_news(-1)")

    # Log the scoring breakdown for debugging/transparency
    # logging.debug(f"Breakout Score Calculation: Base=0, Factors={score_factors}, Final Score={score}")

    # Ensure score isn't excessively negative (optional)
    # score = max(-5, score)

    return score
