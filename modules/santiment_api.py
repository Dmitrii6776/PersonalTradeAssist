import requests
import datetime

SANTIMENT_API_URL = "https://api.santiment.net/graphql"
SANTIMENT_API_KEY = "ms6qbmnwxnq6xtne_dx56zkd4toaz3xgz  # 🔥 Replace with your key

def fetch_social_metrics(symbol):
    """Fetch social dominance % change and active addresses % change for a given symbol."""
    try:
        now = datetime.datetime.utcnow()
        one_day_ago = now - datetime.timedelta(days=1)

        headers = {
            "Authorization": f"Apikey {SANTIMENT_API_KEY}"
        }

        query = """
        query socialDominanceAndAddresses($slug: String!, $from: DateTime!, $to: DateTime!) {
          socialDominance(
            slug: $slug
            from: $from
            to: $to
            interval: "6h"
          ) {
            datetime
            dominance
          }
          activeAddresses(
            slug: $slug
            from: $from
            to: $to
            interval: "6h"
          ) {
            datetime
            activeAddresses
          }
        }
        """

        variables = {
            "slug": symbol.lower(),
            "from": one_day_ago.isoformat() + "Z",
            "to": now.isoformat() + "Z"
        }

        response = requests.post(SANTIMENT_API_URL, json={"query": query, "variables": variables}, headers=headers)

        if response.status_code == 200:
            data = response.json().get('data', {})
            return data
        else:
            print(f"Error fetching Santiment social data: {response.status_code}")
            return None
    except Exception as e:
        print(f"Exception in fetch_social_metrics: {e}")
        return None
