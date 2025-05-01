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
market_data = {}
sentiment_data = {}
last_update_time = None

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


def update_data():
    """Main function to fetch all data, analyze coins, and update global state."""
    global market_data, sentiment_data, last_update_time
    logging.info("🚀 Starting data update cycle...")

    try:
        # --- Fetch Global/Market Data ---
        bybit_market_data = fetch_market_data()
        if not bybit_market_data:
            logging.error("Failed to fetch Bybit market data. Aborting update cycle.")
            return
        market_data = bybit_market_data # Update global market data

        # Determine potential coins to analyze (USDT pairs with some price)
        # Filter criteria can be adjusted (e.g., add volume minimum)
        potential_coins = [
            item["symbol"].replace("USDT", "")
            for item in market_data.values() # Iterate through values directly
            if item.get("symbol", "").endswith("USDT")
               and float(item.get("lastPrice", 0)) > 0 # Check for non-zero price
               and item.get("symbol") # Ensure symbol exists
        ]
        logging.info(f"Found {len(potential_coins)} potential USDT pairs from Bybit.")

        # Fetch context data (less frequently changing data)
        fear_greed_score, fear_greed_class = fetch_fear_greed_index()
        reddit_mentions = fetch_reddit_mentions(potential_coins)
        coingecko_markets = fetch_coingecko_market_data() # Used for sector lookup
        # coingecko_categories = fetch_coingecko_categories() # Not currently used, commented out
        cryptopanic_news = fetch_cryptopanic_news()

        # Build sector lookup (can be cached if CoinGecko data is fetched less often)
        sector_lookup = {
            item.get('symbol', '').upper(): next((cat for cat in item.get('categories', []) if cat), 'Unknown') # Takes first category if available
            for item in coingecko_markets if item.get('symbol')
        }
        logging.info(f"Built sector lookup for {len(sector_lookup)} coins from CoinGecko.")

        # --- Process Each Coin ---
        processed_coins_data = []
        skipped_coins = Counter()

        for coin_symbol in potential_coins:
            symbol_usdt = coin_symbol + "USDT"
            market = market_data.get(symbol_usdt)

            if not market:
                logging.warning(f"[{coin_symbol}] Market data not found in fetched list, skipping.")
                skipped_coins['market_data_missing'] += 1
                continue

            try:
                last_price_str = market.get("lastPrice")
                high_24h_str = market.get("highPrice24h")
                low_24h_str = market.get("lowPrice24h")
                volume_24h_str = market.get("volume24h")

                # --- Basic Data Validation and Conversion ---
                if not all([last_price_str, high_24h_str, low_24h_str, volume_24h_str]):
                    logging.warning(f"[{coin_symbol}] Missing essential price/volume data, skipping.")
                    skipped_coins['missing_price_data'] += 1
                    continue

                last_price = float(last_price_str)
                high_24h = float(high_24h_str)
                low_24h = float(low_24h_str)
                # volume_24h = float(volume_24h_str) # Not used directly below, but available

                if last_price <= 0: # Basic sanity check
                    logging.warning(f"[{coin_symbol}] Invalid last price ({last_price}), skipping.")
                    skipped_coins['invalid_price'] += 1
                    continue

                # --- Volatility Analysis ---
                volatility = ((high_24h - low_24h) / last_price * 100) if last_price > 0 else 0
                zone, strategy = determine_volatility_zone(volatility)

                # --- Order Book and Spread ---
                orderbook_data = fetch_orderbook(symbol_usdt)
                bids = asks = None
                best_bid = best_ask = spread_percent = None
                orderbook_thin = True # Assume thin until proven otherwise

                if orderbook_data and orderbook_data.get('result'):
                    # Bybit V5 format: result['b'] = bids [price, size], result['a'] = asks [price, size]
                    bids_raw = orderbook_data['result'].get('b', [])
                    asks_raw = orderbook_data['result'].get('a', [])

                    if bids_raw and asks_raw:
                        best_bid = float(bids_raw[0][0])
                        best_ask = float(asks_raw[0][0])
                        bids = [{"price": float(p[0]), "size": float(p[1])} for p in bids_raw[:5]] # Top 5
                        asks = [{"price": float(p[0]), "size": float(p[1])} for p in asks_raw[:5]] # Top 5

                        if best_ask > best_bid > 0:
                             spread_percent = (best_ask - best_bid) / last_price * 100
                             # Define 'thin' based on spread (adjust threshold as needed)
                             orderbook_thin = spread_percent > 1.5 # Example threshold
                        else:
                             logging.warning(f"[{coin_symbol}] Invalid best bid/ask ({best_bid}/{best_ask}), cannot calculate spread.")
                             skipped_coins['invalid_orderbook'] += 1
                    else:
                         logging.warning(f"[{coin_symbol}] Empty bids or asks in orderbook data.")
                         skipped_coins['empty_orderbook'] += 1
                else:
                     logging.warning(f"[{coin_symbol}] Failed to fetch or parse orderbook.")
                     skipped_coins['fetch_orderbook_failed'] += 1


                # --- Timeframe Analysis ---
                mtf_confirm, tf_status = analyze_timeframes(coin_symbol, last_price) # Pass base symbol

                # --- Candle Data for Indicators ---
                # Fetch 1h candles (again - potential optimization: reuse from analyze_timeframes if structure allows)
                logging.warning(f"[{coin_symbol}] Fetching 1h candles again for RSI/Volume. Consider optimization.")
                candles_1h_data = fetch_candles(symbol_usdt, "60")
                closes = []
                volumes = []
                if candles_1h_data and candles_1h_data.get('result', {}).get('list'):
                    candle_list = candles_1h_data['result']['list']
                    closes = [float(c[4]) for c in candle_list if len(c) > 4]
                    volumes = [float(c[5]) for c in candle_list if len(c) > 5]
                else:
                    logging.warning(f"[{coin_symbol}] Could not get 1h candle data for indicators.")
                    # Decide how to handle - skip coin or proceed with missing indicators?
                    # Skipping for now as indicators are crucial
                    skipped_coins['candle_data_missing'] += 1
                    # continue # Optional: skip if candles are essential

                # --- Indicator Calculations ---
                rsi = calculate_rsi(closes) if closes else None
                volume_divergence = detect_volume_divergence(volumes) if volumes else None # False if not enough data
                momentum_health = calculate_momentum_health(rsi, volume_divergence)
                cg_metrics = fetch_coingecko_metrics(coin_symbol)
                cg_sentiment_percentage = cg_metrics.get('cg_sentiment_votes_up_percentage') # Raw sentiment %
                cg_community_score = cg_metrics.get('cg_community_score')
                cg_developer_score = cg_metrics.get('cg_developer_score')
                cg_public_interest_score = cg_metrics.get('cg_public_interest_score')

                # --- Initial Filtering (Example: Apply basic filters early) ---
                if spread_percent is not None and spread_percent > 1.5:
                    logging.info(f"[{coin_symbol}] Skipping due to high spread: {spread_percent:.4f}%")
                    skipped_coins['high_spread'] += 1
                    continue
                # Example: Filter based on volatility zone if desired earlier
                # if zone not in ["Very Low Volatility", "Low Volatility"]:
                #     logging.info(f"[{coin_symbol}] Skipping due to volatility zone: {zone}")
                #     skipped_coins['wrong_volatility'] += 1
                #     continue

                # --- Social & News Metrics ---
                # Note: Uses CoinGecko proxy, NOT real Santiment
                cg_metrics = fetch_coingecko_metrics(coin_symbol)
                cg_sentiment_percentage = cg_metrics.get('cg_sentiment_votes_up_percentage') # Raw sentiment %
                cg_community_score = cg_metrics.get('cg_community_score')
                cg_developer_score = cg_metrics.get('cg_developer_score')
                cg_public_interest_score = cg_metrics.get('cg_public_interest_score')

                # Basic news sentiment from CryptoPanic titles
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


                # Placeholder for BTC inflow - needs a real data source
                btc_inflow_spike = False

                # --- Scoring ---
                breakout_score = calculate_breakout_score(
                    rsi=rsi,
                    volume_rising=not volume_divergence if volume_divergence is not None else False,
                    # cg_derived_whale_alert=cg_derived_whale_alert, # REMOVED OLD ARGUMENT
                    news_sentiment=coin_news_sentiment,
                    spread_percent=spread_percent,
                    btc_inflow_spike=btc_inflow_spike,
                    orderbook_thin=orderbook_thin,
                    momentum_health=momentum_health,
                    # --- ADD NEW ARGUMENTS ---
                    cg_sentiment_percentage=cg_sentiment_percentage,
                    cg_community_score=cg_community_score,
                    cg_developer_score=cg_developer_score,
                    cg_public_interest_score=cg_public_interest_score
                )


                # --- Estimates & Signals ---
                tp_estimate = estimate_time_to_tp(breakout_score, zone)
                mentions = reddit_mentions.get(coin_symbol, 0)
                # Refined Signal Logic (Example)
                signal = "NEUTRAL"
                if breakout_score >= 5 and mtf_confirm and fear_greed_score > 40 and momentum_health == "strong": # Example Threshold Adjustment
                    signal = "BUY"
                elif breakout_score <= 1 or fear_greed_score < 30 or momentum_health == "weak": # Example Threshold Adjustment
                    signal = "SELL/AVOID"
                else:
                    signal = "CAUTION"


                # Simplified scalp levels (adjust percentages as needed)
                scalp_tp = round(last_price * 1.008, 4) # ~0.8% gain
                scalp_sl = round(last_price * 0.992, 4) # ~0.8% risk

                # --- Assemble Coin Data ---
                coin_data = {
                    "symbol": coin_symbol,
                    "symbol_usdt": symbol_usdt,
                    "current_price": round(last_price, 4),
                    # ... other existing fields ...
                    "fear_greed_context": f"{fear_greed_score} ({fear_greed_class})",
                    "signal": signal,
                    "bid_ask_spread_percent": round(spread_percent, 4) if spread_percent is not None else None,
                    "orderbook_snapshot": {
                         "top_5_bids": bids,
                         "top_5_asks": asks,
                         "is_thin": orderbook_thin
                    },
                    "multi_timeframe_confirmation": mtf_confirm,
                    "timeframes_status": tf_status,
                    "sector": sector_lookup.get(coin_symbol.upper(), "Unknown"),
                    "news_sentiment": coin_news_sentiment,

                    # --- REMOVE OLD DERIVED METRICS ---
                    # "cg_derived_social_dominance_spike": cg_derived_social_spike,
                    # "cg_derived_active_address_spike": cg_derived_address_spike,
                    # "cg_derived_whale_alert": cg_derived_whale_alert,

                    # --- ADD NEW RAW COINGECKO METRICS ---
                    "cg_metrics_source": "CoinGecko API Proxy", # Clarify source
                    "cg_slug": cg_metrics.get('cg_slug'),
                    "cg_sentiment_votes_up_percentage": cg_sentiment_percentage,
                    "cg_community_score": cg_community_score,
                    "cg_developer_score": cg_developer_score,
                    "cg_public_interest_score": cg_public_interest_score,
                    # Add others fetched if desired (e.g., 'cg_twitter_followers')

                    "btc_inflow_spike": btc_inflow_spike,
                    "rsi_1h": rsi,
                    "volume_divergence_1h": volume_divergence,
                    "momentum_health": momentum_health,
                    "breakout_score": breakout_score,
                    "time_estimate_to_tp": tp_estimate,
                    "example_scalp_levels": {
                        "entry_approx": round(last_price, 4),
                        "tp": scalp_tp,
                        "sl": slop_loss, # Typo fixed: stop_loss
                    },
                    "buy_window_note": get_buy_window()
                }
                processed_coins_data.append(coin_data)
                spread_str = f"{spread_percent:.4f}%" if spread_percent is not None else "N/A"
                rsi_str = f"{rsi:.2f}" if rsi is not None else "N/A"
                logging.info(f"✅ Processed: {coin_symbol} (Score: {breakout_score}, Signal: {signal}, Spread: {spread_str}, RSI: {rsi_str})")
            except (ValueError, TypeError) as e:
                 logging.error(f"[{coin_symbol}] Error converting data (price/vol/etc.): {e}. Skipping coin.")
                 skipped_coins['data_conversion_error'] += 1
            except Exception as e:
                logging.error(f"[{coin_symbol}] Unexpected error during processing: {e}", exc_info=True) # Log traceback
                skipped_coins['unexpected_error'] += 1


        # --- Update Global State ---
        sentiment_data.clear()
        sentiment_data["timestamp"] = datetime.now().isoformat()
        sentiment_data["fear_greed"] = {"score": fear_greed_score, "classification": fear_greed_class}
        sentiment_data["processed_coins"] = processed_coins_data # Use the list built in the loop
        sentiment_data["update_summary"] = {
            "total_potential_coins": len(potential_coins),
            "successfully_processed": len(processed_coins_data),
            "skipped_counts": dict(skipped_coins)
        }

        last_update_time = datetime.now()
        logging.info(f"✅ Data update cycle finished. Processed {len(processed_coins_data)} coins. Skipped: {dict(skipped_coins)}")

    except requests.exceptions.RequestException as e:
        logging.error(f"Network error during update cycle: {e}")
    except Exception as e:
        logging.error(f"Critical error during update_data execution: {e}", exc_info=True)


