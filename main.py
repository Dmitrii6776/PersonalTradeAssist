import requests
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
from collections import Counter
from apscheduler.schedulers.background import BackgroundScheduler

from modules.bybit_api import fetch_market_data, fetch_orderbook, fetch_candles
from modules.coingecko_api import fetch_coingecko_market_data, fetch_coingecko_categories
from modules.cryptopanic_api import fetch_cryptopanic_news
from modules.santiment_api import fetch_social_metrics
from modules.momentum_analysis import calculate_rsi, detect_volume_divergence, calculate_momentum_health
from modules.breakout_scoring import calculate_breakout_score
from modules.buy_timing_logic import get_buy_window

app = Flask(__name__)
CORS(app)

market_data = {}
sentiment_data = {}


def determine_volatility_zone(volatility):
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
    if score >= 7 and 'Low' in volatility_zone:
        return "1–3 hours"
    elif score >= 5:
        return "4–6 hours"
    elif score >= 3:
        return "6–12 hours"
    else:
        return "Uncertain"


def analyze_timeframes(symbol, last_price):
    def calculate_ema(values, period=20):
        if len(values) < period:
            return None
        k = 2 / (period + 1)
        ema = values[0]
        for price in values[1:]:
            ema = price * k + ema * (1 - k)
        return ema

    results = {}
    timeframes = {"15m": 15, "1h": 60, "4h": 240}
    bullish_confirm = True

    for name, minutes in timeframes.items():
        candles = fetch_candles(symbol, minutes)
        closes = [float(c[4]) for c in candles] if candles else []
        if not closes:
            results[name] = {"price": last_price, "ema20": None, "trend": "unknown"}
            bullish_confirm = False
            continue

        ema20 = calculate_ema(closes)
        trend = "bullish" if last_price > ema20 else "bearish"

        results[name] = {
            "price": round(last_price, 4),
            "ema20": round(ema20, 4) if ema20 else None,
            "trend": trend
        }

        if trend != "bullish":
            bullish_confirm = False

    return bullish_confirm, results


def fetch_fear_greed_index():
    try:
        data = requests.get("https://api.alternative.me/fng/?limit=1").json()
        d = data['data'][0]
        return int(d['value']), d['value_classification']
    except:
        return 50, "Neutral"


def fetch_reddit_mentions(symbols):
    try:
        posts = requests.get("https://www.reddit.com/r/CryptoCurrency/new.json", headers={"User-Agent": "Mozilla/5.0"}).json()
        all_titles = " ".join([p['data']['title'] for p in posts['data']['children']]).lower()
        mentions = Counter()
        for symbol in symbols:
            mentions[symbol] = all_titles.count(symbol.lower())
        return mentions
    except:
        return Counter()


def update_data():
    global market_data, sentiment_data

    try:
        market_data = fetch_market_data()
        trending_coins = requests.get("https://api.coingecko.com/api/v3/search/trending").json()
        trending_coins = [c['item']['symbol'].upper() for c in trending_coins['coins']]
        fear_greed_score, fear_greed_class = fetch_fear_greed_index()
        reddit_mentions = fetch_reddit_mentions(trending_coins)
        coingecko_markets = fetch_coingecko_market_data()
        coingecko_categories = fetch_coingecko_categories()
        cryptopanic_news = fetch_cryptopanic_news()

        sector_lookup = {item.get('symbol', '').upper(): item.get('category', 'Unknown') for item in coingecko_markets}

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
            coin_news_sentiment = "positive" if any(
                coin.lower() in n['title'].lower() and n.get("votes", {}).get("positive", 0) > n.get("votes", {}).get("negative", 0)
                for n in cryptopanic_news
            ) else "neutral"

            btc_inflow_spike = False

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
                "time_estimate_to_tp": tp_estimate,
                "buy_window_note": get_buy_window()
            })

    except Exception as e:
        print("Error during update:", e)


scheduler = BackgroundScheduler()
scheduler.add_job(update_data, 'interval', minutes=30)
scheduler.start()
update_data()


@app.route("/sentiment")
def get_sentiment():
    return jsonify(sentiment_data)

@app.route("/market")
def get_market():
    return jsonify(market_data)

@app.route("/health")
def get_health():
    return jsonify({"status": "ok"})

@app.route("/legal")
def legal():
    return send_from_directory("static", "legal.html")

@app.route("/openapi.yaml")
def serve_openapi():
    return send_from_directory("static", "openapi.yaml")
