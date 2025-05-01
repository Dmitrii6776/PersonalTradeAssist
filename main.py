import os
import requests
import logging
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
# --- FIX: Import timedelta ---
from datetime import datetime, timedelta
from collections import Counter
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Import Custom Modules ---
try:
    from modules.bybit_api import fetch_market_data, fetch_orderbook, fetch_candles
    from modules.coingecko_api import fetch_coingecko_market_data # Keep for category lookup
    from modules.cryptopanic_api import fetch_cryptopanic_news
    from modules.coingecko_proxy import fetch_coingecko_metrics # Use the proxy
    from modules.momentum_analysis import calculate_rsi, detect_volume_divergence, calculate_momentum_health
    from modules.breakout_scoring import calculate_breakout_score
    from modules.buy_timing_logic import get_buy_window
    import numpy as np
except ImportError as e:
    logging.error(f"Error importing modules. Make sure they are in a 'modules' directory: {e}")
    exit(1)


app = Flask(__name__)
CORS(app)

# Global data stores
market_data = {}
sentiment_data = {}
basic_coin_data = {}
last_full_update_time = None
last_basic_update_time = None



def determine_volatility_zone(volatility):
    """Classifies volatility percentage into zones and suggests a strategy."""
    if volatility is None: # Handle None input
        return "Unknown Volatility", "Unknown Strategy"
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
    if score is None or volatility_zone is None: # Handle None input
         return "Uncertain"
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

                # Perform basic validation early
                if not all(v is not None and v != '' for v in [last_price_str, high_24h_str, low_24h_str]):
                    logging.debug(f"[{coin_symbol}] Missing essential price/vol data in basic fetch.")
                    continue
                try:
                    last_price = float(last_price_str)
                    high_24h = float(high_24h_str)
                    low_24h = float(low_24h_str)
                    if last_price <= 0: continue
                except (ValueError, TypeError):
                     logging.warning(f"[{coin_symbol}] Invalid numeric data in basic fetch.")
                     continue


                volatility = ((high_24h - low_24h) / last_price * 100) if last_price > 0 else 0
                zone, strategy = determine_volatility_zone(volatility)

                # --- Optionally fetch order book for spread (can be skipped if too slow) ---
                #spread_percent = None
                #orderbook_data = fetch_orderbook(symbol_usdt)
                #if orderbook_data and orderbook_data.get('result'):
                     #bids_raw = orderbook_data['result'].get('b', [])
                     #asks_raw = orderbook_data['result'].get('a', [])
                     #if bids_raw and asks_raw:
                         #try:
                            # best_bid = float(bids_raw[0][0])
                 #           # best_ask = float(asks_raw[0][0])
                  #           if best_ask > best_bid > 0:
                   #               spread_percent = (best_ask - best_bid) / last_price * 100
                    #     except (ValueError, TypeError, IndexError):
                     #         logging.warning(f"[{coin_symbol}] Error processing order book data in basic fetch.")
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
                 # Catch errors during processing of a single coin
                 logging.error(f"[{coin_symbol}] Error during BASIC processing for this coin: {e}", exc_info=True)

        basic_coin_data = temp_basic_data # Update global basic data store
        last_basic_update_time = datetime.now()
        logging.info(f"✅ Basic data fetch cycle finished. Processed {len(basic_coin_data)} coins.")

    except Exception as e:
        # Catch errors during the overall basic fetch process (e.g., market fetch fail)
        logging.error(f"Critical error during fetch_and_process_basic_data: {e}", exc_info=True)

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
                 # Catch errors during processing of a single coin
        logging.error(f"[{coin_symbol}] Error during BASIC processing for this coin: {e}", exc_info=True)

        basic_coin_data = temp_basic_data # Update global basic data store
        last_basic_update_time = datetime.now()
        logging.info(f"✅ Basic data fetch cycle finished. Processed {len(basic_coin_data)} coins.")

    except Exception as e:
        # Catch errors during the overall basic fetch process (e.g., market fetch fail)
        logging.error(f"Critical error during fetch_and_process_basic_data: {e}", exc_info=True)


