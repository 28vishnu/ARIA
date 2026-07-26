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
from docx import Document
import openpyxl
import edge_tts

# Provider SDKs
from groq import Groq
from google import genai
from google.genai import types
from tavily import TavilyClient
import motor.motor_asyncio

# ChromaDB SDK (No local sentence-transformers)
import chromadb

# Scheduler SDKs
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

app = FastAPI()

# -------------------------------------------------------------
# 1. LAZY-LOADED CLIENTS & ENVIRONMENT INITIALIZATION
# -------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_TELEGRAM_USER_ID = os.getenv("ALLOWED_TELEGRAM_USER_ID")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

ASSISTANT_NAME = "ARIA"
USER_FULL_NAME = "N. Vishnu Saketh"

RAM_MEMORY_CACHE = [f"[PERSONAL_PROFILE]: User Full Name is {USER_FULL_NAME}"]
RAM_SCHEDULE_CACHE = []
RAM_RECENT_CHATS = []
LAST_CACHE_UPDATE = 0
LAST_USER_INTERACTION_TIME = datetime.now(timezone.utc)
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
                MONGODB_URI,
                tlsCAFile=certifi.where(),
                tlsInsecure=True,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000
            )
        except Exception as e:
            print(f"[Mongo Init Exception]: {e}")
            _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
    return _mongo_client

def get_chroma():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path="./aria_vectors")
    return _chroma_client

def get_collections():
    client = get_chroma()
    docs_col = client.get_or_create_collection(name="documents")
    mem_col = client.get_or_create_collection(name="memory")
    return docs_col, mem_col

def get_mongo_collections():
    db = get_mongo()
    if db is not None:
        db_instance = db["aria_db"]
        return (
            db_instance["personal_memory"],
            db_instance["tasks_schedule"],
            db_instance["media_vault"],
            db_instance["chat_history"],
            db_instance["reminders"],
            db_instance["security_logs"]
        )
    return None, None, None, None, None, None

scheduler = AsyncIOScheduler()

# -------------------------------------------------------------
# 2. SANITIZATION & EMBEDDING HELPER
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

def get_embedding(text: str) -> list[float]:
    gem = get_gemini()
    if not gem:
        return [0.0] * 768
    try:
        response = gem.models.embed_content(
            model="text-embedding-004",
            contents=text[:2000]
        )
        return response.embedding.values
    except Exception:
        return [0.0] * 768

def parse_document(file_name: str, file_bytes: bytes, password: str = None) -> tuple[str, bool]:
    fn = file_name.lower()
    text = ""
    is_encrypted = False
    MAX_CHARS = 6000
    try:
        if fn.endswith(".pdf"):
            reader = PdfReader(BytesIO(file_bytes))
            if reader.is_encrypted:
                if password:
                    try:
                        if not reader.decrypt(password):
                            return "[INVALID_PASSWORD]", True
                    except Exception:
                        return "[INVALID_PASSWORD]", True
                else:
                    return "[ENCRYPTED_PDF_LOCKED]", True
            text = "".join([page.extract_text() or "" for page in reader.pages]).strip()

        elif fn.endswith(".docx"):
            doc = Document(BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs if p.text]).strip()

        elif fn.endswith(".xlsx"):
            wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
            sheet_texts = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                for row in ws.iter_rows(values_only=True):
                    row_str = " ".join([str(cell) for cell in row if cell is not None])
                    if row_str: sheet_texts.append(row_str)
            text = "\n".join(sheet_texts).strip()

        elif fn.endswith(".txt") or fn.endswith(".csv"):
            text = file_bytes.decode("utf-8", errors="ignore").strip()

        else:
            text = "Binary File Payload"
    except Exception as e:
        text = f"[Parsing Error: {str(e)}]"
    return text[:MAX_CHARS], is_encrypted

