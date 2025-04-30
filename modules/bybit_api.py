import requests

BYBIT_BASE_URL = "https://api.bybit.com/v5/market"


def fetch_market_data():
    try:
        url = f"{BYBIT_BASE_URL}/tickers?category=spot"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            tickers = data['result']['list']
            return {
                t['symbol']: {
                    'last': float(t['lastPrice']),
                    'high': float(t['highPrice24h']),
                    'low': float(t['lowPrice24h'])
                }
                for t in tickers
            }
    except Exception as e:
        print("Error in fetch_market_data:", e)
    return {}


def fetch_orderbook(symbol):
    try:
        url = f"{BYBIT_BASE_URL}/orderbook?category=spot&symbol={symbol}USDT"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            bids = sorted(
                [{"price": float(e["price"]), "size": float(e["size"])} for e in data["result"] if e["side"] == "Buy"],
                key=lambda x: -x["price"]
            )[:5]
            asks = sorted(
                [{"price": float(e["price"]), "size": float(e["size"])} for e in data["result"] if e["side"] == "Sell"],
                key=lambda x: x["price"]
            )[:5]
            return bids, asks
    except Exception as e:
        print("Error in fetch_orderbook:", e)
    return [], []


def fetch_candles(symbol, interval):
    try:
        url = f"{BYBIT_BASE_URL}/kline?category=spot&symbol={symbol}USDT&interval={interval}"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()['result']['list']
    except Exception as e:
        print("Error in fetch_candles:", e)
    return []
