import json

from services.llm_service import generate_response


def create_research_plan(research_question: str) -> dict:
    """
    Use Gemini to convert a research question
    into a structured research plan.
    """

    prompt = f"""
You are the research planning agent for MarketScoutAI.

Your job is to analyze the user's market research question
and create a structured research plan.

Research question:
{research_question}

Return ONLY valid JSON in this exact structure:

{{
    "research_goal": "string",
    "sub_questions": [
        "string"
    ],
    "information_needed": [
        "string"
    ],
    "search_queries": [
        "string"
    ]
}}

Rules:
- Create 3 to 6 sub-questions.
- Identify the specific information needed to answer them.
- Create useful web search queries.
- Keep the queries specific to the user's research question.
- Do not answer the research question yet.
- Return JSON only.
"""

    response = generate_response(prompt)

    try:
        return json.loads(response)

    except json.JSONDecodeError as error:
        raise ValueError(
            f"Gemini returned invalid JSON: {response}"
        ) from error