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
# DYNAMIC MULTI-PROVIDER AI ROUTER WITH TEMPORARY COOLDOWN
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
            raise Exception("Groq temporarily rate-limited (cooldown active)")
        try:
            def _exec():
                res = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                return res.choices[0].message.content.strip()
            return await asyncio.to_thread(_exec)
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                self.rate_limited_until = datetime.now(timezone.utc) + timedelta(minutes=30)
                print(f"[Groq Rate Limit]: Cooldown engaged until {self.rate_limited_until}")
            raise e

class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        self.client_key = api_key
        self.http = http_client
        env_models = os.getenv("OPENROUTER_MODELS")
        if env_models:
            self.models = [m.strip() for m in env_models.split(",")]
        else:
            self.models = [
                "meta-llama/llama-3.3-70b-instruct:free",
                "mistralai/mistral-small-3.1-24b-instruct:free",
                "nvidia/nemotron-3-nano-30b-a3b:free"
            ]
        self.blacklisted_models = set()

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client_key: raise Exception("OpenRouter unconfigured")
        active_models = [m for m in self.models if m not in self.blacklisted_models]
        for model in active_models:
            try:
                res = await self.http.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.client_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                    timeout=15.0
                )
                data = res.json()
                if res.status_code == 404 or "No endpoints found" in str(data):
                    self.blacklisted_models.add(model)
                    continue
                if res.status_code in [429, 500, 503] or "error" in data or "choices" not in data:
                    continue
                res.raise_for_status()
                return data["choices"][0]["message"]["content"].strip()
            except Exception:
                continue
        raise Exception("All OpenRouter models failed or blacklisted")

class MistralProvider(LLMProvider):
    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        self.client_key = api_key
        self.http = http_client

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client_key: raise Exception("Mistral unconfigured")
        res = await self.http.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.client_key}", "Content-Type": "application/json"},
            json={"model": "mistral-small-latest", "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=15.0
        )
        data = res.json()
        res.raise_for_status()
        return data["choices"][0]["message"]["content"].strip()

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
    def __init__(self, http_client: httpx.AsyncClient):
        self.providers = [
            GroqProvider(os.getenv("GROQ_API_KEY")),
            OpenRouterProvider(os.getenv("OPENROUTER_API_KEY"), http_client),
            MistralProvider(os.getenv("MISTRAL_API_KEY"), http_client),
            GeminiProvider(os.getenv("GEMINI_API_KEY"))
        ]

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        for provider in self.providers:
            try:
                return await provider.chat(messages, temperature, max_tokens)
            except Exception as e:
                print(f"[Provider Fallback Triggered]: {e}")
                continue
        return "All neural pathways across Groq, OpenRouter, Mistral, and Gemini are currently exhausted, Sir."

# -------------------------------------------------------------
# MODULAR DETERMINISTIC & CONTEXTUAL HANDLERS
# -------------------------------------------------------------
class BaseHandler:
    def can_handle(self, text: str) -> bool:
        raise NotImplementedError
    async def handle(self, text: str, session_id: str, app_state) -> str:
        raise NotImplementedError

class CommandHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return text.startswith("/")
    async def handle(self, text: str, session_id: str, app_state) -> str:
        lower = text.lower()
        if lower.startswith("/start"):
            return "ARIA online. Systems operational."
        if lower.startswith("/help"):
            return "Commands: /start, /help, /settings, /about, /ping"
        if lower.startswith("/settings"):
            return "Interface: Telegram\nStore: ChromaDB\nTier: Multi-Provider Failover"
        if lower.startswith("/about"):
            return "ARIA v3.5 AI Operating System"
        if lower.startswith("/ping"):
            return "Pong."
        return "Unknown command."

class IdentityHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in ["who are you", "what are you", "your name"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        return "ARIA (Autonomous Responsive Intelligent Assistant)."

class ProfileHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in ["what do you know about me", "tell me about myself", "my profile", "who am i"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        profile = app_state.ram_cache.get("profile", {})
        name = profile.get("name", "Saketh")
        college = profile.get("college", "Gayatri Vidya Parishad College")
        course = profile.get("course", "B.Tech Computer Science Engineering")
        return f"Name: {name}\nEducation: {course}, {college}"

class GreetingHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        greetings = ["hi", "hello", "hey", "good morning", "good evening", "good afternoon", "greetings"]
        lower = text.lower().strip()
        return lower in greetings or any(lower.startswith(g) for g in ["hi ", "hello ", "hey "])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        return "ARIA online. Ready."

class TimeHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(k in lower for k in ["what time is it", "current time", "time now", "what's the time", "date today", "what day is it", "today's date", "today date"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        if "date" in text.lower() or "day" in text.lower():
            return f"Date: {now_ist.strftime('%A, %B %d, %Y')}"
        return f"Time: {now_ist.strftime('%I:%M:%S %p IST')}"

class CalculatorHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return bool(re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', text)) and any(op in text for op in ['+', '-', '*', '/'])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = evaluate_math(text)
        return f"Result: {res}" if res is not None else "Calculation error."

class WeatherHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return "weather" in text.lower()
    async def handle(self, text: str, session_id: str, app_state) -> str:
        loc = app_state.ram_cache.get("profile", {}).get("location", "Visakhapatnam")
        res = await app_state.tool_manager.execute_tool("web", f"current weather in {loc}", chat_id=session_id)
        return f"{res.get('content', 'Unavailable.')}"

class ScheduleHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return any(kw in text.lower() for kw in ["schedule", "task", "reminder", "agenda", "meeting"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = await app_state.tool_manager.execute_tool("schedule", text, chat_id=session_id)
        return f"{res.get('content', 'No schedule found.')}"

class MediaHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        keywords = ["resume", "cv", "portfolio", "pan", "passport", "certificate", "memo", "pdf", "document", "file", "download", "licence", "license", "id card", "my file", "send document", "what documents", "list files"]
        return any(k in text.lower() for k in keywords)
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = await app_state.tool_manager.execute_tool("media", text, chat_id=session_id)
        content = res.get('content', '')
        # Track last referenced document if a file match is found
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
        is_follow_up = any(k in lower for k in ["what's in it", "summarize it", "explain it", "read it", "what is inside"])
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
    CommandHandler(),
    IdentityHandler(),
    ProfileHandler(),
    GreetingHandler(),
    TimeHandler(),
    ScheduleHandler(),
    WeatherHandler(),
    MediaHandler()
]

# Single application instance
app = FastAPI()
scheduler = AsyncIOScheduler()

def clean_text(raw: str) -> str:
    if raw is None: return ""
    return re.sub(r'\*+', '', raw).strip()

def get_temporal() -> str:
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    return f"LIVE TEMPORAL CONTEXT: {now_ist.strftime('%A, %B %d, %Y at %I:%M:%S %p IST')}"

# -------------------------------------------------------------
# STARTUP EVENT & WARM-UP OPTIMIZATIONS
# -------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    print("[ARIA OS]: Initializing kernel state...")
    
    app.state.http = httpx.AsyncClient(timeout=15.0)
    global llm_router
    llm_router = FallbackRouter(app.state.http)

    tavily_key = os.getenv("TAVILY_API_KEY")
    app.state.tavily = TavilyClient(api_key=tavily_key) if tavily_key else None
    
    mongo_uri = os.getenv("MONGODB_URI")
    if mongo_uri:
        try:
            app.state.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
                mongo_uri, tlsCAFile=certifi.where(), tlsInsecure=True, serverSelectionTimeoutMS=5000
            )
        except Exception:
            app.state.mongo_client = None
    else:
        app.state.mongo_client = None

    db_inst = app.state.mongo_client["aria_db"] if app.state.mongo_client is not None else None

    app.state.mem_mongo = db_inst["personal_memory"] if db_inst is not None else None
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
        
        warm_col = app.state.chroma_client.get_or_create_collection(name="warmup_collection")
        warm_col.upsert(ids=["1"], documents=["warmup embedding text"])
        warm_col.query(query_texts=["warmup"], n_results=1)
    except Exception:
        app.state.chroma_client = None

    app.state.ram_cache = {"profile": {}}
    if db_inst is not None:
        try:
            prof_doc = await db_inst["user_profile"].find_one({"_id": "master_profile"})
            if prof_doc:
                app.state.ram_cache["profile"] = prof_doc
        except Exception:
            pass

    if app.state.chroma_client:
        app.state.brain = AriaBrain(chroma_client=app.state.chroma_client, mongo_db=db_inst)
    else:
        app.state.brain = None

    app.state.profile_engine = ProfileEngine(db_inst) if db_inst is not None else None
    app.state.memory_engine = MemoryEngine(db_inst) if db_inst is not None else None
    app.state.personality_engine = PersonalityEngine(app.state.memory_engine)
    app.state.conversation_manager = ConversationManager(app.state.chats_col)
    app.state.reflection_engine = ReflectionEngine(app.state.chats_col, app.state.media_col)
    app.state.tool_manager = ToolManager(
        app.state.mem_col, app.state.docs_col, app.state.media_col, 
        app.state.schedule_col, app.state.tavily, aria_brain=app.state.brain
    )

    if app.state.brain is not None:
        try:
            await app.state.brain.graph.link("Saketh", "studies_at", "Gayatri Vidya Parishad College")
            await app.state.brain.graph.link("Saketh", "pursuing", "B.Tech Computer Science Engineering")
        except Exception:
            pass

    if db_inst is not None:
        try:
            workers = BackgroundWorkers(db_inst, llm_router, app.state.tavily)
            scheduler.add_job(workers.morning_briefing_worker, "cron", hour=9, minute=0, id="morning_briefing", replace_existing=True)
            scheduler.add_job(workers.night_summary_worker, "cron", hour=22, minute=0, id="night_summary", replace_existing=True)
            if not scheduler.running:
                scheduler.start()
        except Exception:
            pass

@app.on_event("shutdown")
async def shutdown_event():
    if hasattr(app.state, "http") and app.state.http:
        await app.state.http.aclose()
    if scheduler.running:
        scheduler.shutdown(wait=False)

# -------------------------------------------------------------
# TASK PROCESSING PIPELINE
# -------------------------------------------------------------
async def process_task(user_text: str, session_id: str) -> str:
    memory_eng = app.state.memory_engine
    persona_eng = app.state.personality_engine
    conv_mgr = app.state.conversation_manager
    brain = app.state.brain
    lower_text = user_text.lower().strip()

    if memory_eng is not None:
        asyncio.create_task(memory_eng.extract_and_store_facts(user_text))

    session_context = await conv_mgr.build_session_context(session_id)

    # 1. Fast Path: Contextual Follow-up Document Router
    doc_handler = ContextualDocumentHandler()
    if doc_handler.can_handle(user_text, session_context):
        raw_reply = await doc_handler.handle(user_text, session_id, app.state, session_context)
        return await persona_eng.apply_persona(raw_reply)

    # 2. Fast Path: RAM Profile Lookup
    if any(k in lower_text for k in ["what's my name", "who am i", "my profile"]):
        profile = app.state.ram_cache.get("profile", {})
        name = profile.get("name", "Saketh")
        return await persona_eng.apply_persona(f"You are {name}.")

    # 3. Fast Path: Deterministic Handlers
    for handler in DETERMINISTIC_ROUTER:
        if handler.can_handle(user_text):
            raw_reply = await handler.handle(user_text, session_id, app.state)
            is_greeting = isinstance(handler, GreetingHandler)
            return await persona_eng.apply_persona(raw_reply, is_major_event=is_greeting)

    # 4. Fast Path: Brain Kernel Search Cache & Metadata
    if brain is not None:
        req = BrainRequest(query=user_text, session_id=session_id, intent="search")
        brain_hit = await brain.search(req)
        if brain_hit and brain_hit.get("source") == "cache":
            return await persona_eng.apply_persona(brain_hit["content"])
        elif brain_hit and brain_hit.get("documents") and len(brain_hit["documents"]) > 0:
            docs = brain_hit["documents"]
            doc_list = "\n".join([f"• **{d.get('title')}** (`{d.get('filename')}`)" for d in docs])
            if len(docs) == 1:
                app.state.conversation_manager.set_last_document(session_id, docs[0].get('filename'))
            return await persona_eng.apply_persona(f"Located.\n{doc_list}")

    # 5. Heavy Fallback: Planner & Reasoner Pipeline
    tool_mgr = app.state.tool_manager
    chats_col = app.state.chats_col
    reflection_eng = app.state.reflection_engine

    correction = await reflection_eng.evaluate_feedback(user_text, session_id)
    if correction and correction.get("needs_retry"):
        res = await tool_mgr.execute_tool(correction["retry_tool"], user_text, chat_id=session_id)
        return await persona_eng.apply_persona(f"{correction['explanation']}\n\n{res.get('content', '')}")

    available_tools_desc = tool_mgr.describe_tools()
    executed_tools = []
    structured_results = {"memory": {}, "documents": {}, "web": {}, "media": {}, "schedule": {}}

    plan = await action_planner(user_text, session_context, available_tools_desc, executed_tools, llm_router)
    tools_to_run = plan.get("tools", [])

    if tools_to_run:
        tasks = [tool_mgr.execute_tool(t_name, user_text, chat_id=session_id) for t_name in tools_to_run if t_name not in executed_tools]
        results = await asyncio.gather(*tasks)
        for t_name, result in zip(tools_to_run, results):
            structured_results[t_name] = result

    raw_answer = await reason(user_text, structured_results, llm_router, get_temporal(), available_tools_desc, session_context)
    cleaned = clean_text(raw_answer)

    if chats_col is not None:
        async def save_chat():
            try:
                await chats_col.insert_one({
                    "session_id": session_id, "user_msg": user_text, "aria_reply": cleaned,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            except Exception:
                pass
        asyncio.create_task(save_chat())

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

@app.head("/health")
@app.get("/health")
def health():
    return JSONResponse(status_code=200, content={"status": "online", "core": "JARVIS Kernel Active"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>ARIA Kernel Active</h1>"
