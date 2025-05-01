import os
import requests
import logging
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
from collections import Counter
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Import Custom Modules ---
# Assuming modules are in a 'modules' subdirectory
try:
    from modules.bybit_api import fetch_market_data, fetch_orderbook, fetch_candles
    from modules.coingecko_api import fetch_coingecko_market_data, fetch_coingecko_categories
    from modules.cryptopanic_api import fetch_cryptopanic_news
    # from modules.santiment_api import fetch_social_metrics # OLD IMPORT - REMOVE/COMMENT OUT
    from modules.coingecko_proxy import fetch_coingecko_metrics # NEW IMPORT
    from modules.momentum_analysis import calculate_rsi, detect_volume_divergence, calculate_momentum_health
    from modules.breakout_scoring import calculate_breakout_score
    from modules.buy_timing_logic import get_buy_window
    import numpy as np # Make sure numpy is imported if used in EMA calc
except ImportError as e:
    logging.error(f"Error importing modules. Make sure they are in a 'modules' directory: {e}")
    exit(1)


app = Flask(__name__)
CORS(app)

# Global data stores (consider thread safety if scaling significantly)
market_data = {} # Raw Bybit data
sentiment_data = {} # Enriched data
basic_coin_data = {} # NEW: Store basic info immediately after startup
last_full_update_time = None
last_basic_update_time = None


def determine_volatility_zone(volatility):
    """Classifies volatility percentage into zones and suggests a strategy."""
    if volatility <= 3:
        return "Very Low Volatility", "Micro Scalping Strategy"
    elif volatility <= 7:
        return "Low Volatility", "Short-Term Tight Strategy"
    elif volatility <= 12:
        return "Medium Volatility", "Balanced Normal Strategy"
    elif volatility <= 18:
        return "High Volatility", "Flexible Swing Strategy"
    else:
        return "Very High Volatility", "Big Swing Survival Strategy"


def estimate_time_to_tp(score, volatility_zone):
    """Estimates time to reach Take Profit based on score and volatility."""
    if score >= 7 and 'Low' in volatility_zone:
        return "1–3 hours"
    elif score >= 5:
        return "4–6 hours"
    elif score >= 3:
        return "6–12 hours"
    else:
        return "Uncertain"


def analyze_timeframes(symbol, last_price):
    """
    Analyzes 15m, 1h, 4h timeframes for EMA20 trend confirmation.
    Returns bullish confirmation status and detailed timeframe statuses.
    """
    def calculate_ema(values, period=20):
        if not values or len(values) < period:
            return None
        try:
            k = 2 / (period + 1)
            ema_values = np.array(values) # Use numpy for potential speedup if available
            ema = np.mean(ema_values[:period]) # Simple average for first value
            for price in ema_values[period:]:
                 ema = price * k + ema * (1 - k)
            return ema
        except Exception as e:
            logging.warning(f"[{symbol}] Error calculating EMA: {e}")
            return None

    results = {}
    # Map standard interval names to Bybit API interval keys
    timeframes = {"15m": "15", "1h": "60", "4h": "240"}
    bullish_confirm = True

    for name, interval_key in timeframes.items():
        # Note: Fetching candles again here. Could be optimized by passing fetched data.
        candle_data = fetch_candles(symbol + "USDT", interval_key) # Ensure symbol has USDT
        if not candle_data or not candle_data.get('result', {}).get('list'):
             logging.warning(f"[{symbol}] No {name} candle data found.")
             closes = []
        else:
            # Bybit V5 Kline format: [timestamp, open, high, low, close, volume, turnover]
            closes = [float(c[4]) for c in candle_data['result']['list'] if len(c) > 4]

        if not closes:
            results[name] = {"price": last_price, "ema20": None, "trend": "unknown"}
            bullish_confirm = False
            continue

        ema20 = calculate_ema(closes)
        trend = "unknown"
        if ema20 is not None and last_price is not None:
             trend = "bullish" if last_price > ema20 else "bearish"
        else:
            bullish_confirm = False # Cannot confirm trend if EMA is missing

        results[name] = {
            "price": round(last_price, 4) if last_price is not None else None,
            "ema20": round(ema20, 4) if ema20 is not None else None,
            "trend": trend
        }

        if trend != "bullish":
            bullish_confirm = False

    return bullish_confirm, results


