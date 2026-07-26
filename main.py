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
from pydantic import BaseModel
from pypdf import PdfReader
import edge_tts

# Provider SDKs
from groq import Groq
from google import genai
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from tavily import TavilyClient
import motor.motor_asyncio

# Scheduler SDKs
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

app = FastAPI()

# -------------------------------------------------------------
# 1. GLOBAL ENVIRONMENT & CACHE INITIALIZATION
# -------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_TELEGRAM_USER_ID = os.getenv("ALLOWED_TELEGRAM_USER_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")

ASSISTANT_NAME = "ARIA"
USER_FULL_NAME = "N. Vishnu Saketh"

RAM_MEMORY_CACHE = [f"[PERSONAL_PROFILE]: User Full Name is {USER_FULL_NAME}"]
RAM_SCHEDULE_CACHE = []
RAM_RECENT_CHATS = []
LAST_CACHE_UPDATE = 0
LAST_USER_INTERACTION_TIME = datetime.now(timezone.utc)
PENDING_SECURITY_ACTIONS = {}

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

def init_mongo_client():
    if not MONGODB_URI: return None
    try:
        return motor.motor_asyncio.AsyncIOMotorClient(
            MONGODB_URI,
            tlsCAFile=certifi.where(),
            tlsInsecure=True,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000
        )
    except Exception as e:
        print(f"[Mongo Init Exception]: {e}")
        return motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)

mongo_client = init_mongo_client()
mongo_db = mongo_client["aria_db"] if mongo_client else None

mongo_memory_col = mongo_db["personal_memory"] if mongo_db is not None else None
mongo_tasks_col = mongo_db["tasks_schedule"] if mongo_db is not None else None
mongo_media_col = mongo_db["media_vault"] if mongo_db is not None else None
mongo_chats_col = mongo_db["chat_history"] if mongo_db is not None else None
mongo_reminders_col = mongo_db["reminders"] if mongo_db is not None else None
mongo_security_col = mongo_db["security_logs"] if mongo_db is not None else None

CACHE_VOICES = []
scheduler = AsyncIOScheduler()

