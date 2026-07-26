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
# 2. SANITIZATION, ENCRYPTION & TEMPORAL ENGINE
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

def extract_text_from_pdf(file_bytes: bytes, password: str = None) -> tuple[str, bool]:
    """Extracts text from PDF, returning (text, is_encrypted)."""
    try:
        reader = PdfReader(BytesIO(file_bytes))
        if reader.is_encrypted:
            if password:
                try:
                    decrypt_success = reader.decrypt(password)
                    if not decrypt_success:
                        return "[INVALID_PASSWORD]", True
                except Exception:
                    return "[INVALID_PASSWORD]", True
            else:
                return "[ENCRYPTED_PDF_LOCKED]", True

        text = "".join([page.extract_text() or "" for page in reader.pages]).strip()
        return text, False
    except Exception as e:
        return f"[PDF Parsing Error: {str(e)}]", False

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

            chat_cursor = mongo_chats_col.find({}).sort("_id", -1).limit(6)
            chat_docs = await chat_cursor.to_list(length=6)
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
# 3. DIRECT FILE DISPATCH, ENCRYPTION & DECRYPTION TOOLS
# -------------------------------------------------------------
async def send_file_from_vault(file_query: str, chat_id: str) -> str:
    """Dispatches and uploads binary PDF file directly via Telegram."""
    if mongo_media_col is None:
        return "Vault database is currently offline, Sir."

    try:
        query_str = file_query.strip() if file_query else ""
        if not query_str:
            target_doc = await mongo_media_col.find_one({"media_type": "document"}, sort=[("_id", -1)])
        else:
            q_regex = re.compile(query_str, re.IGNORECASE)
            target_doc = await mongo_media_col.find_one({"$or": [{"file_name": q_regex}, {"caption": q_regex}]})

        if not target_doc:
            return f"I searched your vault, Sir, but could not locate any document matching '{file_query}'."

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
        return f"Encountered an issue dispatching document for query '{file_query}', Sir."

async def query_document_vault(doc_keyword: str, specific_question: str) -> dict:
    """Deep document reading tool: Checks encryption state and retrieves extracted text."""
    if mongo_media_col is None: return {"status": "error", "message": "Document vault unavailable, Sir."}
    try:
        q_regex = re.compile(doc_keyword.strip(), re.IGNORECASE) if doc_keyword else None
        filter_clause = {"$or": [{"file_name": q_regex}, {"caption": q_regex}]} if q_regex else {}
        target_doc = await mongo_media_col.find_one(filter_clause, sort=[("_id", -1)])

        if not target_doc:
            return {"status": "error", "message": f"No document matching '{doc_keyword}' was found in your vault, Sir."}

        # Check if file is encrypted and locked
        if target_doc.get("is_encrypted") and target_doc.get("caption") == "[ENCRYPTED_PDF_LOCKED]":
            return {
                "status": "encrypted",
                "file_name": target_doc.get("file_name"),
                "doc_id": str(target_doc.get("_id"))
            }

        content = target_doc.get("caption", "").strip()
        return {
            "status": "success",
            "file_name": target_doc.get("file_name"),
            "text": content[:5000]
        }
    except Exception as e:
        return {"status": "error", "message": f"Document query error: {str(e)}"}

async def unlock_encrypted_pdf(doc_id_or_name: str, password: str) -> tuple[str, bool]:
    """Decrypts a stored PDF document with user-provided password."""
    if mongo_media_col is None: return "Database offline.", False
    try:
        q_regex = re.compile(doc_id_or_name.strip(), re.IGNORECASE)
        target_doc = await mongo_media_col.find_one({"$or": [{"file_name": q_regex}, {"caption": q_regex}]})
        
        if not target_doc: return "Document not found.", False

        raw_bytes = base64.b64decode(target_doc["b64_payload"])
        decrypted_text, is_still_encrypted = extract_text_from_pdf(raw_bytes, password=password)

        if decrypted_text == "[INVALID_PASSWORD]":
            return "Invalid password provided, Sir. Access denied.", False

        # Update document in MongoDB with decrypted text
        await mongo_media_col.update_one(
            {"_id": target_doc["_id"]},
            {"$set": {"caption": decrypted_text, "is_encrypted": False}}
        )

        return decrypted_text, True
    except Exception as e:
        return f"Decryption failed: {str(e)}", False

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

