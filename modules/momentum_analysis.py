import numpy as np

# --- RSI Calculation ---
def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    delta = np.diff(closes)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)

    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])

    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period

    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)


# --- Volume Trend Analysis ---
def detect_volume_divergence(volumes):
    if len(volumes) < 3:
        return False
    return volumes[-1] < volumes[-2] < volumes[-3]  # decreasing volume


# --- Health Score Function ---
def calculate_momentum_health(rsi, volume_divergence):
    if rsi is None:
        return "unknown"
    if rsi > 80 or volume_divergence:
        return "weak"
    elif rsi < 35:
        return "oversold but healthy"
    else:
        return "strong"
