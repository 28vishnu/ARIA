import os
from google import genai

def get_embedding(text: str) -> list[float]:
    """Generates semantic embeddings using the current Gemini embedding model."""
    key = os.getenv("GEMINI_API_KEY")
    if not key: 
        return [0.0] * 768
    try:
        client = genai.Client(api_key=key)
        res = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text[:2000]
        )
        return res.embeddings[0].values
    except Exception as e:
        print(f"[Embedding Error - Falling back to zero-vector]: {e}")
        return [0.0] * 768
