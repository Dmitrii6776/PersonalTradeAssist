import requests
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Setup retry strategy
retry_strategy = Retry(
    total=3,
    backoff_factor=1, # E.g., sleep 1s, 2s, 4s between retries
    status_forcelist=[429, 500, 502, 503, 504], # Status codes to retry on
    allowed_methods=["HEAD", "GET", "OPTIONS"] # Use 'allowed_methods' instead of 'method_whitelist'
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests.Session()
session.mount("https://", adapter)
session.mount("http://", adapter)

BYBIT_V5_URL = "https://api.bybit.com/v5"

def _make_request(endpoint, params=None):
    """Helper function to make requests to Bybit API."""
    url = f"{BYBIT_V5_URL}{endpoint}"
    try:
        response = session.get(url, params=params, timeout=10) # Use configured session
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        data = response.json()
        if data.get("retCode") == 0 and "result" in data:
            return data["result"]
        else:
            logging.error(f"Bybit API error: Code={data.get('retCode')}, Msg={data.get('retMsg')}, Endpoint={endpoint}")
            return None # Indicate API level error

    except requests.exceptions.RequestException as e:
        logging.error(f"❗ HTTP Error for Bybit endpoint {endpoint}: {e}")
        return None # Indicate HTTP level error
    except requests.exceptions.JSONDecodeError as e:
         logging.error(f"❗ JSON Decode Error for Bybit endpoint {endpoint}: {e}. Response: {response.text[:200]}")
         return None
    except Exception as e:
         logging.error(f"❗ Unexpected Error during Bybit request {endpoint}: {e}", exc_info=True)
         return None


def fetch_market_data():
    """
    Fetches ticker information for all spot markets from Bybit V5.

    Returns:
        dict: A dictionary mapping symbol (e.g., 'BTCUSDT') to its ticker data,
              or an empty dict if the fetch fails.
    """
    logging.info("Fetching Bybit market tickers...")
    result = _make_request("/market/tickers", {"category": "spot"})
    market_dict = {}
    if result and "list" in result:
        for item in result["list"]:
            if item.get("symbol"):
                market_dict[item["symbol"]] = item
        logging.info(f"Successfully fetched data for {len(market_dict)} Bybit spot tickers.")
        return market_dict
    else:
        logging.error("Failed to fetch or parse Bybit market tickers list.")
        return {}


def fetch_orderbook(symbol):
    """
    Fetches the level 1 order book (best bid/ask) for a specific symbol from Bybit V5.

    Args:
        symbol (str): The market symbol (e.g., 'BTCUSDT').

    Returns:
        dict: The order book result containing 'a' (asks) and 'b' (bids),
              or None if the fetch fails.
              Format: {'ts': timestamp, 's': symbol, 'b': [['price', 'size']], 'a': [['price', 'size']], 'u': updateId}
    """
    logging.debug(f"Fetching Bybit order book for {symbol}...")
    # Limit=1 fetches best bid/ask, Limit=5 fetches top 5 levels
    params = {"category": "spot", "symbol": symbol, "limit": 5}
    result = _make_request("/market/orderbook", params)
    if result and 'b' in result and 'a' in result:
        # logging.debug(f"Successfully fetched order book for {symbol}.")
        return result # Return the whole result dict
    else:
        logging.warning(f"Failed to fetch or parse order book for {symbol}.")
        return None


def fetch_candles(symbol, interval):
    """
    Fetches Kline (candle) data for a specific symbol and interval from Bybit V5.

    Args:
        symbol (str): The market symbol (e.g., 'BTCUSDT').
        interval (str): Kline interval ('1', '3', '5', '15', '30', '60', '120', '240', '360', '720', 'D', 'W', 'M').

    Returns:
        dict: The Kline result containing the 'list' of candles [[ts, O, H, L, C, V, Turnover]],
              or None if the fetch fails.
    """
    logging.debug(f"Fetching Bybit {interval} candles for {symbol}...")
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": 200} # Fetch enough for indicators (e.g., 200 for RSI 14)
    result = _make_request("/market/kline", params)
    if result and "list" in result:
        # logging.debug(f"Successfully fetched {len(result['list'])} candles for {symbol} interval {interval}.")
        return result # Return the whole result dict which includes the list
    else:
        logging.warning(f"Failed to fetch or parse candles for {symbol} interval {interval}.")
        return None
