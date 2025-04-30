import requests
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
from collections import Counter
from apscheduler.schedulers.background import BackgroundScheduler

from modules.coingecko_api import fetch_coingecko_market_data, fetch_coingecko_categories
from modules.cryptopanic_api import fetch_cryptopanic_news
from modules.santiment_api import fetch_social_metrics
from modules.momentum_analysis import calculate_rsi, detect_volume_divergence, calculate_momentum_health
from modules.breakout_scoring import calculate_breakout_score
from modules.buy_timing_logic import get_buy_window
from modules.bybit_api import fetch_market_data

app = Flask(__name__)
CORS(app)

market_data = {}
sentiment_data = {}

BYBIT_PRICE_URL = "https://api.bybit.com/v5/market/tickers?category=spot"
BYBIT_ORDERBOOK_URL = "https://api.bybit.com/v5/market/orderbook?category=spot&symbol={}"
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline?category=spot&symbol={}&interval={}"

# ... (other function definitions unchanged)

# Add the main data update function

def update_data():
    global market_data, sentiment_data

    try:
        market_data = fetch_market_data()
        trending_coins = fetch_trending_coins()
        fear_greed_score, fear_greed_class = fetch_fear_greed_index()
        reddit_mentions = fetch_reddit_mentions(trending_coins)
        coingecko_markets = fetch_coingecko_market_data()
        coingecko_categories = fetch_coingecko_categories()
        cryptopanic_news = fetch_cryptopanic_news()

        # Build sector lookup
        sector_lookup = {}
        for item in coingecko_markets:
            symbol = item.get('symbol', '').upper()
            sector_lookup[symbol] = item.get('category', 'Unknown')

        sentiment_data = {
            "timestamp": datetime.now().isoformat(),
            "fear_greed": {
                "score": fear_greed_score,
                "classification": fear_greed_class
            },
            "trending_coins": []
        }

        for coin in trending_coins:
            market = market_data.get(coin + "USDT")
            if not market:
                continue

            last_price = market['last']
            high_24h = market['high']
            low_24h = market['low']
            volatility = (high_24h - low_24h) / last_price * 100
            zone, strategy = determine_volatility_zone(volatility)

            mentions = reddit_mentions.get(coin, 0)
            signal = "BUY" if mentions >= 2 and fear_greed_score >= 50 else "CAUTION"

            bids, asks = fetch_orderbook(coin)
            spread_percent = None
            if bids and asks:
                best_bid = bids[0]['price']
                best_ask = asks[0]['price']
                spread_percent = (best_ask - best_bid) / last_price * 100

            mtf_confirm, tf_status = analyze_timeframes(coin, last_price)

            closes = [float(c[4]) for c in fetch_candles(coin, 60)]
            volumes = [float(c[5]) for c in fetch_candles(coin, 60)]

            rsi = calculate_rsi(closes)
            volume_divergence = detect_volume_divergence(volumes)
            momentum_health = calculate_momentum_health(rsi, volume_divergence)

            social_metrics = fetch_social_metrics(coin)
            coin_whale_alert = social_metrics.get('whale_alert', False)
            coin_news_sentiment = "positive" if any("{}".format(coin.lower()) in n['title'].lower() and n.get("votes", {}).get("positive", 0) > n.get("votes", {}).get("negative", 0) for n in cryptopanic_news) else "neutral"

            btc_inflow_spike = False  # Add BTC inflow spike logic if needed

            breakout_score = calculate_breakout_score(
                rsi=rsi,
                volume_rising=not volume_divergence,
                whale_alert=coin_whale_alert,
                news_sentiment=coin_news_sentiment,
                spread_percent=spread_percent,
                btc_inflow_spike=btc_inflow_spike,
                orderbook_thin=(spread_percent is not None and spread_percent > 1.5),
                momentum_health=momentum_health,
            )

            tp_estimate = estimate_time_to_tp(breakout_score, zone)

            sentiment_data["trending_coins"].append({
                "symbol": coin,
                "current_price": round(last_price, 2),
                "price_source": "Bybit Spot API",
                "reddit_mentions": mentions,
                "signal": signal,
                "volatility_percent": round(volatility, 2),
                "volatility_zone": zone,
                "strategy_description": strategy,
                "bid_ask_spread_percent": round(spread_percent, 4) if spread_percent else None,
                "top_5_bids": bids,
                "top_5_asks": asks,
                "multi_timeframe_confirmation": mtf_confirm,
                "timeframes_status": tf_status,
                "sector": sector_lookup.get(coin, "Unknown"),
                "news_sentiment": coin_news_sentiment,
                "social_dominance_spike": social_metrics.get("social_dominance_spike", False),
                "active_address_spike": social_metrics.get("active_address_spike", False),
                "whale_alert": coin_whale_alert,
                "btc_inflow_spike": btc_inflow_spike,
                "rsi": rsi,
                "volume_divergence": volume_divergence,
                "momentum_health": momentum_health,
                "breakout_score": breakout_score,
                "time_estimate_to_tp": tp_estimate
                
            })

    except Exception as e:
        print("Error during update:", e)


scheduler = BackgroundScheduler()
scheduler.add_job(update_data, 'interval', minutes=30)
scheduler.start()

update_data()
