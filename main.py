import os
import json
import httpx
import base64
import re
import asyncio
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
from supabase import create_client
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from tavily import TavilyClient
import motor.motor_asyncio

# Scheduler SDKs
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

app = FastAPI()

# -------------------------------------------------------------
# 1. ENVIRONMENT VARIABLES & CLIENT INITIALIZATION
# -------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
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

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI) if MONGODB_URI else None
mongo_db = mongo_client["aria_db"] if mongo_client else None
mongo_docs_col = mongo_db["documents"] if mongo_db is not None else None
mongo_memory_col = mongo_db["personal_memory"] if mongo_db is not None else None

CACHE_VOICES = []
PENDING_SECURITY_ACTIONS = {}
scheduler = AsyncIOScheduler()

# -------------------------------------------------------------
# 2. IN-MEMORY RAM CACHE & TEMPORAL ENGINE
# -------------------------------------------------------------
RAM_MEMORY_CACHE = [f"[PERSONAL_PROFILE]: User Full Name is {USER_FULL_NAME}"]
LAST_CACHE_UPDATE = 0

def get_current_temporal_context() -> str:
    """Provides precise real-time timestamps in UTC and IST."""
    now_utc = datetime.now(timezone.utc)
    ist_offset = timedelta(hours=5, minutes=30)
    now_ist = now_utc + ist_offset
    
    return f"""
LIVE TEMPORAL CONTEXT:
- Date & Time (IST): {now_ist.strftime('%A, %B %d, %Y at %I:%M:%S %p IST')}
- Date & Time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}
"""

async def update_ram_cache():
    """Fetches long-term memory into RAM to eliminate DB latency."""
    global RAM_MEMORY_CACHE, LAST_CACHE_UPDATE
    now = datetime.now().timestamp()
    if now - LAST_CACHE_UPDATE < 60 and len(RAM_MEMORY_CACHE) > 1:
        return RAM_MEMORY_CACHE

    facts = [f"[PERSONAL_PROFILE]: User Full Name is {USER_FULL_NAME}"]
    if mongo_memory_col is not None:
        try:
            cursor = mongo_memory_col.find({})
            async for doc in cursor:
                fact_entry = f"[{doc.get('category', 'MEMORY').upper()}]: {doc.get('fact', '')}"
                if fact_entry not in facts:
                    facts.append(fact_entry)
        except Exception: pass

    RAM_MEMORY_CACHE = facts
    LAST_CACHE_UPDATE = now
    return RAM_MEMORY_CACHE

# -------------------------------------------------------------
# 3. DYNAMIC SMART STORAGE & FAST WEATHER ENGINE
# -------------------------------------------------------------
def get_stored_user_voice() -> str:
    if supabase:
        try:
            res = supabase.table("personal_memory").select("fact").eq("category", "user_voice_preference").execute()
            if res.data and len(res.data) > 0:
                return res.data[0]["fact"].strip()
        except Exception: pass
    return "en-GB-RyanNeural"

def save_stored_user_voice(voice_short_name: str):
    if supabase:
        try:
            supabase.table("personal_memory").delete().eq("category", "user_voice_preference").execute()
            supabase.table("personal_memory").insert({
                "category": "user_voice_preference",
                "fact": voice_short_name
            }).execute()
        except Exception: pass

async def save_memory_fact(category: str, fact: str) -> str:
    cat = category.lower().strip()
    fact_str = fact.strip()

    RAM_MEMORY_CACHE.append(f"[{cat.upper()}]: {fact_str}")

    async def _async_persisters():
        if mongo_memory_col is not None:
            try: await mongo_memory_col.insert_one({"category": cat, "fact": fact_str})
            except Exception: pass
        if supabase:
            try: supabase.table("personal_memory").insert({"category": cat, "fact": fact_str}).execute()
            except Exception: pass

    asyncio.create_task(_async_persisters())
    return "Understood, Sir. Duly recorded in your personal vault."

