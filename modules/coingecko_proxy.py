import requests
import time
import logging
import json
import os
from threading import Lock

# --- Configuration ---
COINGECKO_API_BASE = "https://api.coingecko.com/api/v3"
# Delay between CoinGecko API calls (seconds) - crucial for free tier
# CoinGecko free tier limit is roughly 10-30 calls/minute. Be conservative.
COINGECKO_DELAY = 6.0 # Increased delay to avoid rate limiting
# How often to refresh the coin list cache (seconds)
LIST_CACHE_REFRESH_INTERVAL = 6 * 60 * 60 # 6 hours for coin LIST cache
# Cache duration for individual coin details (seconds)
COIN_DETAIL_CACHE_DURATION = 2 * 60 * 60 # Cache individual coin data for 2 hours

# --- Global Caches ---
# Stores mapping: SYMBOL.UPPER() -> coin_id (slug)
_COIN_LIST_CACHE = {}
# Stores mapping: coin_id -> (timestamp, data_dict)
_COIN_DETAIL_CACHE = {}
# Lock for thread safety when accessing caches
_CACHE_LOCK = Lock()
# Timestamp of the last successful coin LIST update
_LIST_CACHE_LAST_UPDATED = 0

# --- Logging ---
# Use a module-specific logger for better organization
log = logging.getLogger(__name__)

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
        # Apply delay *after* successful call, before returning
        time.sleep(COINGECKO_DELAY)
        return coins
    except requests.exceptions.RequestException as e:
        log.error(f"Failed to fetch CoinGecko coin list: {e}")
        return None
    except json.JSONDecodeError as e:
        log.error(f"Failed to decode CoinGecko coin list JSON: {e}. Response text: {response.text[:200]}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching coin list: {e}", exc_info=True)
        return None

def _update_coin_list_cache(force_update=False):
    """
    Updates the global coin list cache mapping SYMBOL -> slug.
    This function DEFINITION must exist before it's called by _get_slug_for_symbol.
    """
    global _COIN_LIST_CACHE, _LIST_CACHE_LAST_UPDATED

    now = time.time()
    # Check if update is needed based on interval or if forced
    if not force_update and _COIN_LIST_CACHE and (now - _LIST_CACHE_LAST_UPDATED) < LIST_CACHE_REFRESH_INTERVAL:
        # log.debug("Coin list cache is up-to-date.")
        return

    log.info("Updating CoinGecko coin list cache...")
    coins_list = _fetch_all_coins_list()
    if not coins_list:
        log.error("Could not update coin list cache: fetch failed.")
        # Keep the old cache in case of temporary failure
        return

    new_cache = {}
    duplicates = {} # Track symbols with multiple slugs

    for coin in coins_list:
        # Ensure keys exist and are strings before calling methods
        symbol_raw = coin.get('symbol')
        coin_id = coin.get('id')

        if not isinstance(symbol_raw, str) or not isinstance(coin_id, str) or not symbol_raw or not coin_id:
            # log.warning(f"Skipping invalid coin entry in list: {coin}")
            continue

        symbol = symbol_raw.upper() # Now safe to call upper()

        if symbol in new_cache:
            # Handle duplicate symbols
            if symbol not in duplicates:
                duplicates[symbol] = [new_cache[symbol]] # Store the first one encountered
            duplicates[symbol].append(coin_id)
            # Decision: Keep the first encountered slug for simplicity. Log warning later.
        else:
             new_cache[symbol] = coin_id # Map uppercase symbol to slug (id)

    if duplicates:
         # Log only once after processing the whole list
         log.warning(f"Found {len(duplicates)} duplicate symbols during cache update. Using first encountered slug for these symbols: {list(duplicates.keys())}")

    # Safely update the global cache
    with _CACHE_LOCK:
        _COIN_LIST_CACHE = new_cache
        _LIST_CACHE_LAST_UPDATED = now
        log.info(f"Coin list cache updated successfully with {len(_COIN_LIST_CACHE)} unique symbols.")