def fetch_fear_greed_index():
    """Fetches Fear & Greed Index from alternative.me."""
    try:
        response = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and 'data' in data and len(data['data']) > 0:
            d = data['data'][0]
            return int(d['value']), d['value_classification']
        else:
            logging.warning("Fear & Greed Index data is empty or malformed.")
            return 50, "Neutral" # Default value
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching Fear & Greed Index: {e}")
        return 50, "Neutral" # Default value on error
    except (ValueError, KeyError) as e:
        logging.error(f"Error parsing Fear & Greed Index data: {e}")
        return 50, "Neutral" # Default value on error


def fetch_reddit_mentions(symbols):
    """
    Fetches new posts from r/CryptoCurrency and counts symbol mentions in titles.
    Note: Very basic, unreliable, and fragile method. Consider PRAW for robustness.
    """
    mentions = Counter()
    try:
        # Using a common user agent to avoid potential blocks
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        response = requests.get("https://www.reddit.com/r/CryptoCurrency/new.json?limit=50", headers=headers, timeout=15) # Increased limit slightly
        response.raise_for_status()
        posts_data = response.json()
        all_titles = " ".join([
            p['data']['title'] for p in posts_data.get('data', {}).get('children', []) if 'data' in p and 'title' in p['data']
        ]).lower()

        for symbol in symbols:
            # Basic count, might catch substrings (e.g., 'ape' in 'apenft')
            # Consider word boundaries for more accuracy: r'\b' + symbol.lower() + r'\b'
            mentions[symbol] = all_titles.count(symbol.lower())
        logging.info(f"Reddit mentions checked. Found mentions for: { {k: v for k, v in mentions.items() if v > 0} }")

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching Reddit data: {e}")
    except Exception as e:
        logging.error(f"Error processing Reddit data: {e}")
    return mentions

# --- NEW: Function for Basic Data Fetch ---
def fetch_and_process_basic_data():
    """Fetches essential Bybit data and calculates basic metrics only."""
    global market_data, basic_coin_data, last_basic_update_time
    logging.info("🚀 Starting BASIC data fetch cycle...")
    try:
        bybit_market_data = fetch_market_data()
        if not bybit_market_data:
            logging.error("Failed to fetch Bybit market data during basic fetch.")
            return
        market_data = bybit_market_data # Update global raw market data

        temp_basic_data = {}
        potential_coins = [ # Same logic to find potential coins
            item["symbol"].replace("USDT", "")
            for item in market_data.values()
            if item.get("symbol", "").endswith("USDT")
               and float(item.get("lastPrice", 0)) > 0
               and item.get("symbol")
        ]

        for coin_symbol in potential_coins:
            symbol_usdt = coin_symbol + "USDT"
            market = market_data.get(symbol_usdt)
            if not market: continue

            try:
                # --- Extract only essential Bybit data ---
                last_price_str = market.get("lastPrice")
                high_24h_str = market.get("highPrice24h")
                low_24h_str = market.get("lowPrice24h")
                volume_24h_str = market.get("volume24h") # Useful context

                if not all([last_price_str, high_24h_str, low_24h_str]): continue
                last_price = float(last_price_str)
                high_24h = float(high_24h_str)
                low_24h = float(low_24h_str)
                if last_price <= 0: continue

                volatility = ((high_24h - low_24h) / last_price * 100) if last_price > 0 else 0
                zone, strategy = determine_volatility_zone(volatility)

                # --- Optionally fetch order book for spread (can be skipped if too slow) ---
                spread_percent = None
                orderbook_data = fetch_orderbook(symbol_usdt) # Keep this? Or skip for speed?
                if orderbook_data and orderbook_data.get('result'):
                     bids_raw = orderbook_data['result'].get('b', [])
                     asks_raw = orderbook_data['result'].get('a', [])
                     if bids_raw and asks_raw:
                         best_bid = float(bids_raw[0][0])
                         best_ask = float(asks_raw[0][0])
                         if best_ask > best_bid > 0:
                              spread_percent = (best_ask - best_bid) / last_price * 100

                # Store basic info
                temp_basic_data[coin_symbol] = {
                    "symbol": coin_symbol,
                    "symbol_usdt": symbol_usdt,
                    "current_price": round(last_price, 4),
                    "volume_24h": float(volume_24h_str) if volume_24h_str else None,
                    "volatility_percent": round(volatility, 2),
                    "volatility_zone": zone,
                    "strategy_suggestion": strategy,
                    "bid_ask_spread_percent": round(spread_percent, 4) if spread_percent is not None else None,
                    "timestamp": datetime.now().isoformat() # Timestamp of this basic fetch
                }
            except Exception as e:
                 logging.error(f"[{coin_symbol}] Error during BASIC processing: {e}", exc_info=True)

        basic_coin_data = temp_basic_data # Update global basic data store
        last_basic_update_time = datetime.now()
        logging.info(f"✅ Basic data fetch cycle finished. Processed {len(basic_coin_data)} coins.")

    except Exception as e:
        logging.error(f"Critical error during fetch_and_process_basic_data: {e}", exc_info=True)


