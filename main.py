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

# Scheduler SDKs
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
# MULTI-PROVIDER AI ROUTER
# -------------------------------------------------------------
class LLMProvider:
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        raise NotImplementedError

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key) if api_key else None
        self.rate_limited_until = None

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if self.client is None: raise Exception("Groq unconfigured")
        if self.rate_limited_until and datetime.now(timezone.utc) < self.rate_limited_until:
            raise Exception("Groq rate-limited")
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
# DETERMINISTIC & CORRECTION HANDLERS
# -------------------------------------------------------------
class BaseHandler:
    def can_handle(self, text: str) -> bool:
        raise NotImplementedError
    async def handle(self, text: str, session_id: str, app_state) -> str:
        raise NotImplementedError

class CorrectionHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(p in lower for p in ["that's wrong", "incorrect", "no, it's", "wrong answer", "the correct is"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        conv_mgr = app_state.conversation_manager
        ctx = await conv_mgr.build_session_context(session_id)
        history = ctx.get("history", [])
        last_query = history[-2]["content"] if len(history) >= 2 else "previous query"
        wrong_ans = history[-1]["content"] if history else ""

        if app_state.brain is not None:
            await app_state.brain.record_feedback(last_query, wrong_ans, text)
        return "Correction recorded. Stored permanently."

class GreetingHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        greetings = ["hi", "hello", "hey", "good morning", "greetings"]
        lower = text.lower().strip()
        return lower in greetings or any(lower.startswith(g) for g in ["hi ", "hello "])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        return "ARIA online. Ready."

class TimeHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in ["what time", "current time", "date today", "today's date"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        if "date" in text.lower():
            return f"Date: {now_ist.strftime('%A, %B %d, %Y')}"
        return f"Time: {now_ist.strftime('%I:%M:%S %p IST')}"

class MediaHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        keywords = ["resume", "cv", "portfolio", "pdf", "document", "file", "list files", "italy"]
        return any(k in text.lower() for k in keywords)
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = await app_state.tool_manager.execute_tool("media", text, chat_id=session_id)
        content = res.get('content', '')
        if "• **" in content:
            match = re.search(r'• \*\*([^*]+)\*\*', content)
            if match:
                doc_name = match.group(1).strip()
                app_state.conversation_manager.set_last_document(session_id, doc_name)
        return content

class ContextualDocumentHandler:
    def can_handle(self, text: str, session_context: dict) -> bool:
        lower = text.lower()
        has_doc_in_context = bool(session_context.get("last_referenced_document"))
        is_follow_up = any(k in lower for k in ["what's in it", "summarize it", "explain it", "read it"])
        return has_doc_in_context and is_follow_up

    async def handle(self, text: str, session_id: str, app_state, session_context: dict) -> str:
        doc_name = session_context["last_referenced_document"]
        req = BrainRequest(query=doc_name, session_id=session_id, intent="document_search")
        brain_hit = await app_state.brain.search(req)
        
        if brain_hit and brain_hit.get("documents"):
            docs = brain_hit["documents"]
            summaries = "\n".join([f"• {d.get('summary', 'No summary available.')}" for d in docs])
            return f"Located.\n{doc_name}\n\nSummary:\n{summaries}"
        
        return f"Located file `{doc_name}`, but content chunks were unavailable."

DETERMINISTIC_ROUTER = [
    CorrectionHandler(),
    GreetingHandler(),
    TimeHandler(),
    MediaHandler()
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

    tavily_key = os.getenv("TAVILY_API_KEY")
    app.state.tavily = TavilyClient(api_key=tavily_key) if tavily_key else None
    
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
    app.state.profile_engine = ProfileEngine(db_inst) if db_inst is not None else None
    app.state.memory_engine = MemoryEngine(db_inst) if db_inst is not None else None
    app.state.personality_engine = PersonalityEngine(app.state.memory_engine)
    app.state.conversation_manager = ConversationManager(app.state.chats_col)
    app.state.reflection_engine = ReflectionEngine(app.state.chats_col, app.state.media_col)
    app.state.tool_manager = ToolManager(
        app.state.mem_col, app.state.docs_col, app.state.media_col, 
        app.state.schedule_col, app.state.tavily, aria_brain=app.state.brain
    )

@app.on_event("shutdown")
async def shutdown_event():
    if hasattr(app.state, "http") and app.state.http:
        await app.state.http.aclose()

# -------------------------------------------------------------
# STRICT CONFIDENCE-GATED PROCESSING PIPELINE
# -------------------------------------------------------------
async def process_task(user_text: str, session_id: str) -> str:
    memory_eng = app.state.memory_engine
    persona_eng = app.state.personality_engine
    conv_mgr = app.state.conversation_manager
    brain = app.state.brain

    if memory_eng is not None:
        asyncio.create_task(memory_eng.extract_and_store_facts(user_text))

    session_context = await conv_mgr.build_session_context(session_id)

    # 1. Contextual Follow-up Router
    doc_handler = ContextualDocumentHandler()
    if doc_handler.can_handle(user_text, session_context):
        raw_reply = await doc_handler.handle(user_text, session_id, app.state, session_context)
        return await persona_eng.apply_persona(raw_reply)

    # 2. Deterministic Handlers (Corrections, Greetings, Time)
    for handler in DETERMINISTIC_ROUTER:
        if handler.can_handle(user_text):
            raw_reply = await handler.handle(user_text, session_id, app.state)
            return await persona_eng.apply_persona(raw_reply)

    # 3. Brain Kernel Gatekeeper (Data-First Retrieval with Confidence Scoring)
    if brain is not None:
        req = BrainRequest(query=user_text, session_id=session_id, intent="search")
        brain_res = await brain.search(req)
        
        confidence = brain_res.get("confidence", 0.0)
        
        # High Confidence Gates: Return data directly without invoking LLM
        if confidence >= 0.90:
            if brain_res.get("source") in ["profile", "learning_engine"]:
                if "profile" in brain_res:
                    p = brain_res["profile"]
                    return await persona_eng.apply_persona(f"Name: {p.get('name', 'Saketh')}\nEducation: {p.get('course', 'B.Tech')}, {p.get('college', 'GVP')}")
                return await persona_eng.apply_persona(brain_res["content"])
            
            elif brain_res.get("documents"):
                docs = brain_res["documents"]
                doc_list = "\n".join([f"• **{d.get('title')}** (`{d.get('filename')}`)" for d in docs])
                if len(docs) == 1:
                    app.state.conversation_manager.set_last_document(session_id, docs[0].get('filename'))
                return await persona_eng.apply_persona(f"Located.\n{doc_list}")

    # 4. Low Confidence Fallback: LLM Reasoner (Only when data is absent)
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
    return JSONResponse(status_code=200, content={"status": "online", "core": "Behavioral Core Active"})
