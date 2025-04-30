import requests
import time

COINGECKO_SLUGS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "SOL": "solana",
    "ADA": "cardano",
    "DOGE": "dogecoin"
}

def fetch_social_metrics(symbol):
    try:
        slug = COINGECKO_SLUGS.get(symbol.upper())
        if not slug:
            print(f"[CoinGecko fallback] No slug mapping for {symbol}, skipping")
            return {}

        url = f"https://api.coingecko.com/api/v3/coins/{slug}"
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"[CoinGecko fallback] {slug} returned status {response.status_code}")
            return {}

        try:
            data = response.json()
        except Exception:
            print(f"[CoinGecko fallback] JSON decode error for {slug}")
            return {}

        sentiment_score = data.get("sentiment_votes_up_percentage") or 0

        time.sleep(0.7)

        return {
            "whale_alert": sentiment_score > 65,
            "social_dominance_spike": sentiment_score > 55,
            "active_address_spike": sentiment_score > 45
        }

    except Exception as e:
        print(f"[CoinGecko fallback] Error for {symbol}:", e)
        return {}