async def save_binary_document(file_name: str, doc_label: str, raw_bytes: bytes, text_preview: str):
    b64_payload = base64.b64encode(raw_bytes).decode('utf-8')

    if mongo_docs_col is not None:
        try:
            await mongo_docs_col.insert_one({
                "file_name": file_name,
                "label": doc_label.lower().strip(),
                "b64_payload": b64_payload,
                "text_preview": text_preview[:1500]
            })
        except Exception as e: print(f"[Doc Save Error]: {e}")

    await save_memory_fact("documents", f"DOCUMENT '{doc_label}' (File: {file_name}): {text_preview[:1500]}")
    return f"Document '{file_name}' successfully secured in your vault, Sir."

async def purge_memory_category(category: str) -> str:
    cat = category.lower().strip()
    if mongo_memory_col is not None:
        try: await mongo_memory_col.delete_many({"category": cat})
        except Exception: pass
    if mongo_docs_col is not None and cat in ["documents", "exams", "stored_files"]:
        try: await mongo_docs_col.delete_many({})
        except Exception: pass
    if supabase:
        try: supabase.table("personal_memory").delete().eq("category", cat).execute()
        except Exception: pass

    global RAM_MEMORY_CACHE
    RAM_MEMORY_CACHE = [f"[PERSONAL_PROFILE]: User Full Name is {USER_FULL_NAME}"]
    return f"All records associated with '{category}' have been purged, Sir."

def fetch_web_search(query: str) -> str:
    if not tavily_client: return ""
    try:
        res = tavily_client.search(query=query, max_results=2)
        results = [f"- {item['title']}: {item['content'][:150]}" for item in res.get("results", [])]
        return "\nREAL-TIME WEB INTELLIGENCE:\n" + "\n".join(results) + "\n"
    except Exception: pass
    return ""

async def fetch_weather_by_coords(location_info: str = "17.6868,83.2185") -> str:
    """Fetches instant live weather with 2-second strict timeout."""
    if not location_info or "," not in location_info:
        location_info = "17.6868,83.2185" # Default to Visakhapatnam
    try:
        lat, lon = location_info.split(",")
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=2.0)
            if res.status_code == 200:
                data = res.json().get("current_weather", {})
                return f"\nLIVE ATMOSPHERIC DATA: Temperature {data.get('temperature')}°C, Wind Speed {data.get('windspeed')} km/h.\n"
    except Exception: pass
    return ""

# -------------------------------------------------------------
# 4. GMAIL & GOOGLE CALENDAR ENGINE
# -------------------------------------------------------------
async def fetch_recent_emails(max_results: int = 5) -> str:
    try:
        def _get_gmail():
            if GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN:
                creds = Credentials(
                    token=None,
                    refresh_token=GMAIL_REFRESH_TOKEN,
                    client_id=GMAIL_CLIENT_ID,
                    client_secret=GMAIL_CLIENT_SECRET,
                    token_uri="https://oauth2.googleapis.com/token",
                    scopes=['https://www.googleapis.com/auth/gmail.readonly']
                )
                if not creds.valid:
                    creds.refresh(GoogleRequest())
                service = build('gmail', 'v1', credentials=creds)
            elif GOOGLE_SERVICE_ACCOUNT_JSON:
                creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
                creds = service_account.Credentials.from_service_account_info(
                    creds_info, scopes=['https://www.googleapis.com/auth/gmail.readonly']
                )
                service = build('gmail', 'v1', credentials=creds)
            else:
                return "Gmail API authorization pending."

            results = service.users().messages().list(userId='me', maxResults=max_results).execute()
            messages = results.get('messages', [])
            if not messages:
                return "No unread communications in your inbox, Sir."

            summaries = []
            for msg in messages:
                m_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                snippet = m_data.get('snippet', '')
                headers = m_data.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
                sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
                summaries.append(f"- [From: {sender}] Subject: '{subject}' | Snippet: {snippet[:120]}")

            return "\n".join(summaries)

        return await asyncio.to_thread(_get_gmail)
    except Exception as e:
        print(f"[Gmail Error]: {e}")
        return "Gmail service temporarily unavailable."

