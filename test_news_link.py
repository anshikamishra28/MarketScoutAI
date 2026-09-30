import requests
from bs4 import BeautifulSoup


url = "https://news.google.com/rss/articles/CBMigAFBVV95cUxNeWE4NFptdnJEZzNDNUdYU3g0YV9RejlpaGtzLTdIV1hFbHFWU0J0QW11R1FCQzZTVV9mQzllVVZFV3pzRXpNS3hZb0pGMVNiT2tiVlczM251eW55a1hUd19QU28yOUowaE1qMmZWbnd1VFJnM2xPVDhoaFlrcFV2cQ?oc=5"

response = requests.get(
    url,
    headers={
        "User-Agent": "Mozilla/5.0"
    },
    timeout=10,
)

soup = BeautifulSoup(response.text, "html.parser")

print("PAGE TITLE:")
print(soup.title.get_text(strip=True) if soup.title else "No title")

print("\nLINKS CONTAINING HTTP:")
    
count = 0

for link in soup.find_all("a", href=True):
    href = link["href"]

    if href.startswith("http"):
        print(href)
        count += 1

    if count >= 20:
        break