# -------------------------------------------------------------
# 2. SANITIZATION & TEMPORAL ENGINE
# -------------------------------------------------------------
def clean_response_text(raw_text: str) -> str:
    if not raw_text: return ""
    text = raw_text.strip()
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'[\,\.\s]*,[\,\.\s]*', ', ', text)
    text = re.sub(r'\.\s*\.', '.', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\s+([\.,\?!])', r'\1', text)
    return text.strip()

def get_current_temporal_context() -> str:
    now_utc = datetime.now(timezone.utc)
    ist_offset = timedelta(hours=5, minutes=30)
    now_ist = now_utc + ist_offset
    return f"\nLIVE TEMPORAL CONTEXT: {now_ist.strftime('%A, %B %d, %Y at %I:%M:%S %p IST')}\n"

async def sync_ram_cache():
    global RAM_MEMORY_CACHE, RAM_SCHEDULE_CACHE, RAM_RECENT_CHATS, LAST_CACHE_UPDATE
    now = datetime.now().timestamp()
    if now - LAST_CACHE_UPDATE < 20 and len(RAM_MEMORY_CACHE) > 1:
        return RAM_MEMORY_CACHE, RAM_SCHEDULE_CACHE, RAM_RECENT_CHATS

    facts = [f"[PERSONAL_PROFILE]: User Full Name is {USER_FULL_NAME}"]
    schedules = []
    chats = []

    if mongo_db is not None:
        try:
            cursor = mongo_memory_col.find({})
            async for doc in cursor:
                fact_entry = f"[{doc.get('category', 'MEMORY').upper()}]: {doc.get('fact', '')}"
                if fact_entry not in facts: facts.append(fact_entry)

            task_cursor = mongo_tasks_col.find({}).sort("_id", -1)
            async for tdoc in task_cursor:
                sch_entry = f"• Task: {tdoc.get('task')} | Slot: {tdoc.get('timing')}"
                if sch_entry not in schedules: schedules.append(sch_entry)

            chat_cursor = mongo_chats_col.find({}).sort("_id", -1).limit(8)
            chat_docs = await chat_cursor.to_list(length=8)
            for cdoc in reversed(chat_docs):
                chats.append(f"User: {cdoc.get('user_msg')}\nARIA: {cdoc.get('aria_reply')}")

        except Exception as e:
            print(f"[RAM Sync Status]: {e}")

    RAM_MEMORY_CACHE = facts
    RAM_SCHEDULE_CACHE = schedules
    RAM_RECENT_CHATS = chats
    LAST_CACHE_UPDATE = now
    return RAM_MEMORY_CACHE, RAM_SCHEDULE_CACHE, RAM_RECENT_CHATS

# -------------------------------------------------------------
# 3. DIRECT FILE DISPATCH & AUTONOMOUS TOOLS
# -------------------------------------------------------------
async def send_file_from_vault(file_query: str, chat_id: str) -> str:
    """Finds the matching document in MongoDB and dispatches the raw file directly via Telegram."""
    if mongo_media_col is None:
        return "Vault database is currently offline, Sir."

    try:
        q_regex = re.compile(file_query.strip(), re.IGNORECASE)
        # Search by file name first, then content preview
        target_doc = await mongo_media_col.find_one({"file_name": q_regex})
        if not target_doc:
            target_doc = await mongo_media_col.find_one({"caption": q_regex})

        if not target_doc:
            return f"I searched the vault, Sir, but could not find any document matching '{file_query}'."

        fname = target_doc.get("file_name", "document.pdf")
        mtype = target_doc.get("media_type", "document")
        raw_bytes = base64.b64decode(target_doc["b64_payload"])

        endpoint = "sendVoice" if mtype == "voice" else ("sendVideo" if mtype == "video" else ("sendPhoto" if mtype == "image" else "sendDocument"))
        param_name = "voice" if mtype == "voice" else ("video" if mtype == "video" else ("photo" if mtype == "image" else "document"))

        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{endpoint}",
                data={"chat_id": chat_id, "caption": f"Here is your document: '{fname}', Sir."},
                files={param_name: (fname, raw_bytes, "application/octet-stream")}
            )

        return f"File '{fname}' dispatched successfully to your Telegram, Sir."
    except Exception as e:
        print(f"[File Dispatch Error]: {e}")
        return f"Encountered an issue dispatching '{file_query}', Sir."

async def log_security_breach(unauthorized_id: str, raw_msg: str):
    if mongo_security_col is not None:
        try:
            await mongo_security_col.insert_one({
                "unauthorized_id": str(unauthorized_id),
                "attempted_message": raw_msg,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except Exception: pass

    if TELEGRAM_TOKEN and ALLOWED_TELEGRAM_USER_ID:
        alert_msg = f"SECURITY ALERT, Sir: Unauthorized access attempt detected from Telegram User ID {unauthorized_id}. Message intercepted: '{raw_msg[:100]}'."
        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": ALLOWED_TELEGRAM_USER_ID, "text": alert_msg}
                )
            except Exception: pass

async def send_scheduled_reminder(reminder_text: str):
    if not TELEGRAM_TOKEN or not ALLOWED_TELEGRAM_USER_ID: return
    msg = f"Alert, Sir: You have a scheduled reminder — '{reminder_text}'."
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": ALLOWED_TELEGRAM_USER_ID, "text": msg}
            )
        except Exception as e: print(f"[Reminder Error]: {e}")

async def create_time_reminder(minutes: int, task_desc: str) -> str:
    run_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    job_id = f"reminder_{int(run_time.timestamp())}"
    
    scheduler.add_job(
        send_scheduled_reminder,
        trigger=DateTrigger(run_date=run_time),
        args=[task_desc],
        id=job_id,
        replace_existing=True
    )

    if mongo_reminders_col is not None:
        try:
            await mongo_reminders_col.insert_one({
                "task": task_desc, "duration_minutes": minutes,
                "deliver_at": run_time.isoformat(), "status": "pending"
            })
        except Exception: pass

    return f"Reminder established for '{task_desc}' in {minutes} minute{'s' if minutes > 1 else ''}, Sir."

