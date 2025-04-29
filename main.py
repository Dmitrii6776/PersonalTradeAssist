# 🚀 Ultimate Bybit Spot Trading Assistant API

import requests
from bs4 import BeautifulSoup
from collections import Counter
import re
import json
from datetime import datetime
from flask import Flask, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from modules.coingecko_api import fetch_coingecko_market_data, fetch_coingecko_categories
from modules.cryptopanic_api import fetch_cryptopanic_news
from modules.santiment_api import fetch_social_metrics

app = Flask(__name__)

# --- Global Data Storage ---
market_data = {}
sentiment_data = {}

# --- Configuration ---
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers?category=spot"
BYBIT_ORDERBOOK_URL = "https://api.bybit.com/v5/market/orderbook?category=spot&symbol={}"
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline?category=spot&symbol={}&interval={}&limit=20"
COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
FEAR_GREED_URL = "https://api.alternative.me/fng/"
REDDIT_URL = "https://www.reddit.com/r/CryptoCurrency/top/?t=day"
USER_AGENT = {"User-Agent": "Mozilla/5.0"}

# --- Helper Functions ---

def fetch_market_data():
    try:
        response = requests.get(BYBIT_TICKERS_URL)
        if response.status_code == 200:
            data = response.json()
            market_data = {}
            for coin_info in data['result']['list']:
                symbol = coin_info['symbol'].upper()
                market_data[symbol] = {
                    "last": float(coin_info['lastPrice']),
                    "high": float(coin_info['highPrice24h']),
                    "low": float(coin_info['lowPrice24h'])
                }
            return market_data
        else:
            return {}
    except:
        return {}

def fetch_trending_coins():
    try:
        response = requests.get(COINGECKO_TRENDING_URL)
        data = response.json()
        trending = [coin['item']['symbol'].upper() for coin in data['coins']]
        return trending
    except:
        return []

def fetch_fear_greed_index():
    try:
        response = requests.get(FEAR_GREED_URL)
        data = response.json()
        score = data['data'][0]['value']
        classification = data['data'][0]['value_classification']
        return int(score), classification
    except:
        return 50, "Neutral"

def fetch_reddit_mentions(trending_coins):
    try:
        response = requests.get(REDDIT_URL, headers=USER_AGENT)
        soup = BeautifulSoup(response.text, 'html.parser')
        posts = soup.find_all('h3')
        text_content = ' '.join(post.get_text() for post in posts)
        mentions = Counter()
        for symbol in trending_coins:
            pattern = r'\\b' + re.escape(symbol) + r'\\b'
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            mentions[symbol] = len(matches)
        return mentions
    except:
        return Counter()

def fetch_orderbook(symbol):
    try:
        url = BYBIT_ORDERBOOK_URL.format(symbol + "USDT")
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            bids = []
            asks = []
            for entry in data['result']:
                if entry['side'] == 'Buy':
                    bids.append({"price": float(entry['price']), "size": float(entry['size'])})
                elif entry['side'] == 'Sell':
                    asks.append({"price": float(entry['price']), "size": float(entry['size'])})
            bids = sorted(bids, key=lambda x: -x['price'])[:5]
            asks = sorted(asks, key=lambda x: x['price'])[:5]
            return bids, asks
        else:
            return [], []
    except:
        return [], []

def fetch_candles(symbol, interval):
    try:
        url = BYBIT_KLINE_URL.format(symbol + "USDT", interval)
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            closes = [float(candle[4]) for candle in data['result']['list']]
            return closes
        else:
            return []
    except:
        return []

def calculate_ema(values, period=20):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for price in values[1:]:
        ema = price * k + ema * (1 - k)
    return ema

def analyze_timeframes(symbol, last_price):
    results = {}
    timeframes = {"15m": 15, "1h": 60, "4h": 240}
    bullish_confirm = True

    for name, minutes in timeframes.items():
        closes = fetch_candles(symbol, minutes)
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

# --- Core Update Function ---
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
        sector_lookup = {}
        for item in coingecko_markets:
            symbol = item.get('symbol', '').upper()
            category = item.get('category', 'Unknown')
            sector_lookup[symbol] = category

        sentiment_data = {
            "timestamp": datetime.now().isoformat(),
            "fear_greed": {
                "score": fear_greed_score,
                "classification": fear_greed_class
            },
            "trending_coins": []
        }

        for coin in trending_coins:
            market = market_data.get(coin + "USDT", None)
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
            if bids and asks:
                best_bid = bids[0]['price']
                best_ask = asks[0]['price']
                spread_percent = (best_ask - best_bid) / last_price * 100
            else:
                spread_percent = None

            mtf_confirm, tf_status = analyze_timeframes(coin, last_price)
            sector = sector_lookup.get(coin, "Unknown")  # 🆕 sector

    # 🆕 INSERT News Sentiment Scanner Here
            coin_news_sentiment = "neutral"
            for news in cryptopanic_news:
                title = news.get('title', '').lower()
                if coin.lower() in title:
                    if news.get('votes', {}).get('positive', 0) > news.get('votes', {}).get('negative', 0):
                        coin_news_sentiment = "positive"
                        break
                    elif news.get('votes', {}).get('negative', 0) > news.get('votes', {}).get('positive', 0):
                        coin_news_sentiment = "negative"
                        break

            social_metrics = fetch_social_metrics(coin)

            social_dominance_spike = False
            active_address_spike = False

            if social_metrics:
                dominance_points = social_metrics.get('socialDominance', [])
                address_points = social_metrics.get('activeAddresses', [])

                if len(dominance_points) >= 2:
                    delta_dominance = dominance_points[-1]['dominance'] - dominance_points[-2]['dominance']
                    if delta_dominance > 0.5:  # >0.5% increase
                        social_dominance_spike = True

                if len(address_points) >= 2:
                    delta_addresses = address_points[-1]['activeAddresses'] - address_points[-2]['activeAddresses']
                    if delta_addresses > 100:  # 100+ active wallets surge
                        active_address_spike = True

            sentiment_data["trending_coins"].append({
                "symbol": coin,
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
                "sector": sector,  # 🆕
                "news_sentiment": coin_news_sentiment,  # 🆕
                "social_dominance_spike": social_dominance_spike,  # 🆕
                "active_address_spike": active_address_spike  # 🆕
            })
    except Exception as e:
        print(f"Error during update: {e}")

# --- Flask API Routes ---
@app.route("/")
def root():
    return "Ultimate Bybit Spot Trading Assistant API is running 🚀"

@app.route("/sentiment", methods=["GET"])
def get_sentiment_data():
    return jsonify(sentiment_data)

@app.route("/market", methods=["GET"])
def get_market_data():
    return jsonify(market_data)

@app.route("/legal", methods=["GET"])
def legal_page():
    return render_template("legal.html")

@app.route("/health", methods=["GET"])
def health_page():
    return jsonify({"status": "ok"})

@app.route("/openapi.yaml", methods=["GET"])
def serve_openapi_yaml():
    return app.send_static_file("openapi.yaml")

# --- Main Execution ---
if __name__ == "__main__":
    update_data()
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_data, "interval", minutes=30)
    scheduler.start()
    app.run(host="0.0.0.0", port=8000)