# --- Modified update_data function ---
def update_data():
    """Main function to fetch all data, enrich with CG/Reddit, analyze coins, and update global state."""
    global market_data, sentiment_data, last_full_update_time, basic_coin_data
    logging.info("🚀 Starting FULL data update cycle (incl. order books)...")


    try:
        # --- Fetch Global/Market Data ---
        bybit_market_data = fetch_market_data()
        if not bybit_market_data:
            logging.error("Failed to fetch Bybit market data. Aborting full update cycle.")
            return
        market_data = bybit_market_data

        potential_coins = [
            item["symbol"].replace("USDT", "")
            for item in market_data.values()
            if item.get("symbol", "").endswith("USDT")
               and float(item.get("lastPrice", 0)) > 0
               and item.get("symbol")
        ]
        logging.info(f"Found {len(potential_coins)} potential USDT pairs for full analysis.")

        fear_greed_score, fear_greed_class = fetch_fear_greed_index()
        reddit_mentions = fetch_reddit_mentions(potential_coins)
        coingecko_markets = fetch_coingecko_market_data() # Still needed for sector
        cryptopanic_news = fetch_cryptopanic_news()

        sector_lookup = {
            item.get('symbol', '').upper(): next((cat for cat in item.get('categories', []) if cat), 'Unknown')
            for item in coingecko_markets if item.get('symbol')
        }

        processed_coins_data = []
        skipped_coins = Counter()
        current_basic_data = basic_coin_data.copy()

        for coin_symbol in potential_coins:
            symbol_usdt = coin_symbol + "USDT"
            market = market_data.get(symbol_usdt)
            basic_info = current_basic_data.get(coin_symbol)

            if not market:
                skipped_coins['market_data_missing'] += 1
                continue

            try:
                # --- Extract Fresh Data & Use Basic Fallbacks ---
                last_price_str = market.get("lastPrice")
                high_24h_str = market.get("highPrice24h")
                low_24h_str = market.get("lowPrice24h")
                volume_24h_str = market.get("volume24h") # Get fresh volume

                if not last_price_str: continue
                last_price = float(last_price_str)
                if last_price <= 0: continue

                high_24h = float(high_24h_str) if high_24h_str else None
                low_24h = float(low_24h_str) if low_24h_str else None
                volatility = None
                if high_24h is not None and low_24h is not None:
                    volatility = ((high_24h - low_24h) / last_price * 100) if last_price > 0 else 0
                elif basic_info:
                    volatility = basic_info.get('volatility_percent')

                zone, strategy = determine_volatility_zone(volatility)
                spread_percent = None
                
                orderbook_thin = True # Assume thin initially
                bids_asks = None # Store actual bids/asks if needed
                orderbook_data = fetch_orderbook(symbol_usdt) # Fetch it now
                if orderbook_data and orderbook_data.get('result'):
                     bids_raw = orderbook_data['result'].get('b', [])
                     asks_raw = orderbook_data['result'].get('a', [])
                     if bids_raw and asks_raw:
                         try:
                             best_bid = float(bids_raw[0][0])
                             best_ask = float(asks_raw[0][0])
                             if best_ask > best_bid > 0:
                                  spread_percent = (best_ask - best_bid) / last_price * 100
                                  orderbook_thin = spread_percent > 1.5 # Example threshold
                                  # Optionally store bids/asks for the final dict
                                  # bids_asks = {'bids': bids_raw[:5], 'asks': asks_raw[:5]}
                         except (ValueError, TypeError, IndexError):
                              logging.warning(f"[{coin_symbol}] Error processing order book data in full update.")

                # --- Spread: Use basic, don't refetch here unless necessary ---
               # spread_percent = basic_info.get('bid_ask_spread_percent') if basic_info else None
               # orderbook_thin = spread_percent > 1.5 if spread_percent is not None else True # Assume thin if spread unknown

                # --- <<< EARLY FILTERS >>> ---
                SPREAD_THRESHOLD = 1.5
                ALLOWED_VOLATILITY_ZONES = ["Very Low Volatility", "Low Volatility", "Medium Volatility"]

                # --- FIX: Skip if spread is None and filtering requires it ---
                if spread_percent is None:
                    logging.debug(f"[{coin_symbol}] Skipping full analysis due to missing spread info.")
                    skipped_coins['missing_spread_full'] += 1
                    continue # Cannot evaluate spread filter

                if spread_percent > SPREAD_THRESHOLD:
                    skipped_coins['high_spread_full'] += 1
                    continue

                if zone not in ALLOWED_VOLATILITY_ZONES:
                     skipped_coins['wrong_volatility_full'] += 1
                     continue

                # --- Passed Filters - Proceed with Intensive Analysis ---
                logging.debug(f"[{coin_symbol}] Passed filters. Performing full analysis...")

                # --- Timeframe, Candles, Indicators ---
                mtf_confirm, tf_status = analyze_timeframes(coin_symbol, last_price)
                candles_1h_data = fetch_candles(symbol_usdt, "60")
                closes = []
                volumes = []
                if candles_1h_data and candles_1h_data.get('result', {}).get('list'):
                    candle_list = candles_1h_data['result']['list']
                    closes = [float(c[4]) for c in candle_list if len(c) > 4]
                    volumes = [float(c[5]) for c in candle_list if len(c) > 5]
                else:
                     logging.warning(f"[{coin_symbol}] Could not get 1h candle data for indicators in full run.")
                     # Decide: skip coin or proceed with None indicators? Proceeding for now.

                rsi = calculate_rsi(closes) if closes else None
                volume_divergence = detect_volume_divergence(volumes) if volumes else None
                momentum_health = calculate_momentum_health(rsi, volume_divergence)

                # --- Call CoinGecko ---
                logging.info(f"[{coin_symbol}] Fetching CoinGecko metrics (cache check)...")
                cg_metrics = fetch_coingecko_metrics(coin_symbol)

                # --- FIX: Extract only the new metrics ---
                cg_sentiment_percentage = cg_metrics.get('cg_sentiment_votes_up_percentage')
                cg_community_score = cg_metrics.get('cg_community_score')
                cg_developer_score = cg_metrics.get('cg_developer_score')
                cg_public_interest_score = cg_metrics.get('cg_public_interest_score')
                # Extract others if needed for storage/display
                cg_slug = cg_metrics.get('cg_slug')

                # --- Reddit, News, BTC Inflow ---
                mentions = reddit_mentions.get(coin_symbol, 0)
                coin_news_sentiment = "neutral" # Recalculate news sentiment
                if cryptopanic_news:
                    # ... (news sentiment logic as before) ...
                    pass # Add news logic back
                btc_inflow_spike = False # Placeholder

                # --- Scoring ---
                # --- FIX: Pass correct arguments ---
                breakout_score = calculate_breakout_score(
                    rsi=rsi,
                    volume_rising=not volume_divergence if volume_divergence is not None else False,
                    news_sentiment=coin_news_sentiment,
                    spread_percent=spread_percent,
                    btc_inflow_spike=btc_inflow_spike,
                    orderbook_thin=orderbook_thin,
                    momentum_health=momentum_health,
                    cg_sentiment_percentage=cg_sentiment_percentage, # Pass new arg
                    cg_community_score=cg_community_score,         # Pass new arg
                    cg_developer_score=cg_developer_score,         # Pass new arg
                    cg_public_interest_score=cg_public_interest_score # Pass new arg
                )

                # --- Signals, Estimates ---
                tp_estimate = estimate_time_to_tp(breakout_score, zone)
                signal = "NEUTRAL" # Recalculate signal
                # ... (signal logic as before, adjust thresholds if needed) ...
                scalp_tp = round(last_price * 1.008, 4)
                scalp_sl = round(last_price * 0.992, 4)

                # --- FIX: Assemble FULL Coin Data ---
                coin_data = {
                    # Basic Info (potentially updated price/vol)
                    "symbol": coin_symbol,
                    "symbol_usdt": symbol_usdt,
                    "current_price": round(last_price, 4),
                    "volume_24h": float(volume_24h_str) if volume_24h_str else None,
                    "volatility_percent": round(volatility, 2) if volatility is not None else None,
                    "volatility_zone": zone,
                    "strategy_suggestion": strategy,
                    "bid_ask_spread_percent": round(spread_percent, 4) if spread_percent is not None else None,
                    # Analysis Results
                    "multi_timeframe_confirmation": mtf_confirm,
                    "timeframes_status": tf_status,
                    "rsi_1h": rsi,
                    "volume_divergence_1h": volume_divergence,
                    "momentum_health": momentum_health,
                    "breakout_score": breakout_score,
                    "signal": signal,
                    "time_estimate_to_tp": tp_estimate,
                    # Context / Enrichment
                    "sector": sector_lookup.get(coin_symbol.upper(), "Unknown"),
                    "reddit_mentions": mentions,
                    "news_sentiment": coin_news_sentiment,
                    "fear_greed_context": f"{fear_greed_score} ({fear_greed_class})",
                    "buy_window_note": get_buy_window(),
                    # CG Metrics
                    "cg_metrics_source": "CoinGecko API Proxy",
                    "cg_slug": cg_slug,
                    "cg_sentiment_votes_up_percentage": cg_sentiment_percentage,
                    "cg_community_score": cg_community_score,
                    "cg_developer_score": cg_developer_score,
                    "cg_public_interest_score": cg_public_interest_score,
                    # Placeholders / Other
                    "btc_inflow_spike": btc_inflow_spike,
                    "bid_ask_spread_percent": round(spread_percent, 4) if spread_percent is not None else None,
                    "orderbook_snapshot": { # Regenerate if needed, or maybe store basic bids/asks earlier?
                         "top_5_bids": None, # Placeholder - fetch if needed
                         "top_5_asks": None, # Placeholder - fetch if needed
                         "is_thin": orderbook_thin
                    },
                    "example_scalp_levels": {
                        "entry_approx": round(last_price, 4),
                        "tp": scalp_tp,
                        "sl": scalp_sl,
                    },
                    # Timestamps
                    "last_full_update": datetime.now().isoformat(),
                    "basic_update_timestamp": basic_info.get('timestamp') if basic_info else None
                }
                processed_coins_data.append(coin_data)

            except Exception as e:
                logging.error(f"[{coin_symbol}] Unexpected error during FULL processing for coin: {e}", exc_info=True)
                skipped_coins['unexpected_error_full'] += 1

        # --- Update Global State ---
        sentiment_data.clear()
        sentiment_data["timestamp"] = datetime.now().isoformat()
        sentiment_data["fear_greed"] = {"score": fear_greed_score, "classification": fear_greed_class}
        sentiment_data["processed_coins"] = processed_coins_data
        sentiment_data["update_summary"] = {
             "total_potential_coins": len(potential_coins),
             "successfully_processed_full": len(processed_coins_data),
             "skipped_counts": dict(skipped_coins)
        }
        last_full_update_time = datetime.now()
        logging.info(f"✅ FULL data update cycle finished. Processed {len(processed_coins_data)} coins fully. Skipped: {dict(skipped_coins)}")

    except Exception as e:
        logging.error(f"Critical error during full update_data execution: {e}", exc_info=True)

