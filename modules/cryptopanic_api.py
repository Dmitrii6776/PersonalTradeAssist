import requests

CRYPTO_PANIC_API_URL = "https://cryptopanic.com/api/v1/posts/"
CRYPTO_PANIC_API_KEY = "4df2734b13aae958a42beccf84983aa2e13d8317"  # 🔥 Replace with your real API key 🔥

def fetch_cryptopanic_news():
    """Fetch top hot news from CryptoPanic."""
    try:
        params = {
            "auth_token": CRYPTO_PANIC_API_KEY,
            "filter": "hot",
            "kind": "news",
            "regions": "en",
            "public": "true"
        }
        response = requests.get(CRYPTO_PANIC_API_URL, params=params)
        if response.status_code == 200:
            return response.json().get('results', [])
        else:
            print(f"Error fetching CryptoPanic news: {response.status_code}")
            return []
    except Exception as e:
        print(f"Exception in fetch_cryptopanic_news: {e}")
        return []