async def fetch_google_calendar_events() -> str:
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return "Calendar service not configured."
    try:
        def _get_calendar():
            creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
            creds = service_account.Credentials.from_service_account_info(
                creds_info, scopes=['https://www.googleapis.com/auth/calendar.readonly']
            )
            service = build('calendar', 'v3', credentials=creds)

            now = datetime.now(timezone.utc)
            start_of_day = now.replace(hour=0, minute=0, second=0).isoformat()
            end_of_day = now.replace(hour=23, minute=59, second=59).isoformat()

            events_result = service.events().list(
                calendarId='primary', timeMin=start_of_day, timeMax=end_of_day,
                singleEvents=True, orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            if not events:
                return "Your schedule is completely clear for today, Sir."

            return "\n".join([f"- {e.get('summary')} at {e['start'].get('dateTime', e['start'].get('date'))}" for e in events])

        return await asyncio.to_thread(_get_calendar)
    except Exception as e:
        print(f"[Calendar Error]: {e}")
        return "Calendar agenda temporarily unavailable."

async def send_daily_morning_brief():
    if not TELEGRAM_TOKEN or not ALLOWED_TELEGRAM_USER_ID: return

    calendar_agenda = await fetch_google_calendar_events()
    emails_summary = await fetch_recent_emails(max_results=3)
    weather_info = await fetch_weather_by_coords("17.6868,83.2185")
    cached_facts = await update_ram_cache()
    temporal_str = get_current_temporal_context()

    brief_prompt = f"""Synthesize a high-IQ J.A.R.V.I.S. morning briefing for Sir ({USER_FULL_NAME}).
{temporal_str}
WEATHER: {weather_info}
SCHEDULED AGENDA: {calendar_agenda}
INBOX PREVIEW: {emails_summary}
VAULT CONTEXT: {cached_facts}

DIRECTIVES:
- Open with a dignified morning greeting addressing him as 'Sir'.
- Provide a crisp bulleted summary covering current date/time, weather, calendar obligations, and active engineering project status (TaskFlow, WealthFlow AI).
- Close with a sharp motivational focus statement."""

    brief_text = await process_autonomous_task(brief_prompt, "system_cron")

    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": ALLOWED_TELEGRAM_USER_ID, "text": brief_text}
        )

@app.on_event("startup")
async def start_scheduler():
    await update_ram_cache()
    trigger = CronTrigger(hour=1, minute=30, timezone="UTC") # 07:00 AM IST
    scheduler.add_job(send_daily_morning_brief, trigger, id="morning_brief_job", replace_existing=True)
    scheduler.start()
    print("[J.A.R.V.I.S. Core]: Online with high-speed temporal & memory engine.")

