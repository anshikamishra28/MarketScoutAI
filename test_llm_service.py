from services.llm_service import generate_response


response = generate_response(
    "In one sentence, explain what a market intelligence agent does."
)

print(response)