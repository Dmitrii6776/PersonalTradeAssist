def fetch_market_data():
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=spot"
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