# -------------------------------------------------------------
# 3. AI-DRIVEN PLANNER & VECTOR TOOLS
# -------------------------------------------------------------
async def ai_planner(user_text: str) -> dict:
    groq = get_groq()
    planner_prompt = f"""Return JSON only. Analyze user request: "{user_text}"
{{
  "memory": true/false,
  "documents": true/false,
  "vision": true/false,
  "internet": true/false,
  "calculator": true/false
}}"""
    if groq:
        try:
            comp = groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": planner_prompt}],
                temperature=0.1, max_tokens=100
            )
            raw = re.sub(r'```json\s*|\s*```', '', comp.choices[0].message.content.strip())
            return json.loads(raw)
        except Exception:
            pass
    return {"memory": False, "documents": False, "vision": False, "internet": False, "calculator": False}

async def process_image_with_gemini_vision(image_bytes: bytes) -> str:
    gem = get_gemini()
    if not gem: return "Image uploaded."
    try:
        def _gem():
            res = gem.models.generate_content(
                model='gemini-2.0-flash',
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                    "Perform OCR and describe charts, diagrams, code, or handwritten text."
                ]
            )
            return res.text
        return (await asyncio.to_thread(_gem)).strip()
    except Exception as e:
        return f"Vision Error: {e}"

def index_into_chroma(file_name: str, media_type: str, text: str):
    try:
        docs_col, _ = get_collections()
        chunks = [text[i:i+500] for i in range(0, len(text), 500)]
        for idx, chunk in enumerate(chunks):
            emb = get_embedding(chunk)
            docs_col.add(
                ids=[f"{file_name}_{idx}_{datetime.now().timestamp()}"],
                documents=[chunk],
                embeddings=[emb],
                metadatas=[{"file": file_name, "type": media_type}]
            )
    except Exception as e:
        print(f"[Chroma Indexing Error]: {e}")

async def send_file_from_vault(file_query: str, chat_id: str) -> str:
    _, _, media_col, _, _, _ = get_mongo_collections()
    if media_col is None: return "Vault offline, Sir."
    try:
        q_regex = re.compile(re.escape(file_query.strip()), re.IGNORECASE)
        target = await media_col.find_one({"$or": [{"file_name": q_regex}, {"caption": q_regex}]})
        if not target:
            target = await media_col.find_one({"media_type": "document"}, sort=[("_id", -1)])
        if not target: return f"Document matching '{file_query}' not found."

        fname = target.get("file_name", "doc.pdf")
        raw_bytes = base64.b64decode(target["b64_payload"])
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                data={"chat_id": chat_id, "caption": f"Here is your document: '{fname}', Sir."},
                files={"document": (fname, raw_bytes, "application/octet-stream")}
            )
        return f"File '{fname}' dispatched to your Telegram, Sir."
    except Exception as e:
        return f"Dispatch error: {e}"

async def query_vector_docs(question: str) -> str:
    try:
        docs_col, _ = get_collections()
        emb = get_embedding(question)
        res = docs_col.query(query_embeddings=[emb], n_results=4)
        if res and res.get("documents"):
            return "\n".join(res["documents"][0])
        return ""
    except Exception:
        return ""

async def query_vector_memory(query: str) -> str:
    try:
        _, mem_col = get_collections()
        emb = get_embedding(query)
        res = mem_col.query(query_embeddings=[emb], n_results=5)
        if res and res.get("documents"):
            return "\n".join(res["documents"][0])
        return ""
    except Exception:
        return ""

async def save_memory_fact(category: str, fact: str) -> str:
    cat = category.lower().strip()
    fact_str = fact.strip()
    mem_col_mongo, _, _, _, _, _ = get_mongo_collections()
    if mem_col_mongo is not None:
        try:
            await mem_col_mongo.insert_one({"category": cat, "fact": fact_str, "timestamp": datetime.now(timezone.utc).isoformat()})
        except Exception: pass

    try:
        _, mem_col = get_collections()
        emb = get_embedding(fact_str)
        mem_col.add(
            ids=[str(datetime.now().timestamp())],
            documents=[fact_str],
            embeddings=[emb],
            metadatas=[{"category": cat}]
        )
    except Exception: pass
    return "Saved permanently to vector vault, Sir."

