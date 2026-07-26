import os
import json
import httpx
import base64
import re
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
# ROBUST MULTI-PROVIDER TIERED AI ROUTER
# -------------------------------------------------------------
class LLMProvider:
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        raise NotImplementedError

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key) if api_key else None

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if self.client is None: raise Exception("Groq unconfigured")
        for attempt in range(2):
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
                print(f"[Groq Attempt {attempt+1} Failed]: {e}")
                if attempt == 0: await asyncio.sleep(1.0)
                else: raise e

class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client_key = api_key
        self.models = [
            "meta-llama/llama-3-70b-instruct",
            "mistralai/mixtral-8x7b-instruct",
            "google/gemma-2-9b-it"
        ]

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client_key: raise Exception("OpenRouter unconfigured")
        async with httpx.AsyncClient() as client:
            for model in self.models:
                for attempt in range(2):
                    try:
                        res = await client.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers={"Authorization": f"Bearer {self.client_key}", "Content-Type": "application/json"},
                            json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                            timeout=15.0
                        )
                        data = res.json()
                        if res.status_code in [429, 500, 503] or "error" in data:
                            print(f"[OpenRouter Model {model} Error]: {data}")
                            await asyncio.sleep(1.0)
                            continue
                        
                        if "choices" not in data:
                            print(f"[OpenRouter Invalid Response Key]: {data}")
                            raise Exception(f"Invalid OpenRouter payload: {data}")

                        res.raise_for_status()
                        return data["choices"][0]["message"]["content"].strip()
                    except Exception as e:
                        print(f"[OpenRouter Model {model} Exception]: {e}")
                        break
        raise Exception("All OpenRouter models failed")

class MistralProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client_key = api_key

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client_key: raise Exception("Mistral unconfigured")
        async with httpx.AsyncClient() as client:
            for attempt in range(2):
                try:
                    res = await client.post(
                        "https://api.mistral.ai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self.client_key}", "Content-Type": "application/json"},
                        json={"model": "mistral-small-latest", "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                        timeout=15.0
                    )
                    data = res.json()
                    if res.status_code in [429, 500, 503] or "error" in data:
                        print(f"[Mistral Error]: {data}")
                        await asyncio.sleep(1.0)
                        continue
                    
                    if "choices" not in data:
                        print(f"[Mistral Invalid Response Key]: {data}")
                        raise Exception(f"Invalid Mistral payload: {data}")

                    res.raise_for_status()
                    return data["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    print(f"[Mistral Attempt {attempt+1} Failed]: {e}")
                    if attempt == 0: await asyncio.sleep(1.0)
                    else: raise e
        raise Exception("Mistral provider failed")

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key) if api_key else None

    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if self.client is None: raise Exception("Gemini unconfigured")
        prompt_lines = [f"{m['role'].upper()}: {m['content']}" for m in messages]
        prompt_str = "\n".join(prompt_lines) + "\nARIA:"
        for attempt in range(2):
            try:
                def _exec():
                    res = self.client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents=prompt_str
                    )
                    return res.text.strip()
                return await asyncio.to_thread(_exec)
            except Exception as e:
                print(f"[Gemini Attempt {attempt+1} Failed]: {e}")
                if attempt == 0: await asyncio.sleep(1.0)
                else: raise e

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

# -------------------------------------------------------------
# CLIENT INITIALIZATION & GETTERS
# -------------------------------------------------------------
_tavily_client = None
_mongo_client = None
_chroma_client = None
_aria_brain = None

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

def get_brain():
    global _aria_brain
    if _aria_brain is None:
        _aria_brain = AriaBrain(get_chroma())
    return _aria_brain

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

# Stateful conversational follow-up memory
PENDING_STATES = {}