def _get_slug_for_symbol(symbol):
    """Looks up the CoinGecko slug (id) for a given symbol using the cache."""
    global _LIST_CACHE_LAST_UPDATED # Ensure global is referenced for read
    now = time.time()

    # Acquire lock early to prevent race conditions on checking/updating cache
    with _CACHE_LOCK:
        # Check if cache needs update (empty or stale)
        if not _COIN_LIST_CACHE or (now - _LIST_CACHE_LAST_UPDATED) > LIST_CACHE_REFRESH_INTERVAL:
            # Release lock before calling update to avoid holding it during API call
            # Note: This means multiple threads might trigger update, but that's okay
            # as _update_coin_list_cache handles internal locking for the final assignment.
            # If strict single update is needed, keep lock or use different mechanism.
            pass # Lock will be released after 'with' block
        else:
            # Cache is likely okay, just perform lookup
            return _COIN_LIST_CACHE.get(symbol.upper()) # Case-insensitive lookup

    # Lock released here. If update needed, call it now.
    # This check runs again to be sure, in case another thread updated it.
    if not _COIN_LIST_CACHE or (now - _LIST_CACHE_LAST_UPDATED) > LIST_CACHE_REFRESH_INTERVAL:
        log.info(f"Cache check for '{symbol}' triggered list update.")
        # Call the update function - THIS IS WHERE THE NameError occurred previously
        # Ensure the function definition for _update_coin_list_cache exists above this point.
        _update_coin_list_cache() # Update synchronously if cache is empty/stale

    # Re-acquire lock to safely read the potentially updated cache
    with _CACHE_LOCK:
        return _COIN_LIST_CACHE.get(symbol.upper())


# --- Main Fetch Function (Uses Caching) ---

