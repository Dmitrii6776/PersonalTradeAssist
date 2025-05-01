from datetime import datetime, timezone

def get_buy_window():
    """
    Suggests general market conditions based on UTC hour, representing different trading sessions.
    This is a very broad generalization.

    Returns:
        str: A note about the current approximate market phase based on UTC time.
    """
    # Ensure we use UTC time
    hour = datetime.now(timezone.utc).hour

    if 0 <= hour < 6: # Roughly Asian session main hours overlap
        return "Asia Session Focus: Monitor for overnight moves, potentially lower liquidity."
    elif 6 <= hour < 12: # Roughly London/EU open overlap
        return "EU Session Focus: Increased volume often starts, watch for early trends."
    elif 12 <= hour < 17: # US/London Overlap - Peak liquidity/volatility often here
        return "US/EU Overlap Prime Time: Highest liquidity expected, key breakout window."
    elif 17 <= hour < 21: # US Afternoon session
        return "US Late Session: Volume may decline, focus on established trends."
    else: # US Close / Asia pre-open
        return "Late US / Early Asia Transition: Liquidity typically drops, caution advised."
