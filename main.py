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

app = FastAPI()

# -------------------------------------------------------------
# SAFE AST CALCULATOR (Replaces unsafe eval)
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
# DYNAMIC MULTI-PROVIDER AI ROUTER WITH RATE-LIMIT BLACKLISTING
# -------------------------------------------------------------
class LLMProvider:
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        raise NotImplementedError

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key) if api_key else None
        self.is_rate_limited = False

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if self.client is None or self.is_rate_limited: raise Exception("Groq unconfigured or rate-limited")
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
                print("[Groq Rate Limit Triggered]: Blacklisting Groq temporarily.")
                self.is_rate_limited = True
            raise e

class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client_key = api_key
        self.models = [
            "meta-llama/llama-3.3-70b-instruct:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "nvidia/nemotron-3-nano-30b-a3b:free"
        ]
        self.blacklisted_models = set()

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client_key: raise Exception("OpenRouter unconfigured")
        async with httpx.AsyncClient() as client:
            active_models = [m for m in self.models if m not in self.blacklisted_models]
            for model in active_models:
                try:
                    res = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self.client_key}", "Content-Type": "application/json"},
                        json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                        timeout=15.0
                    )
                    data = res.json()
                    
                    if res.status_code == 404 or "No endpoints found" in str(data):
                        self.blacklisted_models.add(model)
                        continue

                    if res.status_code in [429, 500, 503] or "error" in data:
                        continue
                    
                    if "choices" not in data:
                        continue

                    res.raise_for_status()
                    return data["choices"][0]["message"]["content"].strip()
                except Exception:
                    continue
        raise Exception("All OpenRouter models failed or blacklisted")

class MistralProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client_key = api_key

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client_key: raise Exception("Mistral unconfigured")
        async with httpx.AsyncClient() as client:
            res = await client.post(
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
    def __init__(self):
        self.providers = [
            GroqProvider(os.getenv("GROQ_API_KEY")),
            OpenRouterProvider(os.getenv("OPENROUTER_API_KEY")),
            MistralProvider(os.getenv("MISTRAL_API_KEY")),
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

llm_router = FallbackRouter()
scheduler = AsyncIOScheduler()

def clean_text(raw: str) -> str:
    if raw is None: return ""
    return re.sub(r'\*+', '', raw).strip()

def get_temporal() -> str:
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    return f"LIVE TEMPORAL CONTEXT: {now_ist.strftime('%A, %B %d, %Y at %I:%M:%S %p IST')}"

PENDING_STATES = {}

# -------------------------------------------------------------
# STARTUP EVENT: INITIALIZE ONCE & STORE ON app.state
# -------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    print("[ARIA OS]: Initializing background intelligence workers and core state...")
    
    # Initialize Clients
    tavily_key = os.getenv("TAVILY_API_KEY")
    app.state.tavily = TavilyClient(api_key=tavily_key) if tavily_key else None
    
    mongo_uri = os.getenv("MONGODB_URI")
    if mongo_uri:
        try:
            app.state.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
                mongo_uri, tlsCAFile=certifi.where(), tlsInsecure=True, serverSelectionTimeoutMS=5000
            )
        except Exception:
            app.state.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)
    else:
        app.state.mongo_client = None

    db_inst = app.state.mongo_client["aria_db"] if app.state.mongo_client is not None else None

    # Cached Mongo Collections
    app.state.mem_mongo = db_inst["personal_memory"] if db_inst is not None else None
    app.state.media_col = db_inst["media_vault"] if db_inst is not None else None
    app.state.chats_col = db_inst["chat_history"] if db_inst is not None else None
    app.state.schedule_col = db_inst["tasks_schedule"] if db_inst is not None else None
    app.state.profile_col = db_inst["user_profile"] if db_inst is not None else None

    # Initialize ChromaDB Persistent Client & Collections
    persist_path = os.getenv("RENDER_PERSISTENT_DIR", "./aria_vectors")
    os.makedirs(persist_path, exist_ok=True)
    app.state.chroma_client = chromadb.PersistentClient(path=persist_path)
    app.state.docs_col = app.state.chroma_client.get_or_create_collection(name="documents")
    app.state.mem_col = app.state.chroma_client.get_or_create_collection(name="memory")

    # Initialize Engines & Managers
    app.state.brain = AriaBrain(app.state.chroma_client)
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

    # Load Profile & Seed Graph
    if app.state.profile_engine is not None:
        profile = await app.state.profile_engine.get_profile()
        print(f"[ARIA OS]: User Profile Loaded for: {profile.get('name', 'User')}")

    app.state.brain.link_concepts("Saketh", "studies_at", "Gayatri Vidya Parishad College", category="education")
    app.state.brain.link_concepts("Saketh", "pursuing", "B.Tech Computer Science Engineering", category="education")
    app.state.brain.link_concepts("Saketh", "builds", "ARIA AI", category="projects")
    print("[ARIA OS]: Knowledge Graph successfully seeded with core entities.")

    # Initialize Background Workers & Scheduler Guard
    if db_inst is not None:
        workers = BackgroundWorkers(db_inst, llm_router, app.state.tavily)
        scheduler.add_job(workers.morning_briefing_worker, "cron", hour=9, minute=0)
        scheduler.add_job(workers.night_summary_worker, "cron", hour=22, minute=0)
        scheduler.add_job(workers.inactivity_worker, "interval", days=1)
        scheduler.add_job(workers.api_health_monitor_worker, "interval", hours=1)
        
        if not scheduler.running:
            scheduler.start()
            print("[ARIA OS]: Background Intelligence Workers active and running.")

