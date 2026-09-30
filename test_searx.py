import requests


url = "https://search.bus-hit.me/search"

response = requests.get(
    url,
    params={
        "q": "Indian smartphone market under 30000",
        "format": "json",
    },
    headers={
        "User-Agent": "MarketScoutAI/0.1",
    },
    timeout=15,
)

print("STATUS:", response.status_code)
print("CONTENT TYPE:", response.headers.get("content-type"))

if response.ok:
    data = response.json()

    for result in data.get("results", [])[:5]:
        print("\nTITLE:", result.get("title"))
        print("URL:", result.get("url"))