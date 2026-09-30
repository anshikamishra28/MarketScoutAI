from tools.web_search_direct import search_direct


results = search_direct(
    "Indian smartphone market under 30000 India Counterpoint",
    max_results=5,
)

for result in results:
    print("\nTITLE:", result["title"])
    print("URL:", result["url"])