def fetch_coingecko_metrics(symbol):
    """
    Fetches various metrics for a given symbol from CoinGecko using its API.
    !! Uses a time-based cache for individual coin details to reduce API calls !!

    Args:
        symbol (str): The coin symbol (e.g., 'BTC', 'ETH').

    Returns:
        dict: A dictionary containing raw metrics fetched from CoinGecko, prefixed
              with 'cg_'. Returns an empty dict if the symbol is not found
              or if the API request fails.
    """
    coin_id = _get_slug_for_symbol(symbol) # This call ensures list cache is updated if needed
    if not coin_id:
        # Warning already logged by _get_slug_for_symbol if lookup failed
        return {}

    now = time.time()

    # --- Check Detail Cache ---
    with _CACHE_LOCK:
        cached_entry = _COIN_DETAIL_CACHE.get(coin_id)
        if cached_entry:
            cache_time, cached_data = cached_entry
            if (now - cache_time) < COIN_DETAIL_CACHE_DURATION:
                log.info(f"[CoinGecko Proxy] Cache HIT for {symbol} (slug: {coin_id})")
                return cached_data # Return cached data

    # --- Cache Miss or Stale: Fetch from API ---
    log.info(f"[CoinGecko Proxy] Cache MISS/STALE for {symbol}. Fetching metrics (using slug: {coin_id})")
    url = f"{COINGECKO_API_BASE}/coins/{coin_id}?localization=false&tickers=false&market_data=false&community_data=true&developer_data=true&sparkline=false"

    try:
        # Apply delay *before* making the potentially rate-limited call
        log.debug(f"Applying {COINGECKO_DELAY}s delay before calling CoinGecko API for {symbol}")
        time.sleep(COINGECKO_DELAY)

        response = requests.get(url, timeout=15)
        response.raise_for_status() # Raises HTTPError for 4xx/5xx responses
        data = response.json()

        # Extract relevant metrics, handling potential missing keys safely
        metrics = {'cg_slug': coin_id} # Include the slug used
        metrics['cg_sentiment_votes_up_percentage'] = data.get('sentiment_votes_up_percentage')
        metrics['cg_community_score'] = data.get('community_score')
        metrics['cg_developer_score'] = data.get('developer_score')
        metrics['cg_public_interest_score'] = data.get('public_interest_score')

        community = data.get('community_data', {}) # Default to empty dict if key missing
        metrics['cg_twitter_followers'] = community.get('twitter_followers')
        metrics['cg_reddit_subscribers'] = community.get('reddit_subscribers')

        interest = data.get('public_interest_stats', {}) # Default to empty dict
        metrics['cg_alexa_rank'] = interest.get('alexa_rank')

        # Filter out None values before caching? Optional.
        # metrics = {k: v for k, v in metrics.items() if v is not None}

        log.info(f"[CoinGecko Proxy] Successfully fetched metrics for {symbol}")

        # --- Update Detail Cache ---
        with _CACHE_LOCK:
             _COIN_DETAIL_CACHE[coin_id] = (now, metrics) # Store timestamp and data

        return metrics

    except requests.exceptions.HTTPError as e:
        # Handle specific HTTP errors like 429 Rate Limit
        if e.response is not None and e.response.status_code == 429:
             log.error(f"[CoinGecko Proxy] RATE LIMITED (429) for {symbol} (slug: {coin_id}). Increase COINGECKO_DELAY or reduce call frequency. Error: {e}")
             # Consider adding a longer dynamic delay or circuit breaker here
        elif e.response is not None and e.response.status_code == 404:
             log.warning(f"[CoinGecko Proxy] Coin not found (404) for slug: {coin_id} (Symbol: {symbol}). Maybe slug list is slightly stale? Error: {e}")
        else:
             log.error(f"[CoinGecko Proxy] HTTP error for {symbol} (slug: {coin_id}): {e}")
        return {} # Return empty dict on handled HTTP errors
    except requests.exceptions.RequestException as e:
        # Handle other network/request related errors
        log.error(f"[CoinGecko Proxy] Request error for {symbol} (slug: {coin_id}): {e}")
        return {}
    except json.JSONDecodeError as e:
        log.error(f"[CoinGecko Proxy] JSON decode error for {symbol} (slug: {coin_id}): {e}. Response: {response.text[:200]}")
        return {}
    except Exception as e:
        # Catch any other unexpected errors during processing
        log.error(f"[CoinGecko Proxy] Unexpected error fetching metrics for {symbol} (slug: {coin_id}): {e}", exc_info=True)
        return {}

# --- Initial Cache Population ---
# Populate the LIST cache when the module is first loaded.
# It's important this runs before the first call to fetch_coingecko_metrics.
log.info("Initializing CoinGecko Proxy: Performing initial coin list cache population...")
_update_coin_list_cache(force_update=True)
log.info("Initial coin list cache population attempt complete.")


# --- Example Usage (for testing directly) ---
if __name__ == "__main__":
    # Setup basic logging for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    log.info("Testing CoinGecko Proxy Module...")

    test_symbols = ["BTC", "ETH", "SOL", "NONEXISTENT", "HOT", "ADA", "INSP"] # Added INSP for testing
    for sym in test_symbols:
        print("-" * 20)
        metrics = fetch_coingecko_metrics(sym)
        if metrics:
            print(f"Metrics for {sym}:")
            # Pretty print the dictionary
            import pprint
            pprint.pprint(metrics)
        else:
            print(f"Could not fetch metrics for {sym} (Check logs for warnings/errors)")
        # Add a small delay even during testing if hitting API
        # time.sleep(1)

    # Test cache retrieval
    print("\n" + "-" * 20)
    print("Testing cache retrieval for BTC (should be fast)...")
    start_time = time.time()
    metrics_btc_cache = fetch_coingecko_metrics("BTC")
    end_time = time.time()
    print(f"Cache fetch took: {end_time - start_time:.4f} seconds")
    if metrics_btc_cache:
         print("BTC Data from cache retrieved.")
    else:
         print("Failed to get BTC data from cache.")
