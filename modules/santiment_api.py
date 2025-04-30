import requests

def fetch_social_metrics(symbol):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            print(f"[CoinGecko fallback] {symbol} returned status {response.status_code}")
            return {}

        try:
            data = response.json()
        except Exception:
            print(f"[CoinGecko fallback] JSON decode error for {symbol}")
            return {}

        sentiment_score = data.get("sentiment_votes_up_percentage") or 0

        return {
            "whale_alert": sentiment_score > 65,
            "social_dominance_spike": sentiment_score > 55,
            "active_address_spike": sentiment_score > 45
        }

    except Exception as e:
        print(f"[CoinGecko fallback] Error for {symbol}:", e)
        return {}
