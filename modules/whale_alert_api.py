import requests

WHALE_ALERT_API_URL = "https://api.whale-alert.io/v1/transactions"
WHALE_ALERT_API_KEY = "YOUR_API_KEY"  # Replace with your actual Whale Alert API key

def fetch_whale_transactions(min_value_usd=500000, currency='usdt'):
    """
    Fetch recent whale transactions (default: USDT transfers over $500k).
    """
    try:
        params = {
            'api_key': WHALE_ALERT_API_KEY,
            'min_value': min_value_usd,
            'currency': currency,
            'limit': 100
        }
        response = requests.get(WHALE_ALERT_API_URL, params=params)
        if response.status_code == 200:
            return response.json().get('transactions', [])
        else:
            print(f"Whale Alert API error: {response.status_code}")
            return []
    except Exception as e:
        print(f"Exception in fetch_whale_transactions: {e}")
        return []