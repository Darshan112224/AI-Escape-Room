"""
list_models.py — Print the Gemini models YOUR API key can use for text chat.

Run from the project root:
    python v1/list_models.py

Copy one of the printed names into GEMINI_MODEL in your .env file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise SystemExit("GEMINI_API_KEY is missing. Add it to .env first.")

client = genai.Client(api_key=api_key)

print("Models that support text generation (generateContent):\n")
for model in client.models.list():
    # Only chat/text models list "generateContent" as a supported action.
    if "generateContent" in (model.supported_actions or []):
        name = model.name.removeprefix("models/")
        if "flash" in name:  # Flash models are fast and usually on the free tier
            print(f"  ⭐ {name}")
        else:
            print(f"     {name}")
