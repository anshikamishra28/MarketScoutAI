from agents.research_planner import create_research_plan
from tools.web_search import search_web
from tools.web_fetcher import fetch_page


def execute_research(research_question: str) -> dict:
    """
    Create a research plan, search for sources,
    and fetch the discovered webpages.

    A research budget limits the number of sources
    to prevent uncontrolled scraping.
    """

    plan = create_research_plan(research_question)

    all_sources = []

    max_sources = 10
    source_count = 0

    for query in plan["search_queries"]:
        if source_count >= max_sources:
            break

        results = search_web(query, max_results=3)

        for result in results:
            if source_count >= max_sources:
                break

            result["search_query"] = query

            try:
                result["content"] = fetch_page(result["url"])

            except RuntimeError as error:
                result["content"] = ""
                result["fetch_error"] = str(error)

            all_sources.append(result)
            source_count += 1

    return {
        "research_question": research_question,
        "plan": plan,
        "sources": all_sources,
    }