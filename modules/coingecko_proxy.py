import requests
import time
import logging
import json
import os
from threading import Lock

# --- Configuration ---
COINGECKO_API_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_DELAY = 6.0 # Keep conservative delay
CACHE_REFRESH_INTERVAL = 6 * 60 * 60 # 6 hours for coin LIST cache
# --- NEW: Cache for individual coin details ---
COIN_DETAIL_CACHE_DURATION = 2 * 60 * 60 # Cache individual coin data for 2 hours

# --- Global Caches ---
_COIN_LIST_CACHE = {} # SYMBOL.UPPER() -> coin_id (slug)
_COIN_DETAIL_CACHE = {} # coin_id -> (timestamp, data_dict)
_CACHE_LOCK = Lock()
_LIST_CACHE_LAST_UPDATED = 0

# --- Logging ---
log = logging.getLogger(__name__)

# ... (_fetch_all_coins_list, _update_coin_list_cache, _get_slug_for_symbol remain the same) ...
# Make sure _get_slug_for_symbol uses _LIST_CACHE_LAST_UPDATED

# Update _get_slug_for_symbol slightly to use correct timestamp variable
def _get_slug_for_symbol(symbol):
    """Looks up the CoinGecko slug (id) for a given symbol using the cache."""
    global _LIST_CACHE_LAST_UPDATED # Ensure global is referenced
    now = time.time()
    # Ensure cache is populated on first call or if stale
    # Use _LIST_CACHE_LAST_UPDATED for the list cache timestamp
    if not _COIN_LIST_CACHE or (now - _LIST_CACHE_LAST_UPDATED) > CACHE_REFRESH_INTERVAL:
     _update_coin_list_cache() # Update synchronously if cache is empty/stale

    with _CACHE_LOCK:
        return _COIN_LIST_CACHE.get(symbol.upper())

# --- Main Fetch Function (Updated with Caching) ---
def fetch_coingecko_metrics(symbol):
    """
    Fetches various metrics for a given symbol from CoinGecko using its API.
    !! Uses a time-based cache to reduce API calls !!
    """
    coin_id = _get_slug_for_symbol(symbol)
    if not coin_id:
        log.warning(f"[CoinGecko Proxy] No slug found in cache for symbol '{symbol}'. Skipping metrics.")
        return {}

    now = time.time()

    # --- Check Cache ---
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
        # Apply delay *before* the actual call for safety
        time.sleep(COINGECKO_DELAY)
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Extract relevant metrics
        metrics = {'cg_slug': coin_id}
        metrics['cg_sentiment_votes_up_percentage'] = data.get('sentiment_votes_up_percentage')
        metrics['cg_community_score'] = data.get('community_score')
        metrics['cg_developer_score'] = data.get('developer_score')
        metrics['cg_public_interest_score'] = data.get('public_interest_score')
        community = data.get('community_data', {})
        metrics['cg_twitter_followers'] = community.get('twitter_followers')
        metrics['cg_reddit_subscribers'] = community.get('reddit_subscribers')
        interest = data.get('public_interest_stats', {})
        metrics['cg_alexa_rank'] = interest.get('alexa_rank')

        log.info(f"[CoinGecko Proxy] Successfully fetched metrics for {symbol}")

        # --- Update Cache ---
        with _CACHE_LOCK:
             _COIN_DETAIL_CACHE[coin_id] = (now, metrics) # Store timestamp and data

        return metrics

    # ... (rest of error handling remains the same) ...
    except requests.exceptions.RequestException as e:
        # Handle 429 specifically - maybe back off longer?
        if e.response is not None and e.response.status_code == 429:
             log.error(f"[CoinGecko Proxy] RATE LIMITED (429) for {symbol} (slug: {coin_id}). Check COINGECKO_DELAY. Error: {e}")
             # Consider adding a longer dynamic delay here if rate limited
        else:
             log.error(f"[CoinGecko Proxy] Request error for {symbol} (slug: {coin_id}): {e}")
        return {}
    # ... (other except blocks) ...

# ... (Initial cache population remains the same) ...
