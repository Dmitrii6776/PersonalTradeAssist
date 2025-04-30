import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=3))

def fetch_market_data():
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=spot"
        response = session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        result = {}
        for item in data.get("result", {}).get("list", []):
            result[item["symbol"]] = item
        return result
    except requests.exceptions.RequestException as e:
        print("❗ Error in fetch_market_data:", e)
        return {}

def fetch_orderbook(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/orderbook?category=spot&symbol={symbol}&limit=1"
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❗ Error in fetch_orderbook for {symbol}:", e)
        return {}

def fetch_candles(symbol, interval):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval={interval}"
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❗ Error in fetch_candles for {symbol}:", e)
        return {}
