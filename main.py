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

# Modular Imports
from planner import action_planner
from tool_manager import ToolManager
from reasoner import reason
from conversation_manager import ConversationManager
from reflection_engine import ReflectionEngine
from brain import AriaBrain
from profile_engine import ProfileEngine
from workers import BackgroundWorkers

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
# MODULAR DETERMINISTIC HANDLERS
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
            return "Welcome back, Sir.\nARIA Neural Core online.\nAll systems operational.\nHow may I assist you today?"
        if lower.startswith("/help"):
            return "**ARIA Operating System Command Manual**:\n\n• Ask for live weather, news, or calculations.\n• Request documents ('Send my resume', 'What documents do you store?').\n• Manage tasks and schedules ('What is on my schedule today?')."
        if lower.startswith("/settings"):
            return "ARIA System Settings:\n• Interface: Telegram\n• Vector Store: ChromaDB Persistent\n• LLM Tier: Multi-Provider Failover Active, Sir."
        if lower.startswith("/about"):
            return "ARIA (Autonomous Responsive Intelligent Assistant) v3.5 AI Operating System, built for Saketh, Sir."
        if lower.startswith("/ping"):
            return "Pong! All systems optimal, Sir."
        return "Unknown command, Sir. Type /help for assistance."

class IdentityHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in ["who are you", "what are you", "your name"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        return "I am ARIA (Autonomous Responsive Intelligent Assistant), your dedicated AI operating system, built to manage your files, schedules, code, and intelligence feeds, Sir."

class ProfileHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in ["what do you know about me", "tell me about myself", "my profile", "who am i"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        profile = {}
        if app_state.profile_col is not None:
            profile = await app_state.profile_col.find_one({"_id": "master_profile"}) or {}
        
        media_cursor = None
        if app_state.media_col is not None:
            media_cursor = app_state.media_col.find({}, {"file_name": 1, "category": 1})
        stored_files = await media_cursor.to_list(length=20) if media_cursor is not None else []
        file_names = [f"• {f.get('file_name')} ({f.get('category', 'General')})" for f in stored_files]
        file_list_str = "\n".join(file_names) if file_names else "• No documents stored yet."

        name = profile.get("name", "Saketh")
        college = profile.get("college", "Gayatri Vidya Parishad College for Degree and PG Courses")
        course = profile.get("course", "B.Tech Computer Science Engineering")
        project = profile.get("active_project", {}).get("name", "ARIA AI")

        return (
            f"Here's what I currently know about you, Sir.\n\n"
            f"👤 **Name**\n• {name}\n\n"
            f"🎓 **Education**\n• {course}\n• {college}\n\n"
            f"🚀 **Active Project**\n• {project}\n\n"
            f"📂 **Stored Documents & Vault**\n{file_list_str}\n\n"
            f"If any of this is outdated, let me know and I'll update my knowledge, Sir."
        )

class BatchUploadHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        phrases = [
            "send all my documents", "upload my documents", "here are my files", 
            "i'll send my documents", "batch upload", "read these", "save these", 
            "store this", "remember these", "archive these", "index these files", "these are my"
        ]
        lower = text.lower()
        return any(p in lower for p in phrases)
    async def handle(self, text: str, session_id: str, app_state) -> str:
        return (
            "Certainly, Sir.\n\n"
            "Send your documents one by one or in batches. I'll automatically:\n"
            "• Read and extract their contents.\n"
            "• Index them for semantic vector search.\n"
            "• Detect and skip duplicate content.\n"
            "• Categorize them and store originals in your Media Vault.\n\n"
            "Standing by for your files, Sir."
        )

class GreetingHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        greetings = ["hi", "hello", "hey", "good morning", "good evening", "good afternoon", "greetings", "be10x"]
        lower = text.lower().strip()
        return lower in greetings or any(lower.startswith(g) for g in ["hi ", "hello ", "hey "])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        now_hour = datetime.now(timezone.utc).astimezone().hour
        time_greeting = "Good morning" if now_hour < 12 else ("Good afternoon" if now_hour < 17 else "Good evening")
        return f"{time_greeting}, Sir. ARIA online. What would you like to work on today?"

class TimeHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(k in lower for k in ["what time is it", "current time", "time now", "what's the time", "date today", "what day is it", "today's date", "today date"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        lower = text.lower()
        if "date" in lower or "day" in lower:
            return f"Today is {now_ist.strftime('%A, %B %d, %Y')}, Sir."
        return f"Current time is {now_ist.strftime('%I:%M:%S %p IST')}, Sir."

class LocationHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return "i'm in" in lower or "i am in" in lower or "my location is" in lower
    async def handle(self, text: str, session_id: str, app_state) -> str:
        location_name = re.sub(r".*?(i'm in|i am in|my location is)\s+", "", text.lower()).strip()
        if location_name and app_state.profile_col is not None:
            await app_state.profile_col.update_one(
                {"_id": "master_profile"},
                {"$set": {"location": location_name}},
                upsert=True
            )
            return f"Location locked as {location_name.title()}, Sir. Saved in profile for future local queries."
        return "Location update received, Sir."

class CalculatorHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return bool(re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', text)) and any(op in text for op in ['+', '-', '*', '/'])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = evaluate_math(text)
        if res is not None:
            return f"Result: {res}, Sir."
        return "Calculation error, Sir."

class WeatherHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        return "weather" in text.lower()
    async def handle(self, text: str, session_id: str, app_state) -> str:
        loc_query = "Visakhapatnam"
        if app_state.profile_col is not None:
            prof_doc = await app_state.profile_col.find_one({"_id": "master_profile"})
            if prof_doc and prof_doc.get("location"):
                loc_query = prof_doc.get("location")
        res = await app_state.tool_manager.execute_tool("web", f"current weather in {loc_query}", chat_id=session_id)
        return f"{res.get('content', 'Weather data unavailable.')}"

class ScheduleHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        # Excludes generic word 'today' to prevent conflict with TimeHandler
        return any(kw in text.lower() for kw in ["schedule", "task", "reminder", "agenda", "meeting"])
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = await app_state.tool_manager.execute_tool("schedule", text, chat_id=session_id)
        if res.get("success"):
            return f"{res.get('content')}, Sir."
        return "No scheduled tasks found, Sir."

class MediaHandler(BaseHandler):
    def can_handle(self, text: str) -> bool:
        keywords = ["resume", "cv", "portfolio", "pan", "passport", "certificate", "memo", "pdf", "document", "file", "download", "licence", "license", "id card", "my file", "send document", "what documents", "list files", "stored files", "search my files", "list media"]
        return any(k in text.lower() for k in keywords)
    async def handle(self, text: str, session_id: str, app_state) -> str:
        res = await app_state.tool_manager.execute_tool("media", text, chat_id=session_id)
        return f"{res.get('content')}"

# Corrected handler precedence (TimeHandler ordered strictly before ScheduleHandler)
DETERMINISTIC_ROUTER = [
    CommandHandler(),
    IdentityHandler(),
    ProfileHandler(),
    BatchUploadHandler(),
    GreetingHandler(),
    TimeHandler(),
    ScheduleHandler(),
    LocationHandler(),
    CalculatorHandler(),
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

PENDING_STATES = {}

# -------------------------------------------------------------
# STARTUP EVENT & RESILIENT INITIALIZATION
# -------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    print("[ARIA OS]: Initializing background intelligence workers and core state...")
    
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
        except Exception as e:
            print(f"[Startup Warning]: MongoDB connection degraded: {e}")
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
    except Exception as e:
        print(f"[Startup Warning]: ChromaDB initialization degraded: {e}")
        app.state.chroma_client = None
        app.state.docs_col = None
        app.state.mem_col = None

    app.state.brain = AriaBrain(app.state.chroma_client) if app.state.chroma_client else None
    app.state.profile_engine = ProfileEngine(db_inst) if db_inst is not None else None
    app.state.conversation_manager = ConversationManager(app.state.chats_col)
    app.state.reflection_engine = ReflectionEngine(app.state.chats_col, app.state.media_col)
    app.state.tool_manager = ToolManager(
        app.state.mem_col, 
        app.state.docs_col, 
        app.state.media_col, 
        app.state.schedule_col, 
        app.state.tavily
    )

    if app.state.profile_engine is not None:
        try:
            profile = await app.state.profile_engine.get_profile()
            print(f"[ARIA OS]: User Profile Loaded for: {profile.get('name', 'User')}")
        except Exception as e:
            print(f"[Profile Load Warning]: {e}")

    # Idempotent Knowledge Graph Seeding
    if app.state.brain is not None:
        try:
            app.state.brain.link_concepts("Saketh", "studies_at", "Gayatri Vidya Parishad College", category="education")
            app.state.brain.link_concepts("Saketh", "pursuing", "B.Tech Computer Science Engineering", category="education")
            app.state.brain.link_concepts("Saketh", "builds", "ARIA AI", category="projects")
            print("[ARIA OS]: Knowledge Graph successfully seeded with core entities.")
        except Exception as e:
            print(f"[Graph Seeding Warning]: {e}")

    if db_inst is not None:
        try:
            workers = BackgroundWorkers(db_inst, llm_router, app.state.tavily)
            scheduler.add_job(workers.morning_briefing_worker, "cron", hour=9, minute=0, id="morning_briefing", replace_existing=True)
            scheduler.add_job(workers.night_summary_worker, "cron", hour=22, minute=0, id="night_summary", replace_existing=True)
            scheduler.add_job(workers.inactivity_worker, "interval", days=1, id="inactivity", replace_existing=True)
            scheduler.add_job(workers.api_health_monitor_worker, "interval", hours=1, id="health_monitor", replace_existing=True)
            
            if not scheduler.running:
                scheduler.start()
                print("[ARIA OS]: Background Intelligence Workers active and running.")
        except Exception as e:
            print(f"[Worker Scheduler Warning]: {e}")

# -------------------------------------------------------------
# SHUTDOWN EVENT: SAFE RESOURCE CLEANUP
# -------------------------------------------------------------
@app.on_event("shutdown")
async def shutdown_event():
    print("[ARIA OS]: Shutting down systems and closing HTTP connections...")
    if hasattr(app.state, "http") and app.state.http:
        await app.state.http.aclose()
    if scheduler.running:
        scheduler.shutdown(wait=False)
    print("[ARIA OS]: Graceful shutdown complete.")

# -------------------------------------------------------------
# TASK PROCESSING PIPELINE
# -------------------------------------------------------------
async def process_task(user_text: str, session_id: str) -> str:
    print(f"[STAGE -1] Processing task for session {session_id}: '{user_text}'")

    # 1. Modular Deterministic Router Bypass
    for handler in DETERMINISTIC_ROUTER:
        if handler.can_handle(user_text):
            print(f"[DETERMINISTIC ROUTER]: Handled by {handler.__class__.__name__}")
            return await handler.handle(user_text, session_id, app.state)

    # =========================================================
    # STAGE 0 & ABOVE: REFLECTION, BRAIN, PLANNER, & REASONER
    # =========================================================
    tool_mgr = app.state.tool_manager
    chats_col = app.state.chats_col
    mem_col = app.state.mem_col
    aria_brain = app.state.brain
    conv_mgr = app.state.conversation_manager
    reflection_eng = app.state.reflection_engine

    correction = await reflection_eng.evaluate_feedback(user_text, session_id)
    if correction and correction.get("needs_retry"):
        res = await tool_mgr.execute_tool(correction["retry_tool"], user_text, chat_id=session_id)
        return f"{correction['explanation']}\n\n{res.get('content', '')}"

    if aria_brain is not None:
        cached_brain_hit = aria_brain.search_brain(user_text)
        if cached_brain_hit and cached_brain_hit["confidence"] > 0.92:
            return cached_brain_hit["answer"]

    print("[PLANNING STAGE]: Running single-pass action planner...")
    session_context = await conv_mgr.build_session_context(session_id)
    available_tools_desc = tool_mgr.describe_tools()

    executed_tools = []
    structured_results = {"memory": {}, "documents": {}, "web": {}, "media": {}, "schedule": {}}

    plan = await action_planner(user_text, session_context, available_tools_desc, executed_tools, llm_router)
    tools_to_run = plan.get("tools", [])
    action = plan.get("action", "retrieve")

    if action == "save" and any(w in user_text.lower() for w in ["remember", "my ", "i like"]):
        if mem_col is not None:
            mem_col.add(ids=[str(datetime.now().timestamp())], documents=[user_text])
        return "Information stored permanently in your vector vault, Sir."

    # Parallel Tool Execution via asyncio.gather()
    if tools_to_run:
        print(f"[PARALLEL TOOL EXECUTION]: Dispatching tools: {tools_to_run}")
        tasks = [tool_mgr.execute_tool(t_name, user_text, chat_id=session_id) for t_name in tools_to_run if t_name not in executed_tools]
        results = await asyncio.gather(*tasks)
        for t_name, result in zip(tools_to_run, results):
            structured_results[t_name] = result
            executed_tools.append(t_name)

    print("[REASONER STAGE]: Synthesizing response...")
    raw_answer = await reason(user_text, structured_results, llm_router, get_temporal(), available_tools_desc, session_context)
    cleaned = clean_text(raw_answer)

    has_valid_source = any(res.get("success") for res in structured_results.values())
    if has_valid_source and aria_brain is not None:
        aria_brain.store_knowledge(
            question=user_text,
            answer=cleaned,
            topic="general",
            category="general",
            summary=cleaned[:150],
            source="Verified Tool/AI",
            confidence=0.96,
            verified=True,
            knowledge_type="DYNAMIC"
        )

    if chats_col is not None:
        async def save_chat():
            try:
                await chats_col.insert_one({
                    "session_id": session_id,
                    "user_msg": user_text,
                    "aria_reply": cleaned,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            except Exception:
                pass
        asyncio.create_task(save_chat())

    return cleaned

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
    return JSONResponse(status_code=200, content={"status": "online", "core": "Polished Modular State-Optimized Core"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>ARIA Polished Autonomous Core Active</h1>"
