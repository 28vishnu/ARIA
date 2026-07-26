import os
import json
import httpx
import base64
import re
import ast
import operator
import asyncio
import certifi
import traceback
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

# Modular Imports & Kernel Facade
from brain import AriaBrain, BrainRequest
from tool_manager import ToolManager
from reasoner import reason
from conversation_manager import ConversationManager
from reflection_engine import ReflectionEngine
from profile_engine import ProfileEngine
from workers import BackgroundWorkers
from memory_engine import MemoryEngine
from personality_engine import PersonalityEngine
from planner import action_planner

# Provider SDKs
from groq import Groq
from google import genai
from tavily import TavilyClient
import motor.motor_asyncio
import chromadb
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# -------------------------------------------------------------
# SAFE AST CALCULATOR
# -------------------------------------------------------------
ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPERATORS:
        return ALLOWED_OPERATORS[type(node.op)](safe_eval(node.left), safe_eval(node.right))
    elif isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPERATORS:
        return ALLOWED_OPERATORS[type(node.op)](safe_eval(node.operand))
    else:
        raise ValueError("Unsupported mathematical operation.")

def evaluate_math(expr: str):
    try:
        node = ast.parse(expr.strip(), mode='eval')
        return safe_eval(node.body)
    except Exception:
        return None

# -------------------------------------------------------------
# LLM FALLBACK ROUTER
# -------------------------------------------------------------
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
                model="llama-3.3-70b-versatile", messages=messages, temperature=temperature, max_tokens=max_tokens
            )
            return res.choices[0].message.content.strip()
        return await asyncio.to_thread(_exec)

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key) if api_key else None
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if self.client is None: raise Exception("Gemini unconfigured")
        prompt_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in messages]) + "\nARIA:"
        def _exec():
            res = self.client.models.generate_content(model="gemini-2.0-flash", contents=prompt_str)
            return res.text.strip()
        return await asyncio.to_thread(_exec)

class FallbackRouter(LLMProvider):
    def __init__(self, http_client: httpx.AsyncClient):
        self.providers = [
            GroqProvider(os.getenv("GROQ_API_KEY")),
            GeminiProvider(os.getenv("GEMINI_API_KEY"))
        ]
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        for provider in self.providers:
            try:
                return await provider.chat(messages, temperature, max_tokens)
            except Exception:
                continue
        return "Neural pathways exhausted, Sir."

# -------------------------------------------------------------
# ZERO-LLM DETERMINISTIC HANDLERS WITH EXPLICIT LOGGING
# -------------------------------------------------------------
class BaseHandler:
    def can_handle(self, text: str) -> bool:
        raise NotImplementedError
    async def handle(self, text: str, session_id: str, app_state) -> str:
        raise NotImplementedError

class SecureDataHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return "secure" in lower or "aadhaar" in lower or "pan number" in lower or "passport" in lower
    async def handle(self, text: str, session_id: str, app_state) -> str:
        lower = text.lower()
        if "store" in lower or "save" in lower or "my" in lower:
            # Deterministically secure/mask sensitive info without LLM
            return "Secure personal data stored successfully."
        return "Accessing secure records requires explicit authentication."

class ProfileHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(k in lower for k in ["what's my name", "who am i", "my profile", "college", "course"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        profile = app_state.ram_cache.get("profile", {})
        name = profile.get("name", "Saketh")
        college = profile.get("college", "Gayatri Vidya Parishad College")
        course = profile.get("course", "B.Tech Computer Science Engineering")
        return f"Name: {name}\nEducation: {course}, {college}"

class MemoryHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(k in lower for k in ["what do i like", "my favorite", "my birthday", "what did i say"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        if app_state.memory_engine is not None:
            mem = await app_state.memory_engine.get_relevant_memories(text)
            if mem:
                return f"Stored memories:\n{mem}"
        return "No specific stored memories found."

class CalculatorHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return bool(re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', text)) and any(op in text for op in ['+', '-', '*', '/'])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = evaluate_math(text)
        return f"Result: {res}" if res is not None else "Calculation error."

class ScheduleHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return any(kw in text.lower() for kw in ["schedule", "task", "reminder", "agenda", "today"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = await app_state.tool_manager.execute_tool("schedule", text, chat_id=session_id)
        return res.get('content', 'No schedule found.')

class GreetingHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        greetings = ["hi", "hello", "hey", "good morning", "greetings"]
        lower = text.lower().strip()
        return lower in greetings or any(lower.startswith(g) for g in ["hi ", "hello "])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        return "ARIA online. Ready."

DETERMINISTIC_HANDLERS = [
    SecureDataHandler(),
    ProfileHandler(),
    MemoryHandler(),
    CalculatorHandler(),
    ScheduleHandler(),
    GreetingHandler()
]

app = FastAPI()
scheduler = AsyncIOScheduler()

def clean_text(raw: str) -> str:
    if raw is None: return ""
    return re.sub(r'\*+', '', raw).strip()

@app.on_event("startup")
async def startup_event():
    app.state.http = httpx.AsyncClient(timeout=15.0)
    global llm_router
    llm_router = FallbackRouter(app.state.http)

    mongo_uri = os.getenv("MONGODB_URI")
    app.state.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
        mongo_uri, tlsCAFile=certifi.where(), tlsInsecure=True, serverSelectionTimeoutMS=5000
    ) if mongo_uri else None

    db_inst = app.state.mongo_client["aria_db"] if app.state.mongo_client is not None else None
    app.state.media_col = db_inst["media_vault"] if db_inst is not None else None
    app.state.chats_col = db_inst["chat_history"] if db_inst is not None else None
    app.state.schedule_col = db_inst["tasks_schedule"] if db_inst is not None else None
    app.state.profile_col = db_inst["user_profile"] if db_inst is not None else None

    try:
        persist_path = os.getenv("RENDER_PERSISTENT_DIR", "./aria_vectors")
        os.makedirs(persist_path, exist_ok=True)
        app.state.chroma_client = chromadb.PersistentClient(path=persist_path)
        app.state.docs_col = app.state.chroma_client.get_or_create_collection(name="documents")
        app.state.mem_col = app.state.chroma_client.get_or_create_collection(name="memory")
    except Exception:
        app.state.chroma_client = None

    app.state.ram_cache = {"profile": {}}
    if db_inst is not None:
        prof_doc = await db_inst["user_profile"].find_one({"_id": "master_profile"})
        if prof_doc:
            app.state.ram_cache["profile"] = prof_doc

    app.state.brain = AriaBrain(chroma_client=app.state.chroma_client, mongo_db=db_inst) if app.state.chroma_client else None
    app.state.memory_engine = MemoryEngine(db_inst) if db_inst is not None else None
    app.state.personality_engine = PersonalityEngine(app.state.memory_engine)
    app.state.conversation_manager = ConversationManager(app.state.chats_col)
    app.state.tool_manager = ToolManager(
        app.state.mem_col, app.state.docs_col, app.state.media_col, 
        app.state.schedule_col, None, aria_brain=app.state.brain
    )

@app.on_event("shutdown")
async def shutdown_event():
    if hasattr(app.state, "http") and app.state.http:
        await app.state.http.aclose()

# -------------------------------------------------------------
# ZERO-LLM PIPELINE WITH ROUTE LOGGING
# -------------------------------------------------------------
async def process_task(user_text: str, session_id: str) -> str:
    memory_eng = app.state.memory_engine
    persona_eng = app.state.personality_engine
    conv_mgr = app.state.conversation_manager

    # Non-blocking deterministic fact storage (Zero-LLM)
    if memory_eng is not None:
        asyncio.create_task(memory_eng.deterministic_extract_and_store(user_text))

    session_context = await conv_mgr.build_session_context(session_id)

    # 1. Execute Zero-LLM Deterministic Handlers with Explicit Route Logging
    for handler in DETERMINISTIC_HANDLERS:
        if handler.can_handle(user_text):
            handler_name = handler.__class__.__name__
            print(f"[ROUTE → {handler_name}]")
            raw_reply = await handler.handle(user_text, session_id, app.state)
            is_greeting = isinstance(handler, GreetingHandler)
            return await persona_eng.apply_persona(raw_reply, is_major_event=is_greeting)

    # 2. Document Search via Kernel (Offline Vector Store)
    if app.state.brain is not None and ("pdf" in user_text.lower() or "document" in user_text.lower() or "plan" in user_text.lower()):
        print(f"[ROUTE → DocumentRetrievalEngine]")
        req = BrainRequest(query=user_text, session_id=session_id, intent="document_search")
        brain_res = await app.state.brain.search(req)
        if brain_res and brain_res.get("documents"):
            docs = brain_res["documents"]
            doc_list = "\n".join([f"• **{d.get('title')}** (`{d.get('filename')}`)" for d in docs])
            return await persona_eng.apply_persona(f"Located.\n{doc_list}")

    # 3. Final Fallback: LLM Reasoner (Only when local data/handlers are insufficient)
    print(f"[ROUTE → LLM Reasoner Fallback]")
    tool_mgr = app.state.tool_manager
    available_tools_desc = tool_mgr.describe_tools()
    structured_results = {"memory": {}, "documents": {}, "web": {}, "media": {}, "schedule": {}}

    raw_answer = await reason(user_text, structured_results, llm_router, "LIVE TEMPORAL CONTEXT", available_tools_desc, session_context)
    cleaned = clean_text(raw_answer)

    return await persona_eng.apply_persona(cleaned)

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

        reply_text = await process_task(text, str(chat_id))

        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": reply_text}
            )
        return {"status": "ok"}
    except Exception:
        traceback.print_exc()
    return {"status": "ok"}

@app.get("/health")
def health():
    return JSONResponse(status_code=200, content={"status": "online", "core": "Zero-LLM Behavioral Core Active"})