# --- Scheduler Setup ---
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(update_data, 'interval', minutes=60, next_run_time=datetime.now() + timedelta(minutes=1))
scheduler.start()


app.route("/sentiment")
def get_sentiment():
    """Returns the latest aggregated sentiment and coin analysis data (fully processed)."""
    if not sentiment_data or not sentiment_data.get("processed_coins"):
         return jsonify({"warning": "Full sentiment data is not available yet. Initializing or first scheduled run pending.",
                         "timestamp": last_full_update_time.isoformat() if last_full_update_time else None}), 404
    return jsonify(sentiment_data)
@app.route("/market")
def get_market():
    """Returns the raw market data fetched from Bybit."""
    if not market_data:
         return jsonify({"error": "Market data not available yet."}), 503
    # Use the timestamp from the last basic fetch as it updates market_data
    ts = last_basic_update_time.isoformat() if last_basic_update_time else None
    return jsonify({"timestamp": ts, "data": market_data})

@app.route("/scalp-sentiment")
def get_scalp_sentiment():
    """Filters fully processed sentiment data for potential scalp opportunities."""
    if not sentiment_data or not sentiment_data.get("processed_coins"):
         return jsonify({"error": "Full analysis data is not available yet. Please try again later."}), 503

    filtered_coins = []
    original_coins = sentiment_data.get("processed_coins", [])

    for coin in original_coins:
        try:
            # Use the fields from the fully populated coin_data dictionary
            spread = coin.get("bid_ask_spread_percent")
            if spread is None or spread > 0.3: continue

            volatility_zone = coin.get("volatility_zone", "")
            if not volatility_zone.startswith("Very Low") and not volatility_zone.startswith("Low"): continue

            if not coin.get("multi_timeframe_confirmation"): continue

            if coin.get("breakout_score", 0) < 6: continue # Adjust score threshold if needed

            rsi = coin.get("rsi_1h")
            if rsi is None or not (45 <= rsi <= 65): continue

            time_estimate = coin.get("time_estimate_to_tp", "")
            if not time_estimate.startswith("1") and not time_estimate.startswith("2"): continue

            if coin.get("momentum_health") != "strong": continue

            filtered_coins.append(coin)

        except Exception as e:
            logging.warning(f"Error filtering coin {coin.get('symbol', 'N/A')} for scalp: {e}")
            continue

    return jsonify({
        "timestamp": datetime.now().isoformat(), # Or use sentiment_data["timestamp"]
        "strategy": "Scalping Filter (Strict Criteria Applied to Fully Processed Data)",
        "qualified_coins": filtered_coins,
        "total_checked_in_full_run": len(original_coins),
        "total_qualified": len(filtered_coins)
    })