async def save_media_file(file_name: str, media_type: str, raw_bytes: bytes, caption: str = "", is_encrypted: bool = False):
    b64_payload = base64.b64encode(raw_bytes).decode('utf-8')
    if mongo_media_col is not None:
        try:
            await mongo_media_col.insert_one({
                "file_name": file_name, "media_type": media_type,
                "caption": caption.lower().strip(), "b64_payload": b64_payload,
                "is_encrypted": is_encrypted,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except Exception: pass

    await save_memory_fact("media_vault", f"SAVED {media_type.upper()}: '{file_name}' | Status: {'ENCRYPTED_LOCKED' if is_encrypted else 'PARSED_OK'}")
    status_msg = "is encrypted and secured under Privacy Protocol." if is_encrypted else "fully parsed and secured in your vault."
    return f"Document '{file_name}' {status_msg}, Sir."

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
            "description": "Dispatches and uploads the actual binary PDF or media file to Telegram ONLY when the user explicitly requests to send, download, or get a PDF file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_query": {"type": "string", "description": "Document name e.g. 'aadhar', 'resume', 'certificate'"}
                },
                "required": ["file_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_document_vault",
            "description": "Reads text content inside uploaded PDFs to answer specific questions or extract details from stored documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_keyword": {"type": "string", "description": "Keyword identifying which document to search e.g. 'aadhar', 'resume', 'proposal'"},
                    "specific_question": {"type": "string", "description": "The exact detail or question asked about the document content"}
                },
                "required": ["doc_keyword", "specific_question"]
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
                "required": ["task_desc"]
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
            "name": "get_system_diagnostics",
            "description": "Audits assistant health, database metrics, security incidents, and active tasks.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

async def process_autonomous_task(user_text: str, session_id: str, location_info: str = None) -> str:
    cmd = user_text.lower().strip()

    # Conversational Bypass
    if cmd in ["hello", "hi", "hey", "hola", "start", "/start"]:
        return "At your service, Sir. How may I assist you today?"

    # 1. PERMISSION & ENCRYPTION PASSWORD GATE EVALUATION
    if session_id in PENDING_SECURITY_ACTIONS:
        pending = PENDING_SECURITY_ACTIONS[session_id]
        action_type = pending.get("type")

        # Handle Password Input for Encrypted PDF
        if action_type == "unlock_pdf":
            # Extract password from response (e.g. "yes password is 19991234" or "19991234")
            pwd_match = re.search(r'\b([A-Za-z0-9@#$_]{4,25})\b', user_text.strip())
            password_input = pwd_match.group(1) if pwd_match else user_text.strip()

            target_doc_keyword = pending["data"]["doc_keyword"]
            original_q = pending["data"]["original_q"]

            decrypted_text, success = await unlock_encrypted_pdf(target_doc_keyword, password_input)
            if not success:
                return f"Security Alert: Decryption failed for '{target_doc_keyword}', Sir. Please state 'Yes' and provide the correct document password."

            del PENDING_SECURITY_ACTIONS[session_id]

            # Generate QA answer using newly decrypted text
            qa_prompt = f"""User Request: '{original_q}'

DECRYPTED DOCUMENT TEXT FROM VAULT:
{decrypted_text[:5000]}

MANDATORY PRIVACY DIRECTIVE:
- Answer the user's specific request using the document content above.
- Address the user as Sir or Master."""

            qa_comp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": qa_prompt}],
                temperature=0.2, max_tokens=250
            )
            return qa_comp.choices[0].message.content.strip()

        # Handle standard Security Confirmation
        if any(k in cmd for k in ["yes", "proceed", "authorize", "do it", "confirm", "sure", "agree", "allow", "grant"]):
            del PENDING_SECURITY_ACTIONS[session_id]
            if action_type == "purge_vault":
                return await purge_all_vault_data()
            elif action_type == "send_file":
                return await send_file_from_vault(pending["data"].get("file_query", ""), session_id)

        elif any(k in cmd for k in ["no", "cancel", "stop", "abort", "don't", "dont", "deny", "refuse"]):
            del PENDING_SECURITY_ACTIONS[session_id]
            return "Security authorization withheld. Action canceled, Sir."

    # 2. TRIGGER PERMISSION CHECK FOR SENSITIVE COMMANDS
    if any(k in cmd for k in ["delete all data", "clear database", "purge vault", "erase everything"]):
        PENDING_SECURITY_ACTIONS[session_id] = {"type": "purge_vault"}
        return "Security Protocol Alert: This will permanently wipe all database records, schedules, and vault data. Do you grant authorization to proceed, Sir?"

    # 3. STANDARD HYBRID LLM TOOL EXECUTION
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

