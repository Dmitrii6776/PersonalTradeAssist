import requests
import time
import logging
import json
import os
from threading import Lock, Timer

# --- Configuration ---
COINGECKO_API_BASE = "https://api.coingecko.com/api/v3"
# Delay between CoinGecko API calls (seconds) - crucial for free tier
# CoinGecko free tier limit is roughly 10-30 calls/minute. Be conservative.
COINGECKO_DELAY = 6.0
# How often to refresh the coin list cache (seconds)
CACHE_REFRESH_INTERVAL = 6 * 60 * 60 # 6 hours

# --- Global Cache ---
# Stores mapping: SYMBOL.UPPER() -> coin_id (slug)
_COIN_LIST_CACHE = {}
_CACHE_LOCK = Lock()
_CACHE_LAST_UPDATED = 0

# --- Logging ---
log = logging.getLogger(__name__) # Use module-specific logger

# --- Helper Functions ---

def _fetch_all_coins_list():
    """Fetches the complete list of coins from CoinGecko."""
    url = f"{COINGECKO_API_BASE}/coins/list?include_platform=false"
    log.info("Attempting to fetch full coin list from CoinGecko...")
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        coins = response.json()
        log.info(f"Successfully fetched {len(coins)} coin list entries from CoinGecko.")
        time.sleep(COINGECKO_DELAY) # Apply delay after successful call
        return coins
    except requests.exceptions.RequestException as e:
        log.error(f"Failed to fetch CoinGecko coin list: {e}")
        return None
    except json.JSONDecodeError as e:
        log.error(f"Failed to decode CoinGecko coin list JSON: {e}")
        return None

def _update_coin_list_cache(force_update=False):
    """Updates the global coin list cache mapping SYMBOL -> slug."""
    global _COIN_LIST_CACHE, _CACHE_LAST_UPDATED

    now = time.time()
    # Check if update is needed based on interval or if forced
    if not force_update and (now - _CACHE_LAST_UPDATED) < CACHE_REFRESH_INTERVAL and _COIN_LIST_CACHE:
        # log.debug("Coin list cache is up-to-date.")
        return

    log.info("Updating CoinGecko coin list cache...")
    coins_list = _fetch_all_coins_list()
    if not coins_list:
        log.error("Could not update coin list cache: fetch failed.")
        # Optionally schedule a retry later if needed
        return

    new_cache = {}
    duplicates = {} # Track symbols with multiple slugs

    for coin in coins_list:
        symbol = coin.get('symbol', '').upper()
        coin_id = coin.get('id')
        if not symbol or not coin_id:
            continue

        if symbol in new_cache:
            # Handle duplicate symbols
            if symbol not in duplicates:
                duplicates[symbol] = [new_cache[symbol]] # Store the first one encountered
            duplicates[symbol].append(coin_id)
            # Keep the first encountered slug for simplicity, log the warning
            # log.warning(f"Duplicate symbol '{symbol}' found. Keeping first slug '{new_cache[symbol]}'. Other slugs: {duplicates[symbol][1:]}")
        else:
             new_cache[symbol] = coin_id # Map uppercase symbol to slug (id)

    if duplicates:
         log.warning(f"Found {len(duplicates)} duplicate symbols during cache update. Using first encountered slug. Duplicates: {list(duplicates.keys())}")


    with _CACHE_LOCK:
        _COIN_LIST_CACHE = new_cache
        _CACHE_LAST_UPDATED = now
        log.info(f"Coin list cache updated successfully with {len(_COIN_LIST_CACHE)} unique symbols.")

    # Optional: Schedule the next update if running continuously
    # Timer(CACHE_REFRESH_INTERVAL, _update_coin_list_cache).start()


