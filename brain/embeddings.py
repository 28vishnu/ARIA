import os
from google import genai

def get_embedding(text: str) -> list[float]:
    """Generates 768-dimensional semantic embeddings using Google Gemini."""
    key = os.getenv("GEMINI_API_KEY")
    if not key: 
        return [0.0] * 768
    try:
        client = genai.Client(api_key=key)
        res = client.models.embed_content(model="text-embedding-004", contents=text[:2000])
        return res.embedding.values
    except Exception as e:
        print(f"[Embedding Error]: {e}")
        return [0.0] * 768