CRITICAL ROUTING & PRIVACY DIRECTIVES:
1. ROUTING DISTINCTION:
   * Call 'send_file_from_vault' ONLY when the user explicitly asks to receive, download, or dispatch a PDF/document file.
   * Call 'query_document_vault' when the user asks a question about information INSIDE a document.
2. ADDRESS & SALUTATIONS: Address the user as 'Sir' or 'Master'. Keep responses concise (1-2 sentences max), articulate, and sharp."""

    reply_text = ""

    if groq_client:
        try:
            def _groq_exec():
                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
                    tools=GROQ_TOOLS,
                    tool_choice="auto",
                    temperature=0.2, max_tokens=300
                )
                return response.choices[0].message

            msg = await asyncio.to_thread(_groq_exec)

            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

                    if fn_name == "send_file_from_vault":
                        q_term = fn_args.get("file_query", "")
                        if not q_term:
                            for term in ["resume", "certificate", "cs50", "passport", "guide", "aadhar"]:
                                if term in cmd: q_term = term; break
                        reply_text = await send_file_from_vault(q_term, session_id)

                    elif fn_name == "query_document_vault":
                        doc_keyword = fn_args.get("doc_keyword", user_text)
                        specific_q = fn_args.get("specific_question", user_text)
                        doc_res = await query_document_vault(doc_keyword, specific_q)

                        # Check if target document is encrypted and locked
                        if doc_res.get("status") == "encrypted":
                            PENDING_SECURITY_ACTIONS[session_id] = {
                                "type": "unlock_pdf",
                                "data": {
                                    "doc_keyword": doc_keyword,
                                    "original_q": user_text
                                }
                            }
                            return f"Privacy Protocol Alert: Document '{doc_res.get('file_name')}' is password-protected. Do you grant authorization to access it? Please state 'Yes' and provide the document password, Sir."

                        if doc_res.get("status") == "error":
                            reply_text = doc_res.get("message")
                        else:
                            qa_prompt = f"""User Request: '{user_text}'

DOCUMENT TEXT FROM VAULT:
{doc_res.get('text')}

MANDATORY PRIVACY DIRECTIVE:
- Answer the user's specific request using the document content above.
- Address the user as Sir or Master."""

                            qa_comp = groq_client.chat.completions.create(
                                model="llama-3.3-70b-versatile",
                                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": qa_prompt}],
                                temperature=0.2, max_tokens=250
                            )
                            reply_text = qa_comp.choices[0].message.content.strip()

                    elif fn_name == "create_time_reminder":
                        reply_text = await create_time_reminder(fn_args.get("minutes", 5), fn_args.get("task_desc", "Task"))
                    elif fn_name == "save_scheduled_task":
                        reply_text = await save_scheduled_task(fn_args.get("task"), fn_args.get("timing"))
                    elif fn_name == "get_system_diagnostics":
                        reply_text = await get_system_diagnostics()

            elif msg.content:
                reply_text = msg.content.strip()

        except Exception as e:
            print(f"[Groq Execution Error]: {e}")

    if not reply_text and gemini_client:
        try:
            def _gemini_sync():
                res = gemini_client.models.generate_content(
                    model="gemini-2.0-flash", contents=f"{system_prompt}\n\nUser: {user_text}\nARIA:"
                )
                return res.text
            reply = await asyncio.to_thread(_gemini_sync)
            if reply and len(reply.strip()) > 0: reply_text = reply.strip()
        except Exception as e: print(f"[Gemini Error]: {e}")

    if not reply_text:
        reply_text = "At your service, Sir. All neural systems operational."

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

            extracted_text, is_encrypted = extract_text_from_pdf(raw_bytes) if default_name.lower().endswith(".pdf") else ("Binary File", False)
            save_reply = await save_media_file(default_name, media_type, raw_bytes, caption=extracted_text, is_encrypted=is_encrypted)
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
    print("[J.A.R.V.I.S. Encrypted Vault & Permission Engine]: Online and Synced.")

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

@app.head("/health")
@app.get("/health")
def health_check():
    return JSONResponse(status_code=200, content={"status": "online", "database": "MongoDB Atlas", "system": "ARIA Encrypted Vault Engine Active"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_webapp():
    return f"<h1>ARIA Encrypted Vault Core Online</h1>"

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
    extracted_text, is_encrypted = extract_text_from_pdf(file_bytes)
    await save_media_file(file.filename, "document", file_bytes, caption=extracted_text[:5000], is_encrypted=is_encrypted)
    return {"status": "ok"}
