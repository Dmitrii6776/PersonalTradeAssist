import requests

SANTIMENT_API_BASE = "https://api.santiment.net"
SANTIMENT_API_KEY = "ms6qbnmwxnq6xtne_dx56zkd4tkoaz3xgz"

# Slug mapping required by Santiment's asset endpoint
SANTIMENT_SYMBOL_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binance-coin",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "SOL": "solana",
    "AVAX": "avalanche",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "polygon",
    "LTC": "litecoin"
}

def fetch_social_metrics(symbol):
    try:
        slug = SANTIMENT_SYMBOL_MAP.get(symbol.upper())
        if not slug:
            return {}  # Skip unsupported assets

        url = f"{SANTIMENT_API_BASE}/v1/assets/{slug}/social_volume"
        headers = {"Authorization": f"Bearer {SANTIMENT_API_KEY}"}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 429:
            print(f"Rate limit hit when fetching Santiment data for {symbol} (429). Skipping...")
            return {}

        if response.status_code != 200:
            print(f"Error fetching Santiment data for {symbol}: {response.status_code}")
            return {}

        data = response.json()

        return {
            "social_dominance_spike": data.get("social_dominance", 0) > 1.5,
            "active_address_spike": data.get("unique_social_users", 0) > 150,
            "whale_alert": data.get("whale_mentions", 0) > 3
        }

    except Exception as e:
        print(f"Error fetching Santiment social data for {symbol}:", e)
        return {}