# --- Initialize Scheduler ---
scheduler = BackgroundScheduler(daemon=True) # Use daemon thread
# Run every 30 minutes, starting after the first manual run completes
scheduler.add_job(update_data, 'interval', minutes=30, next_run_time=datetime.now())
scheduler.start()

# --- Flask Routes ---
@app.route("/sentiment")
def get_sentiment():
    """Returns the latest aggregated sentiment and coin analysis data."""
    if not sentiment_data:
         return jsonify({"error": "Data is not available yet. Please try again later."}), 503
    return jsonify(sentiment_data)

@app.route("/scalp-sentiment")
def get_scalp_sentiment():
    """Filters sentiment data for potential scalp opportunities based on strict criteria."""
    if not sentiment_data or "processed_coins" not in sentiment_data:
         return jsonify({"error": "Data is not available yet. Please try again later."}), 503

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
    # Perform initial data fetch before starting the web server
    # This makes sure data is available sooner on startup
    logging.info("Performing initial data fetch before starting server...")
    try:
        update_data()
        logging.info("Initial data fetch complete.")
    except Exception as e:
        logging.critical(f"❗ Failed during initial update_data(): {e}", exc_info=True)
        # Decide if you want to exit if the initial fetch fails catastrophically
        # exit(1)

    # Run the Flask app
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"🚀 Starting Flask server on host 0.0.0.0 port {port}")
    # Use waitress or gunicorn in production instead of Flask's development server
    app.run(host="0.0.0.0", port=port)
