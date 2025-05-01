import requests
import logging
import time

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_CATEGORIES_URL = "https://api.coingecko.com/api/v3/coins/categories"
COINGECKO_DELAY = 1.5 # Delay between requests to respect free tier rate limits

def fetch_coingecko_market_data():
    """Fetches market data for top coins from CoinGecko."""
    logging.info("Fetching CoinGecko market data...")
    try:
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250, # Max allowed by API
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d", # Optional: get price changes
            "locale": "en"
        }
        response = requests.get(COINGECKO_MARKETS_URL, params=params, timeout=20) # Increased timeout
        response.raise_for_status()
        market_data = response.json()
        logging.info(f"Successfully fetched market data for {len(market_data)} coins from CoinGecko.")
        time.sleep(COINGECKO_DELAY) # Pause after request
        return market_data
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching CoinGecko markets: {e}")
        return []
    except requests.exceptions.JSONDecodeError as e:
        logging.error(f"Error decoding CoinGecko markets JSON: {e}")
        return []
    except Exception as e:
        logging.error(f"Unexpected error fetching CoinGecko markets: {e}", exc_info=True)
        return []

def fetch_coingecko_categories():
    """Fetches category data from CoinGecko."""
    logging.info("Fetching CoinGecko category data...")
    try:
        response = requests.get(COINGECKO_CATEGORIES_URL, timeout=15)
        response.raise_for_status()
        categories = response.json()
        logging.info(f"Successfully fetched {len(categories)} categories from CoinGecko.")
        time.sleep(COINGECKO_DELAY) # Pause after request
        return categories
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching CoinGecko categories: {e}")
        return []
    except requests.exceptions.JSONDecodeError as e:
        logging.error(f"Error decoding CoinGecko categories JSON: {e}")
        return []
    except Exception as e:
        logging.error(f"Unexpected error fetching CoinGecko categories: {e}", exc_info=True)
        return []
