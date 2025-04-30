def calculate_breakout_score(
    rsi,
    volume_rising,
    whale_alert=False,
    news_sentiment="neutral",
    spread_percent=None,
    btc_inflow_spike=False,
    orderbook_thin=False,
    momentum_health="strong",
):
    score = 0

    # Technical + Sentiment
    if momentum_health == "strong":
        score += 2
    if rsi is not None and rsi < 70:
        score += 1
    if news_sentiment == "positive":
        score += 1
    if whale_alert:
        score += 2
    if volume_rising:
        score += 1
    if spread_percent is not None and spread_percent < 0.8:
        score += 1

    # Cautions
    if orderbook_thin:
        score -= 2
    if btc_inflow_spike:
        score -= 2

    return score
