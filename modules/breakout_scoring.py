# --- START OF FILE modules/breakout_scoring.py ---
import logging

# Define thresholds for CoinGecko metrics (tune these based on observation)
# These determine the minimum score required to get a bonus point
CG_COMMUNITY_SCORE_THRESHOLD = 60
CG_DEVELOPER_SCORE_THRESHOLD = 65
CG_PUBLIC_INTEREST_SCORE_THRESHOLD = 30 # Public interest score seems lower generally
CG_SENTIMENT_THRESHOLD = 70 # Percentage

def calculate_breakout_score(
    # --- Technical / Market Factors ---
    rsi,
    volume_rising,
    spread_percent=None,
    orderbook_thin=False,
    momentum_health="strong",
    # --- Contextual Factors ---
    news_sentiment="neutral",
    btc_inflow_spike=False, # Placeholder
    # --- CoinGecko Proxy Metrics (NEW) ---
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
        spread_percent (float | None): Bid-ask spread percentage.
        orderbook_thin (bool): True if the order book is considered thin.
        momentum_health (str): Overall health of momentum ('strong', 'weak', etc.).
        news_sentiment (str): Basic news sentiment ('positive', 'negative', 'neutral').
        btc_inflow_spike (bool): Placeholder for significant BTC exchange inflow signal.
        cg_sentiment_percentage (float | None): CoinGecko sentiment votes up percentage.
        cg_community_score (float | None): CoinGecko community score.
        cg_developer_score (float | None): CoinGecko developer score.
        cg_public_interest_score (float | None): CoinGecko public interest score.


    Returns:
        int: A score. Higher is generally better.
             Typical range aims for roughly -3 to +8, but tune based on results.
    """
    score = 0
    score_factors = [] # Keep track of contributing factors for logging/debugging

    # --- Core Technical & Momentum Factors ---
    if momentum_health == "strong":
        score += 2
        score_factors.append("strong_momentum(+2)")
    elif momentum_health == "oversold but healthy":
         score += 1
         score_factors.append("oversold_healthy(+1)")
    # Optionally add penalty for 'weak' momentum if desired:
    # elif momentum_health == "weak":
    #     score -= 1
    #     score_factors.append("weak_momentum(-1)")


    if rsi is not None:
        if 40 <= rsi < 70: # Healthy range
            score += 1
            score_factors.append("rsi_healthy_range(+1)")
        elif rsi >= 75: # Overbought caution
            score -= 1
            score_factors.append("rsi_overbought(>=75)(-1)")

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
        score -= 1 # Penalize negative news
        score_factors.append("negative_news(-1)")

    # --- CoinGecko Proxy Metrics ---
    # Add points based on relatively strong CoinGecko scores (check for None)
    if cg_community_score is not None and cg_community_score >= CG_COMMUNITY_SCORE_THRESHOLD:
        score += 1
        score_factors.append(f"cg_community_score(>={CG_COMMUNITY_SCORE_THRESHOLD})(+1)")

    if cg_developer_score is not None and cg_developer_score >= CG_DEVELOPER_SCORE_THRESHOLD:
        score += 1
        score_factors.append(f"cg_developer_score(>={CG_DEVELOPER_SCORE_THRESHOLD})(+1)")

    if cg_public_interest_score is not None and cg_public_interest_score >= CG_PUBLIC_INTEREST_SCORE_THRESHOLD:
        score += 1
        score_factors.append(f"cg_public_interest(>={CG_PUBLIC_INTEREST_SCORE_THRESHOLD})(+1)")

    if cg_sentiment_percentage is not None and cg_sentiment_percentage >= CG_SENTIMENT_THRESHOLD:
         score += 1
         score_factors.append(f"cg_sentiment(>={CG_SENTIMENT_THRESHOLD}%)(+1)")


    # --- Negative Factors / Cautions ---
    if orderbook_thin: # Thin liquidity is a risk (often correlated with high spread)
        score -= 1
        score_factors.append("thin_orderbook(-1)")

    if btc_inflow_spike: # Placeholder for potential market-wide risk
        score -= 2
        score_factors.append("btc_inflow_spike(-2)")

    # Log the scoring breakdown for debugging/transparency
    # Use debug level so it doesn't spam info logs
    logging.debug(f"Breakout Score Calculation: Factors={score_factors}, Final Score={score}")

    # Optional: Clamp score range if needed, e.g., between -5 and 10
    # score = max(-5, min(10, score))

    return score
# --- END OF FILE modules/breakout_scoring.py ---