@app.route("/health")
def get_health():
    """Provides a basic health check of the API."""
    status = "ok"
    message = "API is running."
    full_update_ts = last_full_update_time # Use the correct variable

    if not sentiment_data.get("processed_coins"): # Check if full processing has happened
        status = "initializing"
        message = "API is running. Basic data fetched. Full analysis pending first scheduled run."
    elif full_update_ts and (datetime.now() - full_update_ts).total_seconds() > (90 * 60): # Check if full update is stale (e.g., > 90 mins)
         status = "stale_data"
         message = f"API is running, but full analysis data seems stale. Last full update: {full_update_ts.isoformat()}"

    return jsonify({
        "status": status,
        "message": message,
        "last_basic_update": last_basic_update_time.isoformat() if last_basic_update_time else None,
        "last_full_update": full_update_ts.isoformat() if full_update_ts else None
        })
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
        fetch_and_process_basic_data()
        logging.info("Initial BASIC data fetch complete.")
    except Exception as e:
        logging.critical(f"❗ Failed during initial basic data fetch: {e}", exc_info=True)

    port = int(os.environ.get("PORT", 5000))
    logging.info(f"🚀 Starting Flask server on host 0.0.0.0 port {port}")
    try:
        # Consider using a production server like waitress or gunicorn
        # from waitress import serve
        # serve(app, host='0.0.0.0', port=port)
        app.run(host="0.0.0.0", port=port) # Development server
    except Exception as e:
         logging.critical(f"❗ Flask server failed to start or crashed: {e}", exc_info=True)
