import requests

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_CATEGORIES_URL = "https://api.coingecko.com/api/v3/coins/categories"

def fetch_coingecko_market_data():
    try:
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": 1,
            "sparkline": "false"
        }
        response = requests.get(COINGECKO_MARKETS_URL, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching CoinGecko markets: {response.status_code}")
            return []
    except Exception as e:
        print(f"Exception in fetch_coingecko_market_data: {e}")
        return []

def fetch_coingecko_categories():
    try:
        response = requests.get(COINGECKO_CATEGORIES_URL)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching CoinGecko categories: {response.status_code}")
            return []
    except Exception as e:
        print(f"Exception in fetch_coingecko_categories: {e}")
        return []