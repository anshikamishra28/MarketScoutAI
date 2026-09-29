import os

from dotenv import load_dotenv
from google import genai


load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL")

if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY was not found.")

if not MODEL_NAME:
    raise RuntimeError("GEMINI_MODEL was not found.")


client = genai.Client(api_key=API_KEY)


def generate_response(prompt: str) -> str:
    """
    Send a prompt to Gemini and return the generated text.
    """

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )

    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")

    return response.text
from services.llm_service import generate_response


response = generate_response(
    "In one sentence, explain what a market intelligence agent does."
)

print(response)