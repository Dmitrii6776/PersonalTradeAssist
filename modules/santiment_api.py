import requests

SANTIMENT_API_URL = "https://api.santiment.net/graphql"
SANTIMENT_API_KEY = "ms6qbmnwxnq6xtne_dx56zkd4toaz3xgz"  # Replace with env or config in production


def fetch_social_metrics(symbol):
    try:
        url = f"{SANTIMENT_API_BASE}/v1/assets/{symbol.lower()}/social_volume"
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
            "social_dominance_spike": data.get("social_dominance", 0) > 1.5,  # mock logic
            "active_address_spike": data.get("unique_social_users", 0) > 150,  # mock
            "whale_alert": data.get("whale_mentions", 0) > 3  # mock
        }

    except Exception as e:
        print(f"Error fetching Santiment social data for {symbol}:", e)
        return {}