# -------------------------------------------------------------
# TASK PROCESSING PIPELINE WITH STATE REUSE & OPTIMIZED ROUTER
# -------------------------------------------------------------
async def process_task(user_text: str, session_id: str) -> str:
    print(f"[STAGE -1] Processing task for session {session_id}: '{user_text}'")
    lower_txt = user_text.lower().strip()

    # Retrieve pre-initialized instances from app.state (No recreation per request)
    tool_mgr = app.state.tool_manager
    media_col = app.state.media_col
    chats_col = app.state.chats_col
    profile_col = app.state.profile_col
    mem_col = app.state.mem_col
    docs_col = app.state.docs_col
    aria_brain = app.state.brain
    conv_mgr = app.state.conversation_manager
    reflection_eng = app.state.reflection_engine

    # =========================================================
    # STAGE -1: DETERMINISTIC ROUTER (ZERO-TOKEN BYPASS)
    # =========================================================

    # 1. Telegram & System Commands
    if lower_txt.startswith("/start"):
        return "Welcome back, Sir.\nARIA Neural Core online.\nAll systems operational.\nHow may I assist you today?"
    if lower_txt.startswith("/help"):
        return "**ARIA Operating System Command Manual**:\n\n• Ask for live weather, news, or calculations.\n• Request documents ('Send my resume', 'What documents do you store?').\n• Manage tasks and schedules ('What is on my schedule today?')."
    if lower_txt.startswith("/settings"):
        return "ARIA System Settings:\n• Interface: Telegram\n• Vector Store: ChromaDB Persistent\n• LLM Tier: Multi-Provider Failover Active, Sir."
    if lower_txt.startswith("/about"):
        return "ARIA (Autonomous Responsive Intelligent Assistant) v3.5 AI Operating System, built for Saketh, Sir."
    if lower_txt.startswith("/ping"):
        return "Pong! All systems optimal, Sir."

    # 2. Identity Queries ("Who are you?")
    if any(k in lower_txt for k in ["who are you", "what are you", "your name"]):
        return "I am ARIA (Autonomous Responsive Intelligent Assistant), your dedicated AI operating system, built to manage your files, schedules, code, and intelligence feeds, Sir."

    # 3. Profile Inquiries ("What do you know about me?", "Who am I?")
    if any(k in lower_txt for k in ["what do you know about me", "tell me about myself", "my profile", "who am i"]):
        profile = {}
        if profile_col is not None:
            profile = await profile_col.find_one({"_id": "master_profile"}) or {}
        
        media_cursor = None
        if media_col is not None:
            media_cursor = media_col.find({}, {"file_name": 1, "category": 1})
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

    # 4. Batch Upload Intent Handler
    upload_phrases = ["send all my documents", "upload my documents", "here are my files", "i'll send my documents", "batch upload"]
    if any(phrase in lower_txt for phrase in upload_phrases):
        return (
            "Certainly, Sir.\n\n"
            "Send your documents one by one or in batches. I'll automatically:\n"
            "• Read and extract their contents.\n"
            "• Index them for semantic vector search.\n"
            "• Detect and skip duplicate content.\n"
            "• Categorize them and store originals in your Media Vault.\n\n"
            "Standing by for your files, Sir."
        )

    # 5. Greetings
    greetings = ["hi", "hello", "hey", "good morning", "good evening", "good afternoon", "greetings", "be10x"]
    if lower_txt in greetings or any(lower_txt.startswith(g) for g in ["hi ", "hello ", "hey "]):
        now_hour = datetime.now(timezone.utc).astimezone().hour
        time_greeting = "Good morning" if now_hour < 12 else ("Good afternoon" if now_hour < 17 else "Good evening")
        return f"{time_greeting}, Sir. ARIA online. What would you like to work on today?"

    # 6. Time & Date Queries
    if any(k in lower_txt for k in ["what time is it", "current time", "time now", "what's the time"]):
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        return f"Current time is {now_ist.strftime('%I:%M:%S %p IST')}, Sir."
    if any(k in lower_txt for k in ["date today", "what day is it", "today's date"]):
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        return f"Today is {now_ist.strftime('%A, %B %d, %Y')}, Sir."

    # 7. Structured MongoDB Location Storage
    if "i'm in" in lower_txt or "i am in" in lower_txt or "my location is" in lower_txt:
        location_name = re.sub(r".*?(i'm in|i am in|my location is)\s+", "", lower_txt).strip()
        if location_name and profile_col is not None:
            await profile_col.update_one(
                {"_id": "master_profile"},
                {"$set": {"location": location_name}},
                upsert=True
            )
            return f"Location locked as {location_name.title()}, Sir. Saved in profile for future local queries."

    # 8. Safe AST Calculator
    if re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', user_text) and any(op in user_text for op in ['+', '-', '*', '/']):
        calc_result = evaluate_math(user_text)
        if calc_result is not None:
            return f"Result: {calc_result}, Sir."

    # 9. Weather Requests
    if "weather" in lower_txt:
        loc_query = "Visakhapatnam"
        if profile_col is not None:
            prof_doc = await profile_col.find_one({"_id": "master_profile"})
            if prof_doc and prof_doc.get("location"):
                loc_query = prof_doc.get("location")
        res = await tool_mgr.execute_tool("web", f"current weather in {loc_query}", chat_id=session_id)
        return f"{res.get('content', 'Weather data unavailable.')}"

    # 10. Schedule Requests
    if any(kw in lower_txt for kw in ["schedule", "task", "reminder", "today"]):
        res = await tool_mgr.execute_tool("schedule", user_text, chat_id=session_id)
        if res.get("success"):
            return f"{res.get('content')}, Sir."

    # 11. Media Vault & Document Requests
    media_intent_keywords = [
        "resume", "cv", "portfolio", "pan", "passport", 
        "certificate", "memo", "pdf", "document", "file", 
        "download", "licence", "license", "id card", "my file", "send document", 
        "what documents", "list files", "stored files", "search my files", "list media"
    ]
    if any(keyword in lower_txt for keyword in media_intent_keywords):
        res = await tool_mgr.execute_tool("media", user_text, chat_id=session_id)
        if not res.get("success") and not res.get("metadata", {}).get("requires_clarification"):
            PENDING_STATES[session_id] = {"tool": "media", "query": user_text}
        return f"{res.get('content')}"

    # =========================================================
    # STAGE 0 & ABOVE: REFLECTION, BRAIN, PLANNER, & REASONER
    # =========================================================

    correction = await reflection_eng.evaluate_feedback(user_text, session_id)
    if correction and correction.get("needs_retry"):
        res = await tool_mgr.execute_tool(correction["retry_tool"], user_text, chat_id=session_id)
        return f"{correction['explanation']}\n\n{res.get('content', '')}"

    cached_brain_hit = aria_brain.search_brain(user_text)
    if cached_brain_hit and cached_brain_hit["confidence"] > 0.92:
        return cached_brain_hit["answer"]

    print("[PLANNING STAGE]: Running single-pass action planner...")
    session_context = await conv_mgr.build_session_context(session_id)
    available_tools_desc = tool_mgr.describe_tools()

    executed_tools = []
    structured_results = {"memory": {}, "documents": {}, "web": {}, "media": {}, "schedule": {}}

    # Single-pass plan execution
    plan = await action_planner(user_text, session_context, available_tools_desc, executed_tools, llm_router)
    tools_to_run = plan.get("tools", [])
    action = plan.get("action", "retrieve")

    if action == "save" and any(w in lower_txt for w in ["remember", "my ", "i like"]):
        if mem_col is not None:
            mem_col.add(ids=[str(datetime.now().timestamp())], documents=[user_text])
        return "Information stored permanently in your vector vault, Sir."

    for t_name in tools_to_run:
        if t_name not in executed_tools:
            print(f"[TOOL EXECUTION]: {t_name}")
            result = await tool_mgr.execute_tool(t_name, user_text, chat_id=session_id)
            structured_results[t_name] = result
            executed_tools.append(t_name)

    print("[REASONER STAGE]: Synthesizing response...")
    raw_answer = await reason(user_text, structured_results, llm_router, get_temporal(), available_tools_desc, session_context)
    cleaned = clean_text(raw_answer)

    has_valid_source = any(res.get("success") for res in structured_results.values())
    if has_valid_source:
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
    return JSONResponse(status_code=200, content={"status": "online", "core": "Multi-Provider State-Optimized Core"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>ARIA State-Optimized Autonomous Core Active</h1>"
