import os
import json
import httpx
import base64
import re
import asyncio
import certifi
import traceback
from datetime import datetime, timezone, timedelta
from io import BytesIO
from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pypdf import PdfReader
from docx import Document
import openpyxl
import edge_tts

# Modular Imports
from planner import action_planner
from tool_manager import ToolManager
from reasoner import reason
from conversation_manager import ConversationManager

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

class LLMProvider:
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        raise NotImplementedError

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key) if api_key else None

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if self.client is None: raise Exception("Groq unconfigured")
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
        if self.client is None: raise Exception("Gemini unconfigured")
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
        return db_inst["personal_memory"], db_inst["media_vault"], db_inst["chat_history"], db_inst["tasks_schedule"]
    return None, None, None, None

scheduler = AsyncIOScheduler()

def clean_text(raw: str) -> str:
    if raw is None: return ""
    return re.sub(r'\*+', '', raw).strip()

def get_temporal() -> str:
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    return f"LIVE TEMPORAL CONTEXT: {now_ist.strftime('%A, %B %d, %Y at %I:%M:%S %p IST')}"

async def process_task(user_text: str, session_id: str) -> str:
    print(f"[STAGE 0] Processing task for session {session_id}: '{user_text}'")
    lower_txt = user_text.lower()

    # 1. Fast Intent Bypass for Greetings & Simple Messages (Zero Token Usage)
    if lower_txt in ["/start", "hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening"]:
        return "Online and fully operational, Sir. How may I assist you today?"

    tavily = get_tavily()
    docs_col, mem_col = get_collections()
    mem_mongo, media_col, chats_col, schedule_col = get_mongo_collections()

    tool_mgr = ToolManager(mem_col, docs_col, media_col, schedule_col, tavily)

    # 2. Deterministic Intent Bypasses (Guaranteed Action execution even if AI Quotas are Exceeded)
    if any(kw in lower_txt for kw in ["resume", "cv", "pdf", "file", "document", "send"]):
        print("[INTENT BYPASS] Triggering Media Vault Tool directly.")
        res = await tool_mgr.execute_tool("media", user_text, chat_id=session_id)
        if res.get("success"):
            return res.get("content")

    if any(kw in lower_txt for kw in ["schedule", "task", "reminder", "today"]):
        print("[INTENT BYPASS] Triggering Schedule Tool directly.")
        res = await tool_mgr.execute_tool("schedule", user_text, chat_id=session_id)
        if res.get("success"):
            return res.get("content")

    conv_mgr = ConversationManager(chats_col)
    session_context = await conv_mgr.build_session_context(session_id)
    available_tools_desc = tool_mgr.describe_tools()

    executed_tools = []
    structured_results = {"memory": {}, "documents": {}, "web": {}, "media": {}, "schedule": {}}

    for i in range(3):  
        print(f"[STAGE 1] Running action planner (iteration {i+1})...")
        plan = await action_planner(user_text, session_context, available_tools_desc, executed_tools, llm_router)
        tools_to_run = plan.get("tools", [])
        action = plan.get("action", "retrieve")

        if action == "save" and any(w in lower_txt for w in ["remember", "my ", "i like"]):
            if mem_col is not None:
                await mem_col.add(ids=[str(datetime.now().timestamp())], documents=[user_text])
            return "Information stored permanently in your vector vault, Sir."

        if tools_to_run is None or len(tools_to_run) == 0:
            print("[STAGE 1] Planner completed tool selection.")
            break

        for t_name in tools_to_run:
            if t_name not in executed_tools:
                print(f"[STAGE 2] Executing tool: {t_name}")
                result = await tool_mgr.execute_tool(t_name, user_text, chat_id=session_id)
                structured_results[t_name] = result
                executed_tools.append(t_name)

    print("[STAGE 3] Invoking reasoner...")
    raw_answer = await reason(user_text, structured_results, llm_router, get_temporal(), available_tools_desc, session_context)
    cleaned = clean_text(raw_answer)

    # Fixed background task execution for MongoDB insert_one
    if chats_col is not None:
        async def save_chat():
            try:
                await chats_col.insert_one({
                    "session_id": session_id,
                    "user_msg": user_text,
                    "aria_reply": cleaned,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            except Exception as e:
                print(f"[DB Log Error]: {e}")
        asyncio.create_task(save_chat())

    return cleaned

@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    token = os.getenv("TELEGRAM_TOKEN")
    if token is None: return {"status": "no token"}
    try:
        data = await req.json()
        print(f"[WEBHOOK RECEIVED]: {data}")
        msg = data.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        if chat_id is None or not text: return {"status": "ok"}

        reply_text = await process_task(text, str(chat_id))

        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": reply_text}
            )
        print(f"[WEBHOOK REPLIED SUCCESSFULLY] to chat_id {chat_id}")
        return {"status": "ok"}
    except Exception:
        traceback.print_exc()
    return {"status": "ok"}

@app.head("/health")
@app.get("/health")
def health():
    return JSONResponse(status_code=200, content={"status": "online", "core": "Multi-Provider Fault-Tolerant Router"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>ARIA Multi-Provider Fault-Tolerant Core Active</h1>"
