from datetime import datetime

def get_buy_window():
    """
    Suggest optimal buy timing based on UTC hour.
    Returns a string representing current market phase and advice.
    """
    hour = datetime.utcnow().hour

    if 0 <= hour < 6:
        return "Asia low-volume hours. Buy only coins with strong social or whale confirmation."
    elif 6 <= hour < 12:
        return "EU buildup hours. Look for early breakouts with rising volume."
    elif 12 <= hour < 17:
        return "US prime time. Best entry window if breakout is confirmed."
    elif 17 <= hour < 21:
        return "Late session. Only continue trending setups."
    else:
        return "Low liquidity hours. Avoid new buys unless urgent news."