def _get_slug_for_symbol(symbol):
    """Looks up the CoinGecko slug (id) for a given symbol using the cache."""
    # Ensure cache is populated on first call if needed
    if not _COIN_LIST_CACHE or time.time() - _CACHE_LAST_UPDATED > CACHE_REFRESH_INTERVAL:
         _update_coin_list_cache() # Update synchronously if cache is empty/stale

    with _CACHE_LOCK:
        return _COIN_LIST_CACHE.get(symbol.upper()) # Case-insensitive lookup


# --- Main Fetch Function ---

def fetch_coingecko_metrics(symbol):
    """
    Fetches various metrics for a given symbol from CoinGecko using its API.

    !! IMPORTANT !! This uses the CoinGecko API, NOT the Santiment API.
    The metrics returned are directly from CoinGecko and should be
    interpreted accordingly. They are NOT equivalent to Santiment's metrics.

    Args:
        symbol (str): The coin symbol (e.g., 'BTC', 'ETH').

    Returns:
        dict: A dictionary containing raw metrics fetched from CoinGecko, prefixed
              with 'cg_'. Returns an empty dict if the symbol is not found
              or if the API request fails. Example keys:
              'cg_slug', 'cg_sentiment_votes_up_percentage', 'cg_community_score',
              'cg_developer_score', 'cg_public_interest_score', etc.
    """
    coin_id = _get_slug_for_symbol(symbol)
    if not coin_id:
        log.warning(f"[CoinGecko Proxy] No slug found in cache for symbol '{symbol}'. Skipping metrics.")
        return {}

    url = f"{COINGECKO_API_BASE}/coins/{coin_id}?localization=false&tickers=false&market_data=false&community_data=true&developer_data=true&sparkline=false"
    log.info(f"[CoinGecko Proxy] Fetching metrics for {symbol} (using slug: {coin_id})")

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Extract relevant metrics, handling potential missing keys
        metrics = {'cg_slug': coin_id} # Include the slug used

        # Basic Scores
        metrics['cg_sentiment_votes_up_percentage'] = data.get('sentiment_votes_up_percentage')
        metrics['cg_community_score'] = data.get('community_score')
        metrics['cg_developer_score'] = data.get('developer_score')
        metrics['cg_public_interest_score'] = data.get('public_interest_score')

        # Community Data (Example)
        community = data.get('community_data', {})
        metrics['cg_twitter_followers'] = community.get('twitter_followers')
        metrics['cg_reddit_subscribers'] = community.get('reddit_subscribers')

        # Public Interest Stats (Example)
        interest = data.get('public_interest_stats', {})
        metrics['cg_alexa_rank'] = interest.get('alexa_rank')

        # Filter out None values before returning? Optional.
        # metrics = {k: v for k, v in metrics.items() if v is not None}

        log.info(f"[CoinGecko Proxy] Successfully fetched metrics for {symbol}")
        time.sleep(COINGECKO_DELAY) # Apply delay after successful call
        return metrics

    except requests.exceptions.RequestException as e:
        log.error(f"[CoinGecko Proxy] Request error for {symbol} (slug: {coin_id}): {e}")
        return {}
    except json.JSONDecodeError as e:
        log.error(f"[CoinGecko Proxy] JSON decode error for {symbol} (slug: {coin_id}): {e}")
        return {}
    except Exception as e:
        log.error(f"[CoinGecko Proxy] Unexpected error fetching metrics for {symbol} (slug: {coin_id}): {e}", exc_info=True)
        return {}

# --- Initial Cache Population ---
# Populate the cache when the module is first loaded.
# In a multi-process environment (like gunicorn workers), each process might do this.
_update_coin_list_cache(force_update=True)

# --- Example Usage (for testing) ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    log.info("Testing CoinGecko Proxy Module...")

    test_symbols = ["BTC", "ETH", "SOL", "NONEXISTENT", "HOT", "ADA"]
    for sym in test_symbols:
        print("-" * 20)
        metrics = fetch_coingecko_metrics(sym)
        if metrics:
            print(f"Metrics for {sym}:")
            for k, v in metrics.items():
                print(f"  {k}: {v}")
        else:
            print(f"Could not fetch metrics for {sym}")