def update_data():
    """Main function to fetch all data, enrich with CG/Reddit, analyze coins, and update global state."""
    global market_data, sentiment_data, last_full_update_time, basic_coin_data # Add basic_coin_data
    logging.info("🚀 Starting FULL data update cycle...")

    try:
        # --- Fetch Global/Market Data ---
        # We might already have recent Bybit data from basic fetch, but fetching again ensures freshness for the full cycle
        bybit_market_data = fetch_market_data()
        if not bybit_market_data:
            logging.error("Failed to fetch Bybit market data. Aborting full update cycle.")
            return
        market_data = bybit_market_data # Update global market data

        potential_coins = [ # Recalculate potential coins based on fresh market data
            item["symbol"].replace("USDT", "")
            for item in market_data.values()
            if item.get("symbol", "").endswith("USDT")
               and float(item.get("lastPrice", 0)) > 0
               and item.get("symbol")
        ]
        logging.info(f"Found {len(potential_coins)} potential USDT pairs for full analysis.")

        # Fetch context data (only needed for full analysis)
        fear_greed_score, fear_greed_class = fetch_fear_greed_index()
        reddit_mentions = fetch_reddit_mentions(potential_coins) # Moved here
        coingecko_markets = fetch_coingecko_market_data()
        cryptopanic_news = fetch_cryptopanic_news()

        sector_lookup = { # Rebuild lookup based on potentially new market data
            item.get('symbol', '').upper(): next((cat for cat in item.get('categories', []) if cat), 'Unknown')
            for item in coingecko_markets if item.get('symbol')
        }

        # --- Process Each Coin ---
        processed_coins_data = []
        skipped_coins = Counter()

        # Use the latest basic_coin_data as a starting point or fallback
        current_basic_data = basic_coin_data.copy()

        for coin_symbol in potential_coins:
            symbol_usdt = coin_symbol + "USDT"
            market = market_data.get(symbol_usdt)
            basic_info = current_basic_data.get(coin_symbol) # Get basic info fetched earlier

            if not market:
                logging.warning(f"[{coin_symbol}] Fresh market data not found in fetched list, skipping full analysis.")
                skipped_coins['market_data_missing'] += 1
                continue

            try:
                # Extract fresh price/vol data
                last_price_str = market.get("lastPrice")
                high_24h_str = market.get("highPrice24h")
                low_24h_str = market.get("lowPrice24h")
                # ... (validation) ...
                last_price = float(last_price_str)
                # ...

                # --- Use basic info if available, recalculate if needed ---
                volatility = ((float(high_24h_str) - float(low_24h_str)) / last_price * 100) if last_price > 0 and high_24h_str and low_24h_str else (basic_info.get('volatility_percent') if basic_info else 0)
                zone, strategy = determine_volatility_zone(volatility)
                spread_percent = basic_info.get('bid_ask_spread_percent') if basic_info else None # Reuse spread if available, or fetch again if needed/critical


                # --- <<< EARLY FILTERS (Can use basic info or fresh data) >>> ---
                SPREAD_THRESHOLD = 1.5
                ALLOWED_VOLATILITY_ZONES = ["Very Low Volatility", "Low Volatility", "Medium Volatility"]
                if spread_percent is None: # Optionally fetch orderbook here if essential and missing
                     orderbook_data = fetch_orderbook(symbol_usdt)
                     # orderbook_data = fetch_orderbook(symbol_usdt) ... calculate spread ...
                     pass # For now, skip if spread wasn't fetched in basic

                if spread_percent is not None and spread_percent > SPREAD_THRESHOLD:
                    # logging.info(f"[{coin_symbol}] Skipping full analysis due to high/missing spread: {spread_percent}")
                    # skipped_coins['high_spread_full'] += 1
                    continue # Skip silently in full run if basic info already showed high spread

                if zone not in ALLOWED_VOLATILITY_ZONES:
                     # logging.info(f"[{coin_symbol}] Skipping full analysis due to volatility zone: {zone}")
                     # skipped_coins['wrong_volatility_full'] += 1
                     continue # Skip silently

                # --- Passed Filters - Proceed with Intensive Analysis ---
                logging.debug(f"[{coin_symbol}] Passed filters. Performing full analysis...")

                # --- Timeframe, Candles, Indicators (as before) ---
                mtf_confirm, tf_status = analyze_timeframes(coin_symbol, last_price)
                # ... fetch 1h candles, calc closes/volumes ...
                rsi = calculate_rsi(closes) if closes else None
                # ... calc volume_divergence, momentum_health ...
                volume_divergence = detect_volume_divergence(volumes) if volumes else None # False if not enough data
                momentum_health = calculate_momentum_health(rsi, volume_divergence)



                # --- <<< CALL COINGECKO ONLY HERE >>> ---
                logging.info(f"[{coin_symbol}] Fetching CoinGecko metrics (cache check)...")
                cg_metrics = fetch_coingecko_metrics(coin_symbol)
                cg_derived_whale_alert = cg_metrics.get('cg_derived_whale_alert', False)
                cg_derived_social_spike = cg_metrics.get('cg_derived_social_dominance_spike', False)
                cg_derived_address_spike = cg_metrics.get('cg_derived_active_address_spike', False)