async def query_document_vault(search_query: str) -> str:
    if mongo_media_col is None: return "Document vault unavailable, Sir."
    try:
        q_regex = re.compile(search_query, re.IGNORECASE)
        docs = await mongo_media_col.find({"$or": [{"file_name": q_regex}, {"caption": q_regex}]}).to_list(length=5)

        if not docs:
            return f"No document content matching '{search_query}' found in your vault, Sir."

        results = []
        for d in docs:
            results.append(f"Document '{d.get('file_name')}': {d.get('caption', '')[:300]}...")

        return "RETRIEVED DOCUMENT INTELLIGENCE:\n" + "\n---\n".join(results)
    except Exception as e:
        return f"Document query error: {str(e)}"

async def get_system_diagnostics() -> str:
    mem_count = await mongo_memory_col.count_documents({}) if mongo_memory_col is not None else 0
    task_count = await mongo_tasks_col.count_documents({}) if mongo_tasks_col is not None else 0
    doc_count = await mongo_media_col.count_documents({}) if mongo_media_col is not None else 0
    sec_count = await mongo_security_col.count_documents({}) if mongo_security_col is not None else 0

    return f"DIAGNOSTIC STATUS, Sir: All systems nominal. MongoDB Atlas connected. Memory Records: {mem_count}, Active Tasks: {task_count}, Secured Documents: {doc_count}, Security Incidents Logged: {sec_count}."

