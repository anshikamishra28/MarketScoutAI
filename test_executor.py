from agents.research_executor import execute_research


question = "Analyze the Indian smartphone market under ₹30,000."

research = execute_research(question)

print("\nRESEARCH QUESTION\n")
print(research["research_question"])

print("\nSEARCH QUERIES\n")

for query in research["plan"]["search_queries"]:
    print("-", query)

print("\nSOURCES FOUND\n")

for source in research["sources"]:
    print(source["title"])
    print(source["url"])
    print()