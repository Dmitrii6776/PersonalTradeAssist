import logging

# Define thresholds for CoinGecko metrics (tune these based on observation)
CG_COMMUNITY_SCORE_THRESHOLD = 60
CG_DEVELOPER_SCORE_THRESHOLD = 65
CG_PUBLIC_INTEREST_SCORE_THRESHOLD = 30 # Public interest score seems lower generally
CG_SENTIMENT_THRESHOLD = 70 # Percentage

def calculate_breakout_score(
    rsi,
    volume_rising,
    # cg_derived_whale_alert=False, # REMOVED OLD PARAMETER
    news_sentiment="neutral",
    spread_percent=None,
    btc_inflow_spike=False, # Placeholder
    orderbook_thin=False,
    momentum_health="strong",
    # --- ADD NEW PARAMETERS ---
    cg_sentiment_percentage=None,
    cg_community_score=None,
    cg_developer_score=None,
    cg_public_interest_score=None
):
    """
    Calculates a score indicating the potential strength of a breakout setup.
    Uses a combination of technical, basic news sentiment, and CoinGecko metrics.

    NOTE: CoinGecko metrics are used as proxies for community/developer/public
          interest and general sentiment. They are NOT direct on-chain metrics.

    Args:
        rsi (float | None): RSI value (e.g., from 1h).
        volume_rising (bool): True if recent volume trend is increasing.
        news_sentiment (str): Basic news sentiment ('positive', 'negative', 'neutral').
        spread_percent (float | None): Bid-ask spread percentage.
        btc_inflow_spike (bool): Placeholder for significant BTC exchange inflow signal.
        orderbook_thin (bool): True if the order book is considered thin.
        momentum_health (str): Overall health of momentum ('strong', 'weak', etc.).
        cg_sentiment_percentage (float | None): CoinGecko sentiment votes up percentage.
        cg_community_score (float | None): CoinGecko community score.
        cg_developer_score (float | None): CoinGecko developer score.
        cg_public_interest_score (float | None): CoinGecko public interest score.


    Returns:
        int: A score. Higher is generally better. The range might shift based on factors.
             Typical range aims for roughly -3 to +8, but tune based on results.
    """
    score = 0
    score_factors = [] # Keep track of contributing factors

    # --- Core Technical & Momentum Factors ---
    if momentum_health == "strong":
        score += 2
        score_factors.append("strong_momentum(+2)")
    elif momentum_health == "oversold but healthy":
         score += 1
         score_factors.append("oversold_healthy(+1)")

    if rsi is not None:
        if 40 <= rsi < 70: # Healthy range
            score += 1
            score_factors.append("rsi_healthy_range(+1)")
        elif rsi >= 75: # Overbought caution
            score -= 1
            score_factors.append("rsi_overbought(>=75)(-1)")
        # Note: RSI < 40 doesn't directly add/subtract here, covered partly by momentum_health

    if volume_rising:
        score += 1
        score_factors.append("volume_rising(+1)")

    if spread_percent is not None and spread_percent < 0.5: # Tight spread is favorable
        score += 1
        score_factors.append("tight_spread(<0.5%)(+1)")

    # --- News & Sentiment Factors ---
    if news_sentiment == "positive":
        score += 1
        score_factors.append("positive_news(+1)")
    elif news_sentiment == "negative":
        score -= 1
        score_factors.append("negative_news(-1)")

    # --- CoinGecko Proxy Metrics ---
    # Add points based on relatively strong CoinGecko scores (tune thresholds)
    if cg_community_score is not None and cg_community_score >= CG_COMMUNITY_SCORE_THRESHOLD:
        score += 1
        score_factors.append(f"cg_community_score(>={CG_COMMUNITY_SCORE_THRESHOLD})(+1)")

    if cg_developer_score is not None and cg_developer_score >= CG_DEVELOPER_SCORE_THRESHOLD:
        score += 1
        score_factors.append(f"cg_developer_score(>={CG_DEVELOPER_SCORE_THRESHOLD})(+1)")

    if cg_public_interest_score is not None and cg_public_interest_score >= CG_PUBLIC_INTEREST_SCORE_THRESHOLD:
        score += 1
        score_factors.append(f"cg_public_interest(>={CG_PUBLIC_INTEREST_SCORE_THRESHOLD})(+1)")

    # Use sentiment percentage carefully - maybe only add if very high
    if cg_sentiment_percentage is not None and cg_sentiment_percentage >= CG_SENTIMENT_THRESHOLD:
         score += 1
         score_factors.append(f"cg_sentiment(>={CG_SENTIMENT_THRESHOLD}%)(+1)")


    # --- Negative Factors / Cautions ---
    if orderbook_thin: # Thin liquidity is a risk
        score -= 1
        score_factors.append("thin_orderbook(-1)")

    if btc_inflow_spike: # Placeholder for potential market-wide risk
        score -= 2
        score_factors.append("btc_inflow_spike(-2)")

    # Log the scoring breakdown for debugging/transparency
    logging.debug(f"Breakout Score Calculation: Base=0, Factors={score_factors}, Final Score={score}")

    # Optional: Clamp score range if needed
    # score = max(-5, min(10, score))

    return score