async def save_scheduled_task(task: str, timing: str, date_str: str = "Today") -> str:
    sch_entry = f"• Task: {task} | Slot: {timing}"
    if sch_entry not in RAM_SCHEDULE_CACHE: RAM_SCHEDULE_CACHE.append(sch_entry)

    if mongo_tasks_col is not None:
        try:
            await mongo_tasks_col.insert_one({
                "task": task, "timing": timing, "date": date_str, "status": "active",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except Exception: pass

    return f"Task '{task}' scheduled for {timing}, Sir."

async def save_memory_fact(category: str, fact: str) -> str:
    cat = category.lower().strip()
    fact_str = fact.strip()
    RAM_MEMORY_CACHE.append(f"[{cat.upper()}]: {fact_str}")

    if mongo_memory_col is not None:
        try:
            await mongo_memory_col.insert_one({"category": cat, "fact": fact_str, "timestamp": datetime.now(timezone.utc).isoformat()})
        except Exception: pass

    return "Information saved permanently in your vault, Sir."

async def purge_all_vault_data() -> str:
    if mongo_memory_col is not None: await mongo_memory_col.delete_many({})
    if mongo_tasks_col is not None: await mongo_tasks_col.delete_many({})
    if mongo_chats_col is not None: await mongo_chats_col.delete_many({})
    if mongo_media_col is not None: await mongo_media_col.delete_many({})
    if mongo_reminders_col is not None: await mongo_reminders_col.delete_many({})
    
    global RAM_MEMORY_CACHE, RAM_SCHEDULE_CACHE, RAM_RECENT_CHATS
    RAM_MEMORY_CACHE = [f"[PERSONAL_PROFILE]: User Full Name is {USER_FULL_NAME}"]
    RAM_SCHEDULE_CACHE = []
    RAM_RECENT_CHATS = []
    return "All database records and session vault data have been completely purged, Sir."

async def log_chat_interaction(user_msg: str, aria_reply: str, session_id: str):
    global LAST_USER_INTERACTION_TIME
    LAST_USER_INTERACTION_TIME = datetime.now(timezone.utc)
    if mongo_chats_col is not None:
        try:
            await mongo_chats_col.insert_one({
                "session_id": session_id, "user_msg": user_msg,
                "aria_reply": aria_reply, "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except Exception: pass

async def save_media_file(file_name: str, media_type: str, raw_bytes: bytes, caption: str = ""):
    b64_payload = base64.b64encode(raw_bytes).decode('utf-8')
    if mongo_media_col is not None:
        try:
            await mongo_media_col.insert_one({
                "file_name": file_name, "media_type": media_type,
                "caption": caption.lower().strip(), "b64_payload": b64_payload,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except Exception: pass

    await save_memory_fact("media_vault", f"SAVED {media_type.upper()}: '{file_name}' | Text Preview: {caption[:400]}")
    return f"{media_type.capitalize()} '{file_name}' fully parsed and secured in your document vault, Sir."

def fetch_web_search(query: str) -> str:
    if not tavily_client: return ""
    try:
        res = tavily_client.search(query=query, max_results=2)
        results = [f"- {item['title']}: {item['content'][:150]}" for item in res.get("results", [])]
        return "\nREAL-TIME WEB INTELLIGENCE:\n" + "\n".join(results) + "\n"
    except Exception: pass
    return ""

async def fetch_weather_by_coords(location_info: str = "17.6868,83.2185") -> str:
    if not location_info or "," not in location_info: location_info = "17.6868,83.2185"
    try:
        lat, lon = location_info.split(",")
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=2.0)
            if res.status_code == 200:
                data = res.json().get("current_weather", {})
                return f"\nLIVE WEATHER: Temperature {data.get('temperature')}°C, Wind Speed {data.get('windspeed')} km/h.\n"
    except Exception: pass
    return ""

# -------------------------------------------------------------
# 4. PROACTIVE DAEMON
# -------------------------------------------------------------
async def autonomous_proactive_checkin():
    if not TELEGRAM_TOKEN or not ALLOWED_TELEGRAM_USER_ID: return
    now = datetime.now(timezone.utc)
    if (now - LAST_USER_INTERACTION_TIME).total_seconds() / 60.0 < 25: return

    _, cached_schedules, _ = await sync_ram_cache()
    if not cached_schedules: return

    active_task = cached_schedules[0]
    checkin_prompt = f"You are J.A.R.V.I.S. The user is in task '{active_task}' and silent for 25 mins. Briefly ask if they need assistance or a status check. Address as Sir."

    if groq_client:
        try:
            comp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": checkin_prompt}],
                temperature=0.4, max_tokens=100
            )
            msg = clean_response_text(comp.choices[0].message.content)
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": ALLOWED_TELEGRAM_USER_ID, "text": msg})
        except Exception: pass

# -------------------------------------------------------------
# 5. FUNCTION-CALLING INFERENCE ENGINE
# -------------------------------------------------------------
GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_file_from_vault",
            "description": "Sends the actual binary PDF/file to the user's Telegram chat when they ask to receive, download, or get a document/resume.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_query": {"type": "string", "description": "Keyword/filename e.g. 'resume', 'certificate', 'saketh'"}
                },
                "required": ["file_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_time_reminder",
            "description": "Sets a timed alert or reminder to trigger after a specific number of minutes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "Number of minutes from now to send the reminder alert"},
                    "task_desc": {"type": "string", "description": "What the user needs to be reminded to do"}
                },
                "required": ["minutes", "task_desc"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_scheduled_task",
            "description": "Schedules a task or event into the user's daily calendar/agenda.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task name or description"},
                    "timing": {"type": "string", "description": "Time slot string e.g. '10am-11am' or '5:00 PM'"}
                },
                "required": ["task", "timing"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory_fact",
            "description": "Saves a personal profile fact, detail, or preference about the user into the permanent vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Fact category e.g. personal_profile, study, preferences"},
                    "fact": {"type": "string", "description": "The exact fact or detail to remember"}
                },
                "required": ["category", "fact"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_document_vault",
            "description": "Reads text content inside uploaded PDF documents to answer study/project questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_query": {"type": "string", "description": "Keyword or topic to read inside documents"}
                },
                "required": ["search_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_diagnostics",
            "description": "Audits assistant health, database metrics, security incidents, and active tasks.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

async def process_autonomous_task(user_text: str, session_id: str, location_info: str = None) -> str:
    cmd = user_text.lower().strip()

    # Security Confirmation Dialogue
    if session_id in PENDING_SECURITY_ACTIONS:
        pending = PENDING_SECURITY_ACTIONS[session_id]
        if any(k in cmd for k in ["yes", "proceed", "authorize", "do it", "confirm", "sure", "clear"]):
            del PENDING_SECURITY_ACTIONS[session_id]
            if pending["type"] == "purge_vault": return await purge_all_vault_data()
        elif any(k in cmd for k in ["no", "cancel", "stop", "abort", "don't", "dont"]):
            del PENDING_SECURITY_ACTIONS[session_id]
            return "Security action aborted, Sir."

    if any(k in cmd for k in ["delete all data", "clear database", "purge vault", "erase everything"]):
        PENDING_SECURITY_ACTIONS[session_id] = {"type": "purge_vault"}
        return "Security Protocol Alert: This will permanently wipe all vault records, schedules, and memory. Do you authorize this action, Sir?"

    cached_facts, cached_schedules, cached_chats = await sync_ram_cache()
    temporal_context = get_current_temporal_context()
    weather_context = await fetch_weather_by_coords(location_info or "17.6868,83.2185") if any(k in cmd for k in ["weather", "temp", "rain"]) else ""
    search_context = fetch_web_search(user_text) if any(k in cmd for k in ["search", "latest", "news", "who is"]) else ""

    memory_context = "\nSTORED VAULT MEMORY:\n" + "\n".join(cached_facts) if cached_facts else ""
    schedule_context = "\nACTIVE SCHEDULED TASKS & EVENTS:\n" + ("\n".join(cached_schedules) if cached_schedules else "No tasks scheduled.")
    history_context = "\nRECENT CONVERSATION HISTORY:\n" + ("\n---\n".join(cached_chats) if cached_chats else "None.")

    system_prompt = f"""You are {ASSISTANT_NAME}, an autonomous, hyper-intelligent AI assistant combining J.A.R.V.I.S. and Spider-Man's Karen.

{temporal_context}
{weather_context}
{schedule_context}
{memory_context}
{history_context}
{search_context}

DYNAMIC DIRECTIVES:
- FILE REQUEST RULE: If the user asks to receive, download, or get a document/resume file, call 'send_file_from_vault' with the file query immediately.
- USE TOOLS FREELY: Call functions automatically for reminders, tasks, document reading, and system diagnostics.
- ADDRESS & SALUTATIONS: Address the user as 'Sir' or 'Master'. Never use scripted lines like "Good day Mr. Saketh".
- FORMATTING: Never output bold asterisks (*), extra commas, or double spaces. Keep tone crisp, witty, intelligent, and natural.
- CONCISENESS: Keep conversational responses brief (1-2 sentences max)."""

    reply_text = "All systems operational, Sir."

    if groq_client:
        try:
            def _groq_exec():
                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
                    tools=GROQ_TOOLS,
                    tool_choice="auto",
                    temperature=0.3, max_tokens=180
                )
                return response.choices[0].message

            msg = await asyncio.to_thread(_groq_exec)

            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

                    if fn_name == "send_file_from_vault":
                        reply_text = await send_file_from_vault(fn_args.get("file_query", "resume"), session_id)
                    elif fn_name == "create_time_reminder":
                        reply_text = await create_time_reminder(fn_args.get("minutes", 5), fn_args.get("task_desc", "Task"))
                    elif fn_name == "save_scheduled_task":
                        reply_text = await save_scheduled_task(fn_args.get("task"), fn_args.get("timing"))
                    elif fn_name == "save_memory_fact":
                        reply_text = await save_memory_fact(fn_args.get("category", "general"), fn_args.get("fact"))
                    elif fn_name == "query_document_vault":
                        reply_text = await query_document_vault(fn_args.get("search_query", ""))
                    elif fn_name == "get_system_diagnostics":
                        reply_text = await get_system_diagnostics()
            elif msg.content:
                reply_text = msg.content.strip()

        except Exception as e:
            print(f"[Groq Execution Error]: {e}")

    if reply_text == "All systems operational, Sir." and gemini_client:
        try:
            def _gemini_sync():
                res = gemini_client.models.generate_content(
                    model="gemini-2.0-flash", contents=f"{system_prompt}\n\nUser: {user_text}\nARIA:"
                )
                return res.text
            reply = await asyncio.to_thread(_gemini_sync)
            if reply and len(reply.strip()) > 0: reply_text = reply.strip()
        except Exception as e: print(f"[Gemini Error]: {e}")

    cleaned_reply = clean_response_text(reply_text)
    asyncio.create_task(log_chat_interaction(user_text, cleaned_reply, session_id))
    return cleaned_reply

# -------------------------------------------------------------
# 6. TELEGRAM WEBHOOK
# -------------------------------------------------------------
@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    if not TELEGRAM_TOKEN: return {"status": "no token"}
    
    try:
        data = await req.json()
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        from_user_id = message.get("from", {}).get("id")
        text = message.get("text", "").strip()
        document = message.get("document", None)
        voice = message.get("voice", None)
        video = message.get("video", None)
        photo = message.get("photo", None)

        if not chat_id: return {"status": "no chat_id"}

        if ALLOWED_TELEGRAM_USER_ID and str(from_user_id) != str(ALLOWED_TELEGRAM_USER_ID):
            await log_security_breach(from_user_id, text or "Non-text payload")
            return {"status": "unauthorized"}

        if text.lower() == "/start":
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": "Online and fully operational, Sir. How may I assist you today?"}
                )
            return {"status": "ok"}

        file_obj, media_type, default_name = None, "document", "file.dat"
        if document: file_obj, media_type, default_name = document, "document", document.get("file_name", "document.pdf")
        elif voice: file_obj, media_type, default_name = voice, "voice", "voice_note.ogg"
        elif video: file_obj, media_type, default_name = video, "video", "video_clip.mp4"
        elif photo: file_obj, media_type, default_name = photo[-1], "image", "photo.jpg"

        if file_obj:
            file_id = file_obj.get("file_id")
            async with httpx.AsyncClient() as client:
                file_info = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}")
                file_path = file_info.json().get("result", {}).get("file_path")
                raw_bytes_res = await client.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}")
                raw_bytes = raw_bytes_res.content

            extracted_text = extract_text_from_pdf(raw_bytes) if default_name.lower().endswith(".pdf") else "Binary File"
            save_reply = await save_media_file(default_name, media_type, raw_bytes, caption=extracted_text)
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": save_reply})
            return {"status": "ok"}

        if text:
            reply_text = await process_autonomous_task(text, str(chat_id))
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": reply_text})
            return {"status": "ok"}

    except Exception as e: print(f"[Webhook Error]: {e}")
    return {"status": "ok"}

@app.on_event("startup")
async def start_scheduler():
    await sync_ram_cache()
    scheduler.add_job(autonomous_proactive_checkin, 'interval', minutes=30, id="proactive_checkin_job")
    scheduler.start()
    print("[J.A.R.V.I.S. Direct File Dispatch Core]: Fully Active.")

# -------------------------------------------------------------
# 7. SPEECH & FRONTEND HUD
# -------------------------------------------------------------
async def generate_speech_audio_b64(text: str, selected_voice: str = "en-GB-RyanNeural") -> str:
    is_telugu_script = bool(re.search(r'[\u0C00-\u0C7F]', text))
    voice_to_use = "te-IN-MohanNeural" if (is_telugu_script and "te-IN" not in selected_voice) else selected_voice

    try:
        communicate = edge_tts.Communicate(text, voice_to_use)
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio": audio_data.extend(chunk["data"])
        return base64.b64encode(audio_data).decode('utf-8')
    except Exception:
        communicate = edge_tts.Communicate(text, "en-GB-RyanNeural")
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio": audio_data.extend(chunk["data"])
        return base64.b64encode(audio_data).decode('utf-8')

def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(file_bytes))
        return "".join([page.extract_text() or "" for page in reader.pages]).strip()
    except Exception: return ""

@app.head("/health")
@app.get("/health")
def health_check():
    return JSONResponse(status_code=200, content={"status": "online", "database": "MongoDB Atlas", "system": "ARIA Direct File Dispatcher Active"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_webapp():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>{ASSISTANT_NAME}</title>
        <style>
            * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #020617; color: #f8fafc;
                min-height: 100vh; display: flex; flex-direction: column;
                align-items: center; justify-content: center;
                overflow: hidden; position: relative;
            }}
            canvas#particleCanvas {{
                position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                z-index: 1; pointer-events: none;
            }}
            .ui-layer {{
                position: relative; z-index: 2;
                display: flex; flex-direction: column; align-items: center; justify-content: center;
            }}
            .hud-orb {{
                position: relative; width: 240px; height: 240px;
                display: flex; align-items: center; justify-content: center; cursor: pointer;
            }}
            .ring-outer {{
                position: absolute; width: 100%; height: 100%; border-radius: 50%;
                border: 2px dashed rgba(56, 189, 248, 0.4);
                animation: spin 20s linear infinite;
            }}
            .ring-inner {{
                position: absolute; width: 78%; height: 78%; border-radius: 50%;
                border: 2px solid rgba(129, 140, 248, 0.5);
                box-shadow: 0 0 30px rgba(56, 189, 248, 0.3);
            }}
            .core-node {{
                width: 50%; height: 50%; border-radius: 50%;
                background: radial-gradient(circle, #38bdf8 0%, #0284c7 60%, #0369a1 100%);
                box-shadow: 0 0 50px rgba(56, 189, 248, 0.8);
                transition: all 0.3s ease;
            }}
            .hud-orb.speaking .core-node {{
                animation: pulse 0.8s ease-in-out infinite alternate;
                background: radial-gradient(circle, #818cf8 0%, #4f46e5 70%, #3730a3 100%);
                box-shadow: 0 0 80px rgba(129, 140, 248, 1);
            }}
            @keyframes spin {{ 100% {{ transform: rotate(360deg); }} }}
            @keyframes pulse {{ 0% {{ transform: scale(0.95); }} 100% {{ transform: scale(1.15); }} }}

            #dropZone {{
                position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
                background: rgba(2, 6, 23, 0.85); backdrop-filter: blur(12px);
                border: 3px dashed #38bdf8; z-index: 10;
                display: flex; align-items: center; justify-content: center;
                font-size: 1.5rem; color: #38bdf8; letter-spacing: 2px;
                opacity: 0; pointer-events: none; transition: opacity 0.2s ease;
            }}
            #dropZone.active {{ opacity: 1; pointer-events: all; }}
        </style>
    </head>
    <body>
        <canvas id="particleCanvas"></canvas>
        <div id="dropZone">Drop media or document files here to save in MongoDB vault</div>

        <div class="ui-layer">
            <div class="hud-orb" id="hudOrb" onclick="toggleMic()">
                <div class="ring-outer"></div>
                <div class="ring-inner"></div>
                <div class="core-node"></div>
            </div>
        </div>

        <script>
            const canvas = document.getElementById('particleCanvas');
            const ctx = canvas.getContext('2d');
            let particles = [];
            function resize() {{ canvas.width = window.innerWidth; canvas.height = window.innerHeight; }}
            window.addEventListener('resize', resize); resize();
            class Particle {{
                constructor() {{
                    this.x = Math.random() * canvas.width; this.y = Math.random() * canvas.height;
                    this.vx = (Math.random() - 0.5) * 0.7; this.vy = (Math.random() - 0.5) * 0.7;
                }}
                update() {{
                    this.x += this.vx; this.y += this.vy;
                    if (this.x < 0 || this.x > canvas.width) this.vx *= -1;
                    if (this.y < 0 || this.y > canvas.height) this.vy *= -1;
                }}
                draw() {{
                    ctx.beginPath(); ctx.arc(this.x, this.y, 1.5, 0, Math.PI * 2);
                    ctx.fillStyle = 'rgba(56, 189, 248, 0.4)'; ctx.fill();
                }}
            }}
            for (let i = 0; i < 55; i++) particles.push(new Particle());
            function render() {{
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                particles.forEach((p, i) => {{
                    p.update(); p.draw();
                    for (let j = i + 1; j < particles.length; j++) {{
                        const dist = Math.hypot(p.x - particles[j].x, p.y - particles[j].y);
                        if (dist < 100) {{
                            ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(particles[j].x, particles[j].y);
                            ctx.strokeStyle = `rgba(56, 189, 248, ${{0.15 * (1 - dist / 100)}})`;
                            ctx.stroke();
                        }}
                    }}
                }});
                requestAnimationFrame(render);
            }}
            render();

            let ws, currentAudio = null, userLocation = null, isPlayingAudio = false;
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if ("geolocation" in navigator) {{
                navigator.geolocation.getCurrentPosition((pos) => {{ userLocation = pos.coords.latitude + "," + pos.coords.longitude; }});
            }}

            function initWebSocket() {{
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                ws = new WebSocket(`${{protocol}}//${{window.location.host}}/ws`);
                ws.onmessage = (event) => {{
                    const payload = JSON.parse(event.data);
                    playNeuralAudio(payload.audio);
                }};
            }}
            initWebSocket();

            function startListeningSafely() {{
                if (!recognition || isPlayingAudio) return;
                try {{ recognition.start(); }} catch (e) {{}}
            }}

            if (SpeechRecognition) {{
                recognition = new SpeechRecognition();
                recognition.continuous = true;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onresult = (event) => {{
                    const speech = event.results[event.results.length - 1][0].transcript.trim();
                    if (!speech) return;
                    stopAudio();
                    if (ws && ws.readyState === WebSocket.OPEN) {{
                        ws.send(JSON.stringify({{ prompt: speech, location: userLocation }}));
                    }}
                }};

                recognition.onend = () => {{ if (!isPlayingAudio) setTimeout(startListeningSafely, 200); }};
                recognition.onerror = (event) => {{ if (event.error !== 'aborted' && !isPlayingAudio) setTimeout(startListeningSafely, 300); }};
                window.addEventListener('load', () => {{ startListeningSafely(); }});
            }}

            function stopAudio() {{
                if (currentAudio) {{ currentAudio.pause(); currentAudio.currentTime = 0; currentAudio = null; }}
                isPlayingAudio = false;
                document.getElementById('hudOrb').classList.remove('speaking');
            }}

            function toggleMic() {{ stopAudio(); startListeningSafely(); }}

            function playNeuralAudio(b64Data) {{
                stopAudio();
                if (recognition) {{ try {{ recognition.stop(); }} catch(e) {{}} }}
                isPlayingAudio = true;
                currentAudio = new Audio("data:audio/mp3;base64," + b64Data);
                document.getElementById('hudOrb').classList.add('speaking');
                currentAudio.onended = () => {{ isPlayingAudio = false; document.getElementById('hudOrb').classList.remove('speaking'); startListeningSafely(); }};
                currentAudio.onerror = () => {{ isPlayingAudio = false; document.getElementById('hudOrb').classList.remove('speaking'); startListeningSafely(); }};
                currentAudio.play().catch(err => {{ isPlayingAudio = false; document.getElementById('hudOrb').classList.remove('speaking'); startListeningSafely(); }});
            }}

            const dropZone = document.getElementById('dropZone');
            window.addEventListener('dragover', (e) => {{ e.preventDefault(); dropZone.classList.add('active'); }});
            window.addEventListener('dragleave', (e) => {{ if (e.clientX <= 0 || e.clientY <= 0) dropZone.classList.remove('active'); }});
            window.addEventListener('drop', async (e) => {{
                e.preventDefault();
                dropZone.classList.remove('active');
                if (e.dataTransfer.files.length > 0) {{
                    const file = e.dataTransfer.files[0];
                    const formData = new FormData();
                    formData.append('file', file);
                    formData.append('category', 'documents');
                    await fetch('/upload-pdf', {{ method: 'POST', body: formData }});
                    if (ws && ws.readyState === WebSocket.OPEN) {{
                        ws.send(JSON.stringify({{ prompt: "I uploaded " + file.name + " to my MongoDB document vault.", location: userLocation }}));
                    }}
                }}
            }});
        </script>
    </body>
    </html>
    """

# -------------------------------------------------------------
# 8. WEBSOCKET STREAMING & UPLOAD ROUTE
# -------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            prompt = data.get("prompt", "")
            location = data.get("location", None)

            reply_text = await process_autonomous_task(prompt, session_id, location)
            audio_b64 = await generate_speech_audio_b64(reply_text)
            
            await websocket.send_json({"audio": audio_b64, "text": reply_text})
    except WebSocketDisconnect: pass

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...), category: str = "documents"):
    file_bytes = await file.read()
    pdf_text = extract_text_from_pdf(file_bytes)
    await save_media_file(file.filename, "document", file_bytes, caption=pdf_text[:5000])
    return {"status": "ok"}