# -------------------------------------------------------------
# 4. BACKGROUND TASKS
# -------------------------------------------------------------
async def summarize_recent_chats():
    _, _, _, chats_col, _, _ = get_mongo_collections()
    if chats_col is None: return
    try:
        cursor = chats_col.find({}).sort("_id", -1).limit(30)
        chats = await cursor.to_list(length=30)
        if chats:
            blob = "\n".join([f"User: {c.get('user_msg')}\nARIA: {c.get('aria_reply')}" for c in chats])
            await save_memory_fact("chat_summary", f"Summary: {blob[:1000]}")
    except Exception as e:
        print(f"[Summary Error]: {e}")

# -------------------------------------------------------------
# 5. TASK PROCESSOR & SELF-REFLECTION
# -------------------------------------------------------------
async def process_autonomous_task(user_text: str, session_id: str, location_info: str = None) -> str:
    cmd = user_text.lower().strip()

    # 1. PERMISSION GATE
    if session_id in PENDING_SECURITY_ACTIONS:
        pending = PENDING_SECURITY_ACTIONS[session_id]
        if pending.get("type") == "unlock_pdf":
            pwd = re.search(r'\b([A-Za-z0-9@#$_]{4,25})\b', user_text.strip())
            pwd_str = pwd.group(1) if pwd else user_text.strip()
            _, media_col, _, _, _, _ = get_mongo_collections()
            target = await media_col.find_one({"file_name": re.compile(re.escape(pending["data"]["doc_keyword"]), re.IGNORECASE)})
            if target:
                raw = base64.b64decode(target["b64_payload"])
                txt, _ = parse_document(target["file_name"], raw, password=pwd_str)
                if txt == "[INVALID_PASSWORD]":
                    return "Incorrect password, Sir."
                await media_col.update_one({"_id": target["_id"]}, {"$set": {"caption": txt, "is_encrypted": False}})
                index_into_chroma(target["file_name"], "document", txt)
            del PENDING_SECURITY_ACTIONS[session_id]
            return "Document unlocked successfully, Sir."

    plan = await ai_planner(user_text)

    # 2. LOCAL CALCULATOR CHECK
    if plan.get("calculator") or re.search(r'^\s*[\d\+\-\*\/\(\)\.\s]+\s*$', user_text):
        try:
            val = eval(user_text)
            return f"{val}"
        except Exception:
            pass

    # 3. IMPORTANCE-BASED MEMORY CAPTURE (Threshold >= 8)
    if any(w in cmd for w in ["remember", "my ", "i like", "favorite"]):
        groq = get_groq()
        if groq:
            score_prompt = f"Rate 1-10 importance to remember permanently: '{user_text}'. Return integer only."
            try:
                s_res = groq.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": score_prompt}], max_tokens=5)
                score = int(re.search(r'\d+', s_res.choices[0].message.content).group())
                if score >= 8:
                    await save_memory_fact("preference", user_text)
            except Exception:
                pass

    # 4. ASSEMBLE CONTEXT
    global RAM_MEMORY_CACHE, RAM_RECENT_CHATS
    mem_text = await query_vector_memory(user_text) if plan.get("memory") else ""
    doc_text = await query_vector_documents(user_text) if plan.get("documents") else ""
    tavily = get_tavily()
    web_text = ""
    if plan.get("internet") and tavily:
        try:
            res = tavily.search(query=user_text, max_results=2)
            web_text = "\n".join([item['content'][:200] for item in res.get("results", [])])
        except Exception: pass

    master_context = f"""
{get_current_temporal_context()}
[VECTOR MEMORY]: {mem_text}
[DOCUMENTS]: {doc_text}
[WEB SEARCH]: {web_text}
"""

    system_prompt = f"""You are {ASSISTANT_NAME}, J.A.R.V.I.S.-style assistant.
{master_context}
Rules: 
1. STRICT REDACTION: Never output, echo, or print raw numeric digits of Aadhaar, RRN, or MyNumber under any circumstances. If requested, state that you cannot display government ID numbers in text chat but can dispatch the official PDF file directly to Telegram.
2. Address user as Sir. Be precise and concise."""

    reply = ""
    groq = get_groq()
    if groq:
        try:
            comp = groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
                temperature=0.2, max_tokens=300
            )
            reply = comp.choices[0].message.content.strip()
        except Exception: pass

    if not reply:
        gem = get_gemini()
        if gem:
            try:
                res = gem.models.generate_content(model="gemini-2.0-flash", contents=f"{system_prompt}\nUser: {user_text}")
                reply = res.text.strip()
            except Exception: pass

    if not reply:
        reply = "At your service, Sir."

    cleaned = clean_response_text(reply)

    # 5. CONDITIONAL SELF-REFLECTION
    if plan.get("internet") and len(cleaned) < 40 and tavily:
        try:
            res = tavily.search(query=user_text, max_results=3)
            cleaned += "\n" + "\n".join([i['content'][:150] for i in res.get("results", [])])
        except Exception: pass

    RAM_MEMORY_CACHE = RAM_MEMORY_CACHE[-20:]
    RAM_RECENT_CHATS = RAM_RECENT_CHATS[-10:]

    asyncio.create_task(log_chat_interaction(user_text, cleaned, session_id))
    return cleaned

