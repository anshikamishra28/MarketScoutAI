import requests
from bs4 import BeautifulSoup

query = "India smartphone prices jump 16% in first half of 2026"

response = requests.get(
    "https://www.google.com/search",
    params={"q": query},
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=10,
)

print("STATUS:", response.status_code)

soup = BeautifulSoup(response.text, "html.parser")

for link in soup.select("a"):
    href = link.get("href", "")
    text = link.get_text(" ", strip=True)

    if "economictimes" in href.lower():
        print(text)
        print("->", href)