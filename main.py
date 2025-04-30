import os
import time
import requests
from flask import Flask, jsonify
from datetime import datetime
from modules.coingecko_api import fetch_coingecko_market_data, fetch_coingecko_categories
from modules.cryptopanic_api import fetch_cryptopanic_news
from modules.momentum_analysis import calculate_rsi, detect_volume_divergence, calculate_momentum_health
from modules.breakout_scoring import calculate_breakout_score
from modules.buy_timing_logic import get_buy_window
from modules.santiment_api import fetch_social_metrics

app = Flask(__name__)

market_data = {}
sentiment_data = {}

@app.route("/")
def home():
    return "✅ PersonalTradeAssist is running."

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

def update_data():
    global market_data, sentiment_data

    print("🔄 Starting update_data...")
    try:
        trending_coins = ["BTC", "ETH", "XRP", "SOL", "ADA", "DOGE"]
        sentiment_data["trending_coins"] = []

        for symbol in trending_coins:
            print(f"📊 Processing {symbol}...")
            social_metrics = fetch_social_metrics(symbol)
            print(f"✅ Fetched metrics for {symbol}:", social_metrics)
            sentiment_data["trending_coins"].append({
                "symbol": symbol,
                **social_metrics
            })

        sentiment_data["timestamp"] = datetime.utcnow().isoformat()
        print("✅ update_data completed successfully")

    except Exception as e:
        print("❌ update_data failed:", e)

@app.route("/sentiment")
def get_sentiment():
    return jsonify({
        "timestamp": sentiment_data.get("timestamp"),
        "sample": sentiment_data.get("trending_coins", [])[:3]  # limit output for testing
    })

if __name__ == "__main__":
    try:
        update_data()
    except Exception as e:
        print("❗ Failed during update_data():", e)

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