# -------------------------------------------------------------
# 5. SUB-SECOND FIRST-TOKEN LLM ENGINE (<300MS)
# -------------------------------------------------------------
async def process_autonomous_task(user_text: str, session_id: str, location_info: str = None) -> str:
    cmd = user_text.lower().strip()

    # 1. PENDING SECURITY ACTIONS
    if session_id in PENDING_SECURITY_ACTIONS:
        pending = PENDING_SECURITY_ACTIONS[session_id]
        if any(k in cmd for k in ["yes", "proceed", "authorize", "do it", "confirm", "sure", "ok"]):
            del PENDING_SECURITY_ACTIONS[session_id]
            if pending["type"] == "purge_category":
                return await purge_memory_category(pending["category"])
        elif any(k in cmd for k in ["no", "cancel", "stop", "abort", "don't", "dont"]):
            del PENDING_SECURITY_ACTIONS[session_id]
            return "Security action aborted, Sir."
        else:
            return f"Awaiting authorization, Sir. Shall I purge all {pending['category']} records?"

    # 2. GMAIL INTENT DETECTOR
    if any(k in cmd for k in ["check email", "read emails", "my mails", "summarize emails", "check my inbox", "important mail"]):
        email_data = await fetch_recent_emails(max_results=5)
        user_text = f"Here are my recent inbox emails:\n{email_data}\n\nPlease summarize these concise briefs for me, Sir."

    # 3. AUTO-SAVER (Instant RAM capture)
    auto_save_triggers = ["my name is", "my dob is", "i was born", "my college is", "i live in", "remember", "save this", "i am"]
    if any(trigger in cmd for trigger in auto_save_triggers):
        await save_memory_fact("personal_profile", user_text)

    # 4. TEMPORAL & WEATHER ENGINE INJECTION
    temporal_context = get_current_temporal_context()
    weather_context = ""
    if any(kw in cmd for kw in ["weather", "temperature", "rain", "forecast", "climate"]):
        weather_context = await fetch_weather_by_coords(location_info or "17.6868,83.2185")

    search_context = fetch_web_search(user_text) if any(kw in cmd for kw in ["search", "latest", "news", "who is", "what is", "price"]) else ""
    cached_facts = await update_ram_cache()
    memory_context = "\nVAULT CONTEXT:\n" + "\n".join(cached_facts) if cached_facts else ""

    system_prompt = f"""You are {ASSISTANT_NAME}, an autonomous, hyper-intelligent neural AI assistant inspired by J.A.R.V.I.S.

{temporal_context}
{weather_context}
{memory_context}
{search_context}

CORE DIRECTIVES:
- TONALITY: Impeccably polite, professional, calm, articulate, and composed.
- GREETING RULES: NEVER use informal, local, or regional greetings like "Namesthe", "Namaskaram", "Hey there". Use natural, professional J.A.R.V.I.S. greetings ("Good day, Sir", "At your service, Sir").
- ADDRESS: Address the user as 'Sir' or 'Mr. Saketh'.
- EFFICIENCY: Keep conversational responses brief (1-2 sentences max), highly intelligent, and direct to the point."""

    # Fast Primary Stream via Groq Llama-3.3-70b (<300ms)
    if groq_client:
        try:
            def _groq_sync():
                comp = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
                    temperature=0.3, max_tokens=180
                )
                return comp.choices[0].message.content
            reply = await asyncio.to_thread(_groq_sync)
            if reply and len(reply.strip()) > 0:
                return reply.strip()
        except Exception as e:
            print(f"[Groq Error]: {e}")

    # Fallback to Gemini 2.0 Flash
    if gemini_client:
        try:
            def _gemini_sync():
                res = gemini_client.models.generate_content(
                    model="gemini-2.0-flash", contents=f"{system_prompt}\n\nSir: {user_text}\nARIA:"
                )
                return res.text
            reply = await asyncio.to_thread(_gemini_sync)
            if reply and len(reply.strip()) > 0:
                return reply.strip()
        except Exception as e:
            print(f"[Gemini Error]: {e}")

    return "All neural systems operational, Sir."

# -------------------------------------------------------------
# 6. INSTANT TELEGRAM WEBHOOK (DIRECT FILE DISPATCH)
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

        if not chat_id: return {"status": "no chat_id"}

        # Security Lock
        if ALLOWED_TELEGRAM_USER_ID and str(from_user_id) != str(ALLOWED_TELEGRAM_USER_ID):
            return {"status": "unauthorized"}

        # 1. Isolated /start Command
        if text.lower() == "/start":
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": "Good day, Sir. I am ARIA, your personal neural assistant. All systems online."}
                )
            return {"status": "ok"}

        # 2. Document Upload Handling
        if document:
            file_id = document.get("file_id")
            file_name = document.get("file_name", "document.pdf")

            async with httpx.AsyncClient() as client:
                file_info_res = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}")
                file_path = file_info_res.json().get("result", {}).get("file_path")
                raw_bytes_res = await client.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}")
                raw_bytes = raw_bytes_res.content

            extracted_text = extract_text_from_pdf(raw_bytes) if file_name.lower().endswith(".pdf") else "Binary Document Stored"
            save_reply = await save_binary_document(file_name, file_name, raw_bytes, extracted_text)

            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": save_reply})
            return {"status": "ok"}

        # 3. DIRECT FILE RETRIEVAL (Bypasses LLM — Sub-2 Second Speed)
        if text:
            cmd = text.lower()
            file_triggers = [
                "give my resume", "send my resume", "get resume", "give resume", "send resume",
                "give that document", "save in my phone", "send document", "send pdf",
                "download my resume", "give me the pdf", "send file"
            ]
            
            if any(trigger in cmd for trigger in file_triggers):
                target_doc = None
                if mongo_docs_col is not None:
                    target_doc = await mongo_docs_col.find_one({}, sort=[("_id", -1)])

                async with httpx.AsyncClient() as client:
                    if not target_doc:
                        await client.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                            json={"chat_id": chat_id, "text": "I possess your profile details in text memory, Sir, but no binary PDF is saved in the vault yet. Please upload your resume PDF once."}
                        )
                    else:
                        target_name = target_doc.get("file_name", "resume.pdf")
                        raw_file_bytes = base64.b64decode(target_doc["b64_payload"])
                        
                        await client.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                            data={"chat_id": chat_id, "caption": f"Here is your document: '{target_name}' Sir."},
                            files={"document": (target_name, raw_file_bytes, "application/octet-stream")}
                        )
                return {"status": "ok"}

            # 4. Fast Conversational AI Response
            reply_text = await process_autonomous_task(text, str(chat_id))
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": reply_text})
            return {"status": "ok"}

    except Exception as e:
        print(f"[Webhook Error]: {e}")

    return {"status": "ok"}