# Calls CG API (uses cache)

                # Extract CG metrics (as before)
                # ... cg_sentiment_percentage = cg_metrics.get(...) ...

                # --- Use Reddit mentions (fetched once per cycle) ---
                mentions = reddit_mentions.get(coin_symbol, 0)

                # --- News sentiment (as before) ---
                # ... coin_news_sentiment = ...
                coin_news_sentiment = "neutral"
                if cryptopanic_news:
                    positive_mentions = sum(
                        1 for n in cryptopanic_news
                        if coin_symbol.lower() in n.get('title', '').lower()
                           and n.get("votes", {}).get("positive", 0) > n.get("votes", {}).get("negative", 0) + n.get("votes", {}).get("important", 0) # Example: More positive than neg+important
                    )
                    negative_mentions = sum(
                         1 for n in cryptopanic_news
                        if coin_symbol.lower() in n.get('title', '').lower()
                           and n.get("votes", {}).get("negative", 0) > n.get("votes", {}).get("positive", 0)
                    )
                    if positive_mentions > negative_mentions:
                        coin_news_sentiment = "positive"
                    elif negative_mentions > positive_mentions:
                         coin_news_sentiment = "negative"


                # --- Scoring (as before, using all available metrics) ---
                breakout_score = calculate_breakout_score(
                    rsi=rsi,
                    volume_rising=not volume_divergence if volume_divergence is not None else False, # Need volume trend, not just divergence
                    cg_derived_whale_alert=cg_derived_whale_alert, # Use renamed key
                    news_sentiment=coin_news_sentiment,
                    spread_percent=spread_percent,
                    btc_inflow_spike=btc_inflow_spike,
                    orderbook_thin=orderbook_thin,
                    momentum_health=momentum_health,
                )
                # logging.info(...) # Maybe log less verbosely here

            except Exception as e:
                logging.error(f"[{coin_symbol}] Unexpected error during FULL processing: {e}", exc_info=True)
                skipped_coins['unexpected_error_full'] += 1

        # --- Update Global State ---
        sentiment_data.clear() # Clear previous full data
        sentiment_data["timestamp"] = datetime.now().isoformat()
        sentiment_data["fear_greed"] = {"score": fear_greed_score, "classification": fear_greed_class}
        sentiment_data["processed_coins"] = processed_coins_data # Store the list of fully processed coins
        sentiment_data["update_summary"] = { # Add summary
             "total_potential_coins": len(potential_coins),
             "successfully_processed_full": len(processed_coins_data),
             "skipped_counts": dict(skipped_coins)
        }
        last_full_update_time = datetime.now()
        logging.info(f"✅ FULL data update cycle finished. Processed {len(processed_coins_data)} coins fully. Skipped: {dict(skipped_coins)}")

    except Exception as e:
        logging.error(f"Critical error during full update_data execution: {e}", exc_info=True)


# --- Adjust Scheduler ---
scheduler = BackgroundScheduler(daemon=True)
# Schedule the FULL update less frequently
scheduler.add_job(update_data, 'interval', minutes=60, next_run_time=datetime.now() + timedelta(minutes=1)) # Run 1 min after start
# Optionally schedule basic data refresh more often if needed, but maybe not necessary
# scheduler.add_job(fetch_and_process_basic_data, 'interval', minutes=15)
scheduler.start()