# -------------------------------------------------------------
# TASK PROCESSING PIPELINE
# -------------------------------------------------------------
async def process_task(user_text: str, session_id: str) -> str:
    print(f"[STAGE 0] Processing task for session {session_id}: '{user_text}'")
    lower_txt = user_text.lower().strip()

    tavily = get_tavily()
    docs_col, mem_col = get_collections()
    mem_mongo, media_col, chats_col, schedule_col = get_mongo_collections()
    tool_mgr = ToolManager(mem_col, docs_col, media_col, schedule_col, tavily)

    # 1. REFLECTION ENGINE RUNS FIRST
    reflection_eng = ReflectionEngine(chats_col, media_col)
    correction = await reflection_eng.evaluate_feedback(user_text, session_id)
    if correction and correction.get("needs_retry"):
        print("[REFLECTION TRIGGERED]: Retrying media vault search...")
        res = await tool_mgr.execute_tool(correction["retry_tool"], user_text, chat_id=session_id)
        return f"{correction['explanation']}\n\n{res.get('content', '')}"

    # 2. STATEFUL FOLLOW-UP INTENT HANDLER ("Yes", "Send it", etc.)
    affirmative_triggers = ["yes", "yep", "sure", "go ahead", "send it", "do it", "please do"]
    if lower_txt in affirmative_triggers and session_id in PENDING_STATES:
        pending = PENDING_STATES.pop(session_id)
        print(f"[STATEFUL INTENT]: Executing pending action: {pending}")
        if pending.get("tool") == "media":
            res = await tool_mgr.execute_tool("media", pending["query"], chat_id=session_id)
            return res.get("content", "Action completed, Sir.")

    # 3. DETERMINISTIC INTENT ENGINE (Zero-Token Handlers)
    zero_token_responses = {
        "hello": "Greetings, Sir. How may I assist you today?",
        "hi": "Hello, Sir. ARIA systems online.",
        "hey": "I am here, Sir. What do you need?",
        "thanks": "You are very welcome, Sir.",
        "thank you": "My pleasure, Sir.",
        "great": "Excellent, Sir. Standing by.",
        "awesome": "Glad to be of service, Sir.",
        "good job": "Thank you, Sir. I aim to please.",
        "good morning": "Good morning, Sir. Systems are optimal.",
        "good evening": "Good evening, Sir. Ready when you are.",
        "no": "Understood, Sir. Aborting.",
        "okay": "Standing by for further instructions, Sir.",
        "ok": "Standing by, Sir.",
        "continue": "Proceeding as requested, Sir."
    }
    if lower_txt in zero_token_responses:
        PENDING_STATES.pop(session_id, None)
        print("[INTENT BYPASS] Zero-Token response triggered.")
        return zero_token_responses[lower_txt]

    # Deterministic Calculator / Math Bypass
    if re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', user_text) and any(op in user_text for op in ['+', '-', '*', '/']):
        try:
            calc_result = eval(user_text)
            print("[INTENT BYPASS] Deterministic calculation executed.")
            return f"Result: {calc_result}"
        except Exception:
            pass

    # Deterministic Time Bypass
    if any(k in lower_txt for k in ["what time is it", "current time", "date today", "what day is it"]):
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        return f"Current time is {now_ist.strftime('%I:%M:%S %p IST')} on {now_ist.strftime('%A, %B %d, %Y')}."

    # 4. BROAD MEDIA & DOCUMENT INTENT BYPASS
    media_intent_keywords = [
        "resume", "cv", "portfolio", "aadhar", "aadhaar", "pan", "certificate", 
        "pdf", "document", "file", "download", "my file", "send document"
    ]
    if any(keyword in lower_txt for keyword in media_intent_keywords):
        print(f"[INTENT BYPASS] Broad Media/Document Tool trigger for query: '{user_text}'")
        res = await tool_mgr.execute_tool("media", user_text, chat_id=session_id)
        if not res.get("success"):
            PENDING_STATES[session_id] = {"tool": "media", "query": user_text}
        return res.get("content")

    if any(kw in lower_txt for kw in ["schedule", "task", "reminder", "today"]):
        print("[INTENT BYPASS] Triggering Schedule Tool directly.")
        res = await tool_mgr.execute_tool("schedule", user_text, chat_id=session_id)
        if res.get("success"):
            return res.get("content")

    # 5. BRAIN SEARCH WITH STRICT CONFIDENCE THRESHOLD (> 0.92)
    aria_brain = get_brain()
    cached_brain_hit = aria_brain.search_brain(user_text)
    if cached_brain_hit and cached_brain_hit["confidence"] > 0.92:
        print(f"[BRAIN HIT]: Serving high-confidence answer (Confidence: {cached_brain_hit['confidence']})")
        return cached_brain_hit["answer"]

    print("[BRAIN MISS or LOW CONFIDENCE]: Proceeding to autonomous planner & reasoner...")

    conv_mgr = ConversationManager(chats_col)
    session_context = await conv_mgr.build_session_context(session_id)
    available_tools_desc = tool_mgr.describe_tools()

    executed_tools = []
    structured_results = {"memory": {}, "documents": {}, "web": {}, "media": {}, "schedule": {}}

    # SMART PLANNER LOOP WITH REPEAT-DETECTION TERMINATION
    for i in range(4):  
        print(f"[STAGE 1] Running action planner (iteration {i+1})...")
        plan = await action_planner(user_text, session_context, available_tools_desc, executed_tools, llm_router)
        tools_to_run = plan.get("tools", [])
        action = plan.get("action", "retrieve")

        if action == "save" and any(w in lower_txt for w in ["remember", "my ", "i like"]):
            if mem_col is not None:
                await mem_col.add(ids=[str(datetime.now().timestamp())], documents=[user_text])
            return "Information stored permanently in your vector vault, Sir."

        if not tools_to_run or set(tools_to_run).issubset(set(executed_tools)):
            print("[STAGE 1] Planner loop terminated: No new tools required or duplicate plan detected.")
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

    # 6. ANTI-HALLUCINATION GUARD: Only store if verified by tools
    has_valid_source = any(res.get("success") for res in structured_results.values())
    if has_valid_source:
        is_time_sensitive = any(w in lower_txt for w in ["today", "now", "current", "weather", "news", "president"])
        knowledge_type = "DYNAMIC" if is_time_sensitive else "STATIC"
        
        aria_brain.store_knowledge(
            question=user_text,
            answer=cleaned,
            topic="general",
            category="general",
            summary=cleaned[:150],
            source="Verified Tool/AI",
            confidence=0.96,
            verified=True,
            knowledge_type=knowledge_type
        )
        print("[LEARNING ENGINE]: Verified response successfully stored in Brain.")
    else:
        print("[LEARNING ENGINE]: Skipping brain storage — response lacked verified tool backing.")

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
    return JSONResponse(status_code=200, content={"status": "online", "core": "Multi-Provider Brain-Enhanced Core"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>ARIA Brain-Enhanced Autonomous Core Active</h1>"
