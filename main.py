import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

app = FastAPI()

# -------------------------------------------------------------
# LLM PROVIDER ABSTRACTION LAYER (AUTOMATIC FALLBACK)
# -------------------------------------------------------------
class LLMProvider:
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        raise NotImplementedError

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str):
        from groq import Groq
        self.client = Groq(api_key=api_key) if api_key else None

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client: raise Exception("Groq unconfigured")
        def _exec():
            res = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return res.choices[0].message.content.strip()
        return await asyncio.to_thread(_exec)

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        from google import genai
        self.client = genai.Client(api_key=api_key) if api_key else None

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client: raise Exception("Gemini unconfigured")
        # Format messages into a single prompt string for Gemini Flash
        prompt_lines = [f"{m['role'].upper()}: {m['content']}" for m in messages]
        prompt_str = "\n".join(prompt_lines) + "\nARIA:"
        def _exec():
            res = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt_str
            )
            return res.text.strip()
        return await asyncio.to_thread(_exec)

class FallbackRouter(LLMProvider):
    def __init__(self):
        self.providers = [
            GroqProvider(os.getenv("GROQ_API_KEY")),
            GeminiProvider(os.getenv("GEMINI_API_KEY"))
        ]

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        for provider in self.providers:
            try:
                return await provider.chat(messages, temperature, max_tokens)
            except Exception as e:
                print(f"[Provider Fallback Triggered]: {e}")
                continue
        return "All neural pathways are temporarily offline, Sir. Please check API allowances."

llm_router = FallbackRouter()

# -------------------------------------------------------------
# CORE ASSISTANT LOGIC WITH INTENT BYPASS
# -------------------------------------------------------------
@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    token = os.getenv("TELEGRAM_TOKEN")
    if not token: return {"status": "no token"}
    
    try:
        data = await req.json()
        msg = data.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        if chat_id is None or not text: return {"status": "ok"}

        # Fast Intent Bypass for Simple Messages (Zero Token Usage)
        lower_txt = text.lower()
        if lower_txt in ["/start", "hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening"]:
            reply_text = "Online and fully operational, Sir. How may I assist you today?"
        else:
            # Complex Request: Pass through multi-provider fallback reasoner
            messages = [
                {"role": "system", "content": "You are ARIA, an advanced J.A.R.V.I.S.-style assistant. Address the user as Sir. Be precise and concise."},
                {"role": "user", "content": text}
            ]
            reply_text = await llm_router.chat(messages)

        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": reply_text}
            )
        return {"status": "ok"}
    except Exception as e:
        print(f"[Webhook Error]: {e}")
    return {"status": "ok"}

@app.head("/health")
@app.get("/health")
def health():
    return JSONResponse(status_code=200, content={"status": "online", "core": "Multi-Provider Fault-Tolerant Router"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>ARIA Multi-Provider Fallback Core Active</h1>"