@app.post("/set-telegram-webhook")
async def set_telegram_webhook(req: Request):
    data = await req.json()
    webhook_url = data.get("url") + "/telegram-webhook"
    async with httpx.AsyncClient() as client:
        res = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}")
        return res.json()

# -------------------------------------------------------------
# 7. SPEECH & PDF ENGINE
# -------------------------------------------------------------
async def generate_speech_audio_b64(text: str, selected_voice: str = None) -> str:
    if not selected_voice: selected_voice = get_stored_user_voice()
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

# -------------------------------------------------------------
# 8. API ROUTES & FRONTEND HUD
# -------------------------------------------------------------
@app.get("/api/voices")
async def get_voices_list():
    global CACHE_VOICES
    if not CACHE_VOICES:
        try:
            all_voices = await edge_tts.list_voices()
            CACHE_VOICES = [
                {
                    "shortName": v["ShortName"],
                    "gender": v["Gender"],
                    "locale": v["Locale"],
                    "friendlyName": f"{v['ShortName'].split('-')[-1].replace('Neural','')} ({v['Locale']})"
                }
                for v in all_voices
            ]
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    active_voice = get_stored_user_voice()
    return {"voices": CACHE_VOICES, "activeVoice": active_voice}

@app.post("/api/set-voice")
async def set_voice_preference(req: Request):
    data = await req.json()
    voice = data.get("voice", "en-GB-RyanNeural")
    save_stored_user_voice(voice)
    return {"status": "success", "voice": voice}

