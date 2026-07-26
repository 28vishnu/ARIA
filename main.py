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

# Lazy-loaded Globals
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_TELEGRAM_USER_ID = os.getenv("ALLOWED_TELEGRAM_USER_ID")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

USER_FULL_NAME = "N. Vishnu Saketh"
PENDING_SECURITY_ACTIONS = {}

_groq_client = None
_gemini_client = None
_tavily_client = None
_mongo_client = None
_chroma_client = None

def get_groq():
    global _groq_client
    if _groq_client is None and GROQ_API_KEY:
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client

def get_gemini():
    global _gemini_client
    if _gemini_client is None and GEMINI_API_KEY:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client

def get_tavily():
    global _tavily_client
    if _tavily_client is None and TAVILY_API_KEY:
        _tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
    return _tavily_client

def get_mongo():
    global _mongo_client
    if _mongo_client is None and MONGODB_URI:
        try:
            _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
                MONGODB_URI, tlsCAFile=certifi.where(), tlsInsecure=True, serverSelectionTimeoutMS=5000
            )
        except Exception:
            _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
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
    if not raw: return ""
    return re.sub(r'\*+', '', raw).strip()

def get_temporal() -> str:
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    return f"LIVE TEMPORAL CONTEXT: {now_ist.strftime('%A, %B %d, %Y at %I:%M:%S %p IST')}"

async def process_task(user_text: str, session_id: str) -> str:
    groq = get_groq()
    tavily = get_tavily()
    docs_col, mem_col = get_collections()
    _, _, chats_col = get_mongo_collections()

    conv_mgr = ConversationManager(chats_col)
    session_context = await conv_mgr.build_session_context(session_id)

    tool_mgr = ToolManager(mem_col, docs_col, tavily)
    available_tools_desc = tool_mgr.describe_tools()

    # --- ITERATIVE ACTION PLANNER LOOP ---
    executed_tools = []
    structured_results = {"memory": {}, "documents": {}, "web": {}}

    for _ in range(3):  # Max 3 planning iterations
        plan = await action_planner(user_text, session_context, available_tools_desc, executed_tools, groq)
        tools_to_run = plan.get("tools", [])
        action = plan.get("action", "retrieve")

        # Handle Action Types (e.g. save/delete/dispatch)
        if action == "save" and any(w in user_text.lower() for w in ["remember", "my ", "i like"]):
            await mem_col.add(ids=[str(datetime.now().timestamp())], documents=[user_text])
            return "Information stored permanently in your vector vault, Sir."

        if not tools_to_run:
            break

        for t_name in tools_to_run:
            if t_name not in executed_tools:
                result = await tool_mgr.execute_tool(t_name, user_text)
                structured_results[t_name] = result
                executed_tools.append(t_name)

    # --- STATEFUL REASONER ---
    raw_answer = await reason(user_text, structured_results, groq, get_temporal(), available_tools_desc, session_context)
    cleaned = clean_text(raw_answer)

    # Log interaction
    if chats_col is not None:
        asyncio.create_task(chats_col.insert_one({"session_id": session_id, "user_msg": user_text, "aria_reply": cleaned, "timestamp": datetime.now(timezone.utc).isoformat()}))

    return cleaned

@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    if not TELEGRAM_TOKEN: return {"status": "no token"}
    try:
        data = await req.json()
        msg = data.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        if not chat_id or not text: return {"status": "ok"}

        if text.lower() == "/start":
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "ARIA online, Sir."})
            return {"status": "ok"}

        ans = await process_task(text, str(chat_id))
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": ans})
        return {"status": "ok"}
    except Exception as e:
        print(f"[Webhook Error]: {e}")
    return {"status": "ok"}

@app.head("/health")
@app.get("/health")
def health():
    return JSONResponse(status_code=200, content={"status": "online"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>ARIA Stateful Agentic Core Active</h1>"
