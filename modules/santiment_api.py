import requests
import time
import logging

# --- IMPORTANT WARNING ---
# This module DOES NOT use the official Santiment API.
# It uses the FREE CoinGecko API as a *proxy*.
# The metrics 'whale_alert', 'social_dominance_spike', and 'active_address_spike'
# are DERIVED *heuristically* from CoinGecko's "sentiment_votes_up_percentage".
# This is a VERY ROUGH APPROXIMATION and NOT equivalent to Santiment's detailed,
# often paid, metrics. Use these derived values with extreme caution and understand
# they might not accurately reflect true whale activity, social dominance, or address activity.
# Consider subscribing to Santiment's API for accurate data.
# --- END WARNING ---


# Simple mapping (expand as needed)
COINGECKO_SLUGS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "SOL": "solana",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "SHIB": "shiba-inu",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    # Add more mappings as required
}

# Rate limit delay between CoinGecko calls
COINGECKO_DELAY = 1.5 # Increased delay for free tier


def fetch_social_metrics(symbol):
    """
    Fetches CoinGecko data and derives *approximate* social metrics.

    Args:
        symbol (str): The coin symbol (e.g., 'BTC').

    Returns:
        dict: A dictionary containing derived metrics:
              - 'cg_derived_whale_alert' (bool): Approximated based on high sentiment %.
              - 'cg_derived_social_dominance_spike' (bool): Approximated based on medium-high sentiment %.
              - 'cg_derived_active_address_spike' (bool): Approximated based on moderate sentiment %.
              Returns an empty dict if fetching fails or symbol not mapped.
    """
    slug = COINGECKO_SLUGS.get(symbol.upper())
    if not slug:
        logging.warning(f"[CoinGecko Proxy] No slug mapping for {symbol}, skipping social metrics.")
        return {}

    url = f"https://api.coingecko.com/api/v3/coins/{slug}"
    logging.info(f"[CoinGecko Proxy] Fetching social proxy data for {symbol} ({slug})")

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            logging.error(f"[CoinGecko Proxy] JSON decode error for {slug} ({symbol}). Response text: {response.text[:200]}")
            return {}

        # --- Derive metrics from sentiment percentage ---
        # This is a heuristic - adjust thresholds based on observation/testing.
        sentiment_score = data.get("sentiment_votes_up_percentage")

        if sentiment_score is None:
             logging.warning(f"[CoinGecko Proxy] Sentiment score not found for {slug} ({symbol}).")
             # Return default False values if score is missing
             return {
                "cg_derived_whale_alert": False,
                "cg_derived_social_dominance_spike": False,
                "cg_derived_active_address_spike": False,
                "cg_sentiment_score_used": None # Indicate score was missing
             }

        # Example thresholds (Adjust these based on analysis!)
        whale_threshold = 75
        social_dom_threshold = 65
        active_addr_threshold = 55

        derived_metrics = {
            "cg_derived_whale_alert": sentiment_score >= whale_threshold,
            "cg_derived_social_dominance_spike": sentiment_score >= social_dom_threshold,
            "cg_derived_active_address_spike": sentiment_score >= active_addr_threshold,
            "cg_sentiment_score_used": sentiment_score # Include the score used for derivation
        }

        logging.info(f"[CoinGecko Proxy] Derived metrics for {symbol}: {derived_metrics}")

        # Respect CoinGecko's rate limits, especially the free tier
        time.sleep(COINGECKO_DELAY)

        return derived_metrics

    except requests.exceptions.RequestException as e:
        logging.error(f"[CoinGecko Proxy] Request error for {symbol} ({slug}): {e}")
        return {}
    except Exception as e:
        # Catch any other unexpected errors during processing
        logging.error(f"[CoinGecko Proxy] Unexpected error for {symbol} ({slug}): {e}", exc_info=True)
        return {}