@app.head("/health")
@app.get("/health")
def health_check():
    return JSONResponse(status_code=200, content={"status": "online", "system": "ARIA AI"})

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

            .settings-btn {{
                position: absolute; top: 25px; right: 25px; z-index: 5;
                background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(56, 189, 248, 0.3);
                color: #38bdf8; font-size: 1.2rem; padding: 10px 14px; border-radius: 50%;
                cursor: pointer; backdrop-filter: blur(8px);
            }}

            #voiceModal {{
                position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
                background: rgba(2, 6, 23, 0.92); backdrop-filter: blur(16px);
                z-index: 100; display: none; flex-direction: column;
                align-items: center; justify-content: center; padding: 20px;
            }}
            #voiceModal.active {{ display: flex; }}
            .modal-content {{
                width: 100%; max-width: 480px; height: 80vh;
                background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(56, 189, 248, 0.3);
                border-radius: 20px; padding: 20px; display: flex; flex-direction: column;
            }}
            .modal-header {{
                display: flex; justify-content: space-between; align-items: center;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding-bottom: 12px; margin-bottom: 15px;
            }}
            .search-box {{
                width: 100%; padding: 10px 15px; border-radius: 10px;
                border: 1px solid rgba(56, 189, 248, 0.3); background: rgba(30, 41, 59, 0.8);
                color: #f8fafc; margin-bottom: 15px; font-size: 0.9rem;
            }}
            .voice-list {{
                flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px;
            }}
            .voice-item {{
                padding: 12px 16px; border-radius: 12px;
                background: rgba(30, 41, 59, 0.5); border: 1px solid rgba(255, 255, 255, 0.05);
                display: flex; justify-content: space-between; align-items: center;
                cursor: pointer; transition: all 0.2s;
            }}
            .voice-item:hover, .voice-item.selected {{
                background: rgba(56, 189, 248, 0.2); border-color: #38bdf8;
            }}

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
        <button class="settings-btn" onclick="openVoiceModal()">⚙️</button>
        <div id="dropZone">Drop document files here to save in MongoDB vault</div>

        <div class="ui-layer">
            <div class="hud-orb" id="hudOrb" onclick="toggleMic()">
                <div class="ring-outer"></div>
                <div class="ring-inner"></div>
                <div class="core-node"></div>
            </div>
        </div>

        <div id="voiceModal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3 style="color: #38bdf8; letter-spacing: 1px;">Neural Voice Catalog</h3>
                    <button style="background: none; border: none; color: #64748b; font-size: 1.5rem; cursor: pointer;" onclick="closeVoiceModal()">✕</button>
                </div>
                <input type="text" id="voiceSearch" class="search-box" placeholder="Search language or voice (e.g. Telugu, Ryan, India)..." oninput="filterVoices()">
                <div class="voice-list" id="voiceList">
                    <div style="color: #64748b; text-align: center; margin-top: 20px;">Loading catalog...</div>
                </div>
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

            let ws, currentAudio = null, userLocation = null, allVoices = [], activeVoice = "", isPlayingAudio = false;
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
                        ws.send(JSON.stringify({{ prompt: speech, location: userLocation, voice: activeVoice }}));
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

            async function openVoiceModal() {{
                document.getElementById('voiceModal').classList.add('active');
                if (allVoices.length === 0) {{
                    const res = await fetch('/api/voices');
                    const data = await res.json();
                    allVoices = data.voices; activeVoice = data.activeVoice;
                }}
                renderVoices(allVoices);
            }}

            function closeVoiceModal() {{ document.getElementById('voiceModal').classList.remove('active'); }}

            function renderVoices(voices) {{
                const listContainer = document.getElementById('voiceList');
                listContainer.innerHTML = "";
                voices.slice(0, 100).forEach(v => {{
                    const isSelected = v.shortName === activeVoice;
                    const item = document.createElement('div');
                    item.className = `voice-item ${{isSelected ? 'selected' : ''}}`;
                    item.innerHTML = `<div><div style="font-weight: 600; color: #e2e8f0;">${{v.friendlyName}}</div><div style="font-size: 0.75rem; color: #64748b;">${{v.shortName}}</div></div><span style="font-size: 0.8rem; color: #38bdf8;">${{v.gender}}</span>`;
                    item.onclick = () => selectVoice(v.shortName);
                    listContainer.appendChild(item);
                }});
            }}

            function filterVoices() {{
                const q = document.getElementById('voiceSearch').value.toLowerCase();
                const filtered = allVoices.filter(v => v.shortName.toLowerCase().includes(q) || v.locale.toLowerCase().includes(q) || v.friendlyName.toLowerCase().includes(q));
                renderVoices(filtered);
            }}

            async function selectVoice(shortName) {{
                activeVoice = shortName;
                renderVoices(allVoices);
                await fetch('/api/set-voice', {{ method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{ voice: shortName }}) }});
                closeVoiceModal();
                if (ws && ws.readyState === WebSocket.OPEN) {{
                    ws.send(JSON.stringify({{ prompt: "Switched voice to " + shortName, location: userLocation, voice: activeVoice }}));
                }}
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
                        ws.send(JSON.stringify({{ prompt: "I uploaded " + file.name + " to my MongoDB document vault.", location: userLocation, voice: activeVoice }}));
                    }}
                }}
            }});
        </script>
    </body>
    </html>
    """

# -------------------------------------------------------------
# 9. WEBSOCKET STREAMING & API ENDPOINTS
# -------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = id(websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            prompt = data.get("prompt", "")
            location = data.get("location", None)
            selected_voice = data.get("voice", None)

            reply_text = await process_autonomous_task(prompt, str(session_id), location)
            audio_b64 = await generate_speech_audio_b64(reply_text, selected_voice)
            
            await websocket.send_json({"audio": audio_b64, "text": reply_text})
    except WebSocketDisconnect:
        if str(session_id) in PENDING_SECURITY_ACTIONS:
            del PENDING_SECURITY_ACTIONS[str(session_id)]

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...), category: str = "documents"):
    file_bytes = await file.read()
    pdf_text = extract_text_from_pdf(file_bytes)
    await save_binary_document(file.filename, file.filename, file_bytes, pdf_text)
    return {"status": "ok"}