# --- Flask Routes ---
@app.route("/sentiment")
def get_sentiment():
    """Returns the latest aggregated sentiment and coin analysis data (fully processed)."""
    if not sentiment_data or not sentiment_data.get("processed_coins"): # Check for fully processed coins
         # Optionally merge basic data here if needed for partial response
         return jsonify({"warning": "Full sentiment data is not available yet. Initializing or first scheduled run pending.",
                         "timestamp": last_full_update_time.isoformat() if last_full_update_time else None}), 404 # Use 404 or 503
    return jsonify(sentiment_data)
    
@app.route("/scalp-sentiment")
def get_scalp_sentiment():
    """Filters fully processed sentiment data for potential scalp opportunities."""
    if not sentiment_data or not sentiment_data.get("processed_coins"):
         return jsonify({"error": "Full analysis data is not available yet. Please try again later."}), 503

    filtered_coins = []
    original_coins = sentiment_data.get("processed_coins", [])

    for coin in original_coins:
        try:
            spread = coin.get("bid_ask_spread_percent")
            # Filter 1: Low Spread (adjust threshold as needed)
            if spread is None or spread > 0.3: # Strict spread limit for scalping
                continue

            # Filter 2: Low Volatility Zone
            volatility_zone = coin.get("volatility_zone", "")
            # Use the correct variable name here
            if not volatility_zone.startswith("Very Low") and not volatility_zone.startswith("Low"):
                continue

            # Filter 3: Multi-Timeframe Confirmation
            if not coin.get("multi_timeframe_confirmation"):
                continue

            # Filter 4: High Enough Breakout Score
            if coin.get("breakout_score", 0) < 6: # Minimum score threshold
                continue

            # Filter 5: RSI in optimal range (adjust as needed)
            rsi = coin.get("rsi_1h")
            if rsi is None or not (45 <= rsi <= 65): # RSI range filter
                continue

            # Filter 6: Short Time Estimate to TP (if available)
            time_estimate = coin.get("time_estimate_to_tp", "")
            if not time_estimate.startswith("1") and not time_estimate.startswith("2"): # Only 1-3h or 2-Xh estimates
                 continue

            # Filter 7: Positive Momentum Health
            if coin.get("momentum_health") != "strong":
                continue

            filtered_coins.append(coin)

        except Exception as e:
            logging.warning(f"Error filtering coin {coin.get('symbol', 'N/A')} for scalp: {e}")
            continue # Skip coin if error occurs during filtering

    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "strategy": "Scalping Filter (Strict Criteria: Low Spread/Vol, MTF Conf, Score>=6, RSI 45-65, Quick TP Est, Strong Momentum)",
        "qualified_coins": filtered_coins,
        "total_checked": len(original_coins),
        "total_qualified": len(filtered_coins)
    })

@app.route("/market")
def get_market():
    """Returns the raw market data fetched from Bybit."""
    if not market_data:
         return jsonify({"error": "Market data not available yet."}), 503
    # Return a copy to prevent modification? For now, return directly.
    return jsonify({"timestamp": last_update_time.isoformat() if last_update_time else None, "data": market_data})

@app.route("/health")
def get_health():
    """Provides a basic health check of the API."""
    status = "ok"
    message = "API is running."
    if not sentiment_data:
        status = "initializing"
        message = "API is running, but initial data load may not be complete."
    elif last_update_time and (datetime.now() - last_update_time).total_seconds() > (45 * 60): # e.g., if last update was > 45 mins ago
         status = "stale_data"
         message = f"API is running, but data seems stale. Last update: {last_update_time.isoformat()}"

    return jsonify({"status": status, "message": message, "last_update": last_update_time.isoformat() if last_update_time else None})

# --- Static Files ---
@app.route("/legal")
def legal():
    """Serves the legal information page."""
    return send_from_directory("static", "legal.html")

@app.route("/openapi.yaml")
def serve_openapi():
    """Serves the OpenAPI specification file."""
    return send_from_directory("static", "openapi.yaml")

@app.route("/")
def index():
    """Basic index route indicating the API is running."""
    return "✅ PersonalTradeAssist API is running. Use /sentiment, /scalp-sentiment, /market, or /health."

# --- Main Execution ---
if __name__ == "__main__":
    logging.info("Performing initial BASIC data fetch before starting server...")
    try:
        fetch_and_process_basic_data() # <<< CALL THE BASIC FUNCTION AT STARTUP
        logging.info("Initial BASIC data fetch complete.")
    except Exception as e:
        logging.critical(f"❗ Failed during initial basic data fetch: {e}", exc_info=True)
        # Decide if you want to exit

    # Run the Flask app
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"🚀 Starting Flask server on host 0.0.0.0 port {port}")
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
         logging.critical(f"❗ Flask server failed to start: {e}", exc_info=True)
