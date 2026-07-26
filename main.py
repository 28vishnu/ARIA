import os
import json
import httpx
import base64
import re
import asyncio
import certifi
from datetime import datetime, timezone, timedelta
from io import BytesIO
from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pypdf import PdfReader
from docx import Document
import openpyxl
import edge_tts

# Provider SDKs
from groq import Groq
from google import genai
from google.genai import types
from tavily import TavilyClient
import motor.motor_asyncio
import chromadb

# Scheduler SDKs
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

app = FastAPI()

# -------------------------------------------------------------
# 1. LLM PROVIDER ABSTRACTION LAYER (AUTOMATIC FALLBACK)
# -------------------------------------------------------------
class LLMProvider:
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        raise NotImplementedError

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str):
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
        self.client = genai.Client(api_key=api_key) if api_key else None

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client: raise Exception("Gemini unconfigured")
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
# 2. LAZY-LOADED DATABASE & CLIENTS INITIALIZATION
# -------------------------------------------------------------
USER_FULL_NAME = "N. Vishnu Saketh"
_tavily_client = None
_mongo_client = None
_chroma_client = None

def get_tavily():
    global _tavily_client
    key = os.getenv("TAVILY_API_KEY")
    if _tavily_client is None and key is not None:
        _tavily_client = TavilyClient(api_key=key)
    return _tavily_client

def get_mongo():
    global _mongo_client
    uri = os.getenv("MONGODB_URI")
    if _mongo_client is None and uri is not None:
        try:
            _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
                uri, tlsCAFile=certifi.where(), tlsInsecure=True, serverSelectionTimeoutMS=5000
            )
        except Exception:
            _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(uri)
    return _mongo_client

def get_chroma():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path="./aria_vectors")
    return _chroma_client

def get_collections():
    client = get_chroma()
    return client.get_or_create_collection(name="documents"), client.get_or_create_collection(name="memory")

def get_mongo_collections():
    db = get_mongo()
    if db is not None:
        db_inst = db["aria_db"]
        return db_inst["personal_memory"], db_inst["media_vault"], db_inst["chat_history"]
    return None, None, None

scheduler = AsyncIOScheduler()

def clean_text(raw: str) -> str:
    if raw is None: return ""
    return re.sub(r'\*+', '', raw).strip()

def get_temporal() -> str:
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    return f"LIVE TEMPORAL CONTEXT: {now_ist.strftime('%A, %B %d, %Y at %I:%M:%S %p IST')}"

# -------------------------------------------------------------
# 3. CORE ASSISTANT LOGIC WITH INTENT BYPASS & FALLBACK ROUTER
# -------------------------------------------------------------
async def process_autonomous_task(user_text: str, session_id: str) -> str:
    lower_txt = user_text.lower()

    # Fast Intent Bypass for Simple Messages (Zero Token Usage)
    if lower_txt in ["/start", "hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening"]:
        return "Online and fully operational, Sir. How may I assist you today?"

    # Assemble System Prompt & Context
    system_prompt = f"""You are ARIA, an advanced J.A.R.V.I.S.-style assistant.
{get_temporal()}
CRITICAL DIRECTIVES:
1. STRICT REDACTION: Never output, echo, or print raw numeric digits of Aadhaar, RRN, or MyNumber under any circumstances.
2. Address the user as Sir. Be precise and concise."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text}
    ]

    # Route through multi-provider fallback router (Groq -> Gemini Flash)
    reply_text = await llm_router.chat(messages)
    cleaned = clean_text(reply_text)

    # Log interaction to MongoDB
    _, _, chats_col = get_mongo_collections()
    if chats_col is not None:
        asyncio.create_task(chats_col.insert_one({
            "session_id": session_id,
            "user_msg": user_text,
            "aria_reply": cleaned,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }))

    return cleaned

# -------------------------------------------------------------
# 4. TELEGRAM WEBHOOK & ENDPOINTS
# -------------------------------------------------------------
@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    token = os.getenv("TELEGRAM_TOKEN")
    if token is None: return {"status": "no token"}
    
    try:
        data = await req.json()
        msg = data.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        if chat_id is None or not text: return {"status": "ok"}

        reply_text = await process_autonomous_task(text, str(chat_id))

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