# -------------------------------------------------------------
# 6. TELEGRAM WEBHOOK & UPLOADS
# -------------------------------------------------------------
@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    if not TELEGRAM_TOKEN: return {"status": "no token"}
    try:
        data = await req.json()
        msg = data.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        from_id = msg.get("from", {}).get("id")
        text = msg.get("text", "").strip()
        doc = msg.get("document")
        photo = msg.get("photo")

        if not chat_id: return {"status": "ok"}
        if ALLOWED_TELEGRAM_USER_ID and str(from_id) != str(ALLOWED_TELEGRAM_USER_ID):
            return {"status": "unauthorized"}

        if text.lower() == "/start":
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "ARIA online, Sir."})
            return {"status": "ok"}

        file_obj, fname = None, "file.dat"
        if doc: file_obj, fname = doc, doc.get("file_name", "doc.pdf")
        elif photo: file_obj, fname = photo[-1], "image.jpg"

        if file_obj:
            file_id = file_obj.get("file_id")
            async with httpx.AsyncClient() as client:
                f_info = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}")
                f_path = f_info.json().get("result", {}).get("file_path")
                raw = (await client.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{f_path}")).content

            if photo:
                extracted = await process_image_with_gemini_vision(raw)
                is_enc = False
            else:
                extracted, is_enc = parse_document(fname, raw)

            msg_rep = await save_media_file(fname, "document", raw, caption=extracted, is_encrypted=is_enc)
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg_rep})
            return {"status": "ok"}

        if text:
            ans = await process_autonomous_task(text, str(chat_id))
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": ans})
            return {"status": "ok"}
    except Exception as e:
        print(f"[Webhook Error]: {e}")
    return {"status": "ok"}

@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(summarize_recent_chats, 'interval', hours=24, id="summarize_chats_job")
    scheduler.start()
    print("[ARIA Optimized Core]: Online.")

@app.head("/health")
@app.get("/health")
def health():
    return JSONResponse(status_code=200, content={"status": "online"})

@app.head("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>ARIA Stark-Tier Lightweight Core Active</h1>"

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            ans = await process_autonomous_task(data.get("prompt", ""), session_id, data.get("location"))
            await websocket.send_json({"text": ans})
    except WebSocketDisconnect: pass

@app.post("/upload-file")
async def upload_file(file: UploadFile = File(...)):
    raw = await file.read()
    if file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        extracted = await process_image_with_gemini_vision(raw)
        is_enc = False
    else:
        extracted, is_enc = parse_document(file.filename, raw)
    msg = await save_media_file(file.filename, "document", raw, caption=extracted, is_encrypted=is_enc)
    return {"status": "ok", "message": msg}
