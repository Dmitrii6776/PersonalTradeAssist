import numpy as np
import logging

# --- RSI Calculation ---
def calculate_rsi(closes, period=14):
    """
    Calculates the Relative Strength Index (RSI).

    Args:
        closes (list or np.array): List of closing prices.
        period (int): The RSI period (default 14).

    Returns:
        float | None: The calculated RSI value, or None if not enough data.
    """
    if closes is None or len(closes) < period + 1:
        # logging.debug(f"Not enough data for RSI calculation (need {period + 1}, got {len(closes) if closes else 0})")
        return None

    try:
        closes_array = np.array(closes, dtype=float)
        delta = np.diff(closes_array)

        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        # Use simple moving average for the first calculation
        avg_gain = np.mean(gain[:period])
        avg_loss = np.mean(loss[:period])

        if avg_loss == 0: # Prevent division by zero; RSI is 100 if no losses
             if avg_gain == 0: # If no gains either, RSI is undefined (or neutral 50)
                  return 50.0
             return 100.0

        # Use Wilder's smoothing (exponential moving average) for subsequent calculations
        for i in range(period, len(delta)):
            avg_gain = (avg_gain * (period - 1) + gain[i]) / period
            avg_loss = (avg_loss * (period - 1) + loss[i]) / period
            # Check for zero avg_loss again inside loop if needed, though less likely after first calc
            if avg_loss == 0: avg_loss = 0.00001 # Add tiny value to prevent later division by zero

        rs = avg_gain / avg_loss if avg_loss != 0 else 100 # Handle potential division by zero again
        rsi = 100.0 - (100.0 / (1.0 + rs))

        return round(rsi, 2)

    except (ValueError, TypeError, IndexError) as e:
         logging.error(f"Error calculating RSI: {e}", exc_info=True)
         return None
    except Exception as e: # Catch any other numpy errors etc.
         logging.error(f"Unexpected error during RSI calculation: {e}", exc_info=True)
         return None


# --- Volume Trend Analysis ---
def detect_volume_divergence(volumes, lookback=3):
    """
    Detects if volume has been consistently decreasing over the lookback period.
    Simple check for decreasing volume, not a complex divergence pattern.

    Args:
        volumes (list or np.array): List of volume data.
        lookback (int): Number of recent periods to check (default 3).

    Returns:
        bool: True if volume decreased over the lookback period, False otherwise or if not enough data.
    """
    if volumes is None or len(volumes) < lookback:
        return False # Not enough data to detect divergence

    try:
        recent_volumes = np.array(volumes[-lookback:], dtype=float)
        # Check if each volume is less than the previous one
        is_decreasing = all(recent_volumes[i] < recent_volumes[i-1] for i in range(1, lookback))
        return is_decreasing
    except (ValueError, TypeError, IndexError) as e:
        logging.warning(f"Could not detect volume divergence due to data error: {e}")
        return False # Treat data errors as non-divergent for safety


# --- Health Score Function ---
def calculate_momentum_health(rsi, volume_divergence):
    """
    Provides a qualitative assessment of momentum health based on RSI and volume trend.

    Args:
        rsi (float | None): The calculated RSI value.
        volume_divergence (bool | None): True if volume is decreasing/diverging.

    Returns:
        str: 'strong', 'weak', 'oversold but healthy', or 'unknown'.
    """
    if rsi is None:
        return "unknown"

    # Volume divergence is often a strong warning sign
    if volume_divergence is True: # Explicitly check for True
        return "weak"

    # RSI based conditions
    if rsi > 75: # Extended threshold for "weak" due to overbought
        return "weak"
    elif rsi < 30: # Adjusted threshold for oversold
        return "oversold but healthy" # Potential bounce area, but needs confirmation
    elif 40 <= rsi <= 65: # Healthy momentum range
         return "strong"
    else:
         # Covers 30-40 and 65-75 ranges, treat as neutral/less strong
         return "neutral" # Changed from 'strong' to be more nuanced
