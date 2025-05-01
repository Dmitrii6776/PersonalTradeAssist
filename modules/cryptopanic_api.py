import requests
import os
import logging

# Fetch API key from environment variable
CRYPTO_PANIC_API_KEY = os.environ.get("CRYPTO_PANIC_API_KEY")
CRYPTO_PANIC_API_URL = "https://cryptopanic.com/api/v1/posts/"

if not CRYPTO_PANIC_API_KEY:
    logging.warning("CRYPTO_PANIC_API_KEY environment variable not set. CryptoPanic news fetching will be disabled.")

def fetch_cryptopanic_news():
    """Fetch top hot news from CryptoPanic. Requires CRYPTO_PANIC_API_KEY env var."""
    if not CRYPTO_PANIC_API_KEY:
        return [] # Return empty list if API key is missing

    try:
        params = {
            "auth_token": CRYPTO_PANIC_API_KEY,
            "filter": "hot", # You can change filter (e.g., 'rising')
            "kind": "news",
            "public": "true", # Fetch publicly available news
            # "currencies": "BTC,ETH", # Optional: filter by specific currencies
            # "regions": "en", # Optional: filter by language/region
        }
        response = requests.get(CRYPTO_PANIC_API_URL, params=params, timeout=15)
        response.raise_for_status() # Raise HTTPError for bad responses

        data = response.json()
        news_results = data.get('results', [])
        logging.info(f"Fetched {len(news_results)} news items from CryptoPanic.")
        return news_results

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching CryptoPanic news: {e}")
        return []
    except requests.exceptions.JSONDecodeError as e:
         logging.error(f"Error decoding CryptoPanic JSON response: {e}")
         return []
    except Exception as e:
        logging.error(f"Unexpected exception in fetch_cryptopanic_news: {e}", exc_info=True)
        return []
