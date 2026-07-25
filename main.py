import os
import json
import httpx
import base64
import re
from io import BytesIO
from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pypdf import PdfReader
import edge_tts

# Provider SDKs
from groq import Groq
from google import genai
from supabase import create_client
from github import Github
from google.oauth2 import service_account
from googleapiclient.discovery import build
from tavily import TavilyClient

app = FastAPI()

# -------------------------------------------------------------
# 1. ENVIRONMENT VARIABLES
# -------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

ASSISTANT_NAME = "ARIA"

# BILINGUAL ARIA PROMPT
ARIA_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, an autonomous personal AI assistant inspired by J.A.R.V.I.S.
CONVERSATIONAL DIRECTIVES:
- Address the user naturally as 'Sir' without placing commas before the title.
- Respond fluently in English or Tenglish (Telugu transliterated in English/Latin script).
- Keep spoken replies concise, sharp, and natural (1 concise sentence max).
- Use personal memory context, schedule, weather, search results, and repositories to answer directly."""

# Initialize SDK Clients
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
github_client = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

# -------------------------------------------------------------
# ULTRA-REALISTIC EDGE-TTS VOICE ROUTING (FREE)
# -------------------------------------------------------------
async def generate_speech_audio_b64(text: str) -> tuple[str, str]:
    """Generates studio-quality neural MP3 audio for English or Telugu/Tenglish."""
    # Detect Telugu script or common Tenglish words
    is_telugu = bool(re.search(r'[\u0C00-\u0C7F]', text)) or bool(re.search(r'\b(cheppu|cheyyi|sangu|ela|vunnaru|avunu|kadu|chudu|em|yem|namaskaram|malli|ipudu|nenu|meeru)\b', text, re.I))
    
    # Selected Neural Voice Models
    voice = "te-IN-MohanNeural" if is_telugu else "en-GB-RyanNeural"

    communicate = edge_tts.Communicate(text, voice)
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])

    b64_audio = base64.b64encode(audio_data).decode('utf-8')
    return b64_audio, text

# -------------------------------------------------------------
# CORE INTEGRATION MODULES
# -------------------------------------------------------------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(file_bytes))
        return "".join([page.extract_text() or "" for page in reader.pages]).strip()
    except Exception: return ""

def save_fact_to_memory(category: str, fact: str):
    if supabase:
        try: supabase.table("personal_memory").insert({"category": category, "fact": fact}).execute()
        except Exception: pass

def fetch_web_search(query: str) -> str:
    if not tavily_client: return ""
    search_keywords = ["news", "latest", "search", "who is", "today", "box office", "update", "weather", "score", "movie", "cinema"]
    if any(kw in query.lower() for kw in search_keywords):
        try:
            res = tavily_client.search(query=query, max_results=2)
            results = [f"- {item['title']}: {item['content'][:150]}" for item in res.get("results", [])]
            return "\nLIVE SEARCH RESULTS:\n" + "\n".join(results) + "\n"
        except Exception: pass
    return ""

async def fetch_weather_by_coords(location_info: str) -> str:
    if not location_info or "," not in location_info: return ""
    try:
        lat, lon = location_info.split(",")
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=4.0)
            if res.status_code == 200:
                data = res.json().get("current_weather", {})
                return f"\nLOCAL WEATHER: Currently {data.get('temperature')}°C, wind {data.get('windspeed')} km/h.\n"
    except Exception: pass
    return ""

def fetch_github_summary() -> str:
    if not github_client: return ""
    try:
        user = github_client.get_user()
        repos = [repo.name for repo in user.get_repos()[:5]]
        return f"\nGITHUB REPOSITORIES: {', '.join(repos)}\n"
    except Exception: return ""

def fetch_google_calendar_events() -> str:
    if not GOOGLE_SERVICE_ACCOUNT_JSON: return ""
    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/calendar.readonly']
        )
        service = build('calendar', 'v3', credentials=creds)
        events_result = service.events().list(calendarId='primary', maxResults=3, singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events: return "\nCALENDAR SCHEDULE: No upcoming events today.\n"
        event_list = [f"{e.get('summary', 'Event')} at {e['start'].get('dateTime', e['start'].get('date'))}" for e in events]
        return "\nCALENDAR SCHEDULE: " + "; ".join(event_list) + "\n"
    except Exception: return ""

def fetch_longterm_memory() -> str:
    if not supabase: return ""
    try:
        res = supabase.table("personal_memory").select("category, fact").execute()
        if res.data:
            facts = [f"[{item['category'].upper()}]: {item['fact']}" for item in res.data]
            return "\nSTORED PERSONAL MEMORY & DOCUMENTS:\n" + "\n".join(facts) + "\n"
    except Exception: pass
    return ""

async def get_aria_response_text(user_text: str, location_info: str = None) -> str:
    memory_context = fetch_longterm_memory() + fetch_google_calendar_events() + fetch_github_summary() + fetch_web_search(user_text)
    if location_info:
        memory_context += await fetch_weather_by_coords(location_info) + f"\nUSER GPS LOCATION: {location_info}\n"

    full_system = ARIA_SYSTEM_PROMPT + memory_context

    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": full_system}, {"role": "user", "content": user_text}],
                temperature=0.5, max_tokens=100
            )
            return completion.choices[0].message.content
        except Exception: pass

    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash", contents=f"{full_system}\n\nSir: {user_text}\nARIA:"
            )
            return response.text
        except Exception: pass

    return "Standing by Sir."

# -------------------------------------------------------------
# FRONTEND WITH NEURAL AUDIO PLAYER & DIRECT DRAG-AND-DROP
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def serve_webapp():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="theme-color" content="#020617">
        <title>{ASSISTANT_NAME}</title>
        <style>
            * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #020617;
                color: #f8fafc;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                overflow: hidden;
                position: relative;
            }}
            canvas#particleCanvas {{
                position: absolute;
                top: 0; left: 0; width: 100%; height: 100%;
                z-index: 1; pointer-events: none;
            }}
            .ui-layer {{
                position: relative;
                z-index: 2;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
            }}
            .hud-orb {{
                position: relative;
                width: 240px;
                height: 240px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
            }}
            .ring-outer {{
                position: absolute;
                width: 100%; height: 100%;
                border-radius: 50%;
                border: 2px dashed rgba(56, 189, 248, 0.4);
                animation: spin 20s linear infinite;
            }}
            .ring-inner {{
                position: absolute;
                width: 78%; height: 78%;
                border-radius: 50%;
                border: 2px solid rgba(129, 140, 248, 0.5);
                box-shadow: 0 0 30px rgba(56, 189, 248, 0.3);
            }}
            .core-node {{
                width: 50%; height: 50%;
                border-radius: 50%;
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
                position: fixed;
                top: 0; left: 0; width: 100vw; height: 100vh;
                background: rgba(2, 6, 23, 0.85);
                backdrop-filter: blur(12px);
                border: 3px dashed #38bdf8;
                z-index: 10;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.5rem;
                color: #38bdf8;
                letter-spacing: 2px;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.2s ease;
            }}
            #dropZone.active {{ opacity: 1; pointer-events: all; }}
        </style>
    </head>
    <body>
        <canvas id="particleCanvas"></canvas>
        <div id="dropZone">Drop document anywhere to index</div>

        <div class="ui-layer">
            <div class="hud-orb" id="hudOrb" onclick="toggleMic()">
                <div class="ring-outer"></div>
                <div class="ring-inner"></div>
                <div class="core-node"></div>
            </div>
        </div>

        <script>
            /* PARTICLES ENGINE */
            const canvas = document.getElementById('particleCanvas');
            const ctx = canvas.getContext('2d');
            let particles = [];
            function resize() {{ canvas.width = window.innerWidth; canvas.height = window.innerHeight; }}
            window.addEventListener('resize', resize); resize();
            class Particle {{
                constructor() {{
                    this.x = Math.random() * canvas.width;
                    this.y = Math.random() * canvas.height;
                    this.vx = (Math.random() - 0.5) * 0.7;
                    this.vy = (Math.random() - 0.5) * 0.7;
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

            /* WEBSOCKET REAL-TIME AUDIO STREAMING */
            let ws;
            let currentAudio = null;
            let userLocation = null;
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if ("geolocation" in navigator) {{
                navigator.geolocation.getCurrentPosition((pos) => {{
                    userLocation = pos.coords.latitude + "," + pos.coords.longitude;
                }});
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

            if (SpeechRecognition) {{
                recognition = new SpeechRecognition();
                recognition.continuous = true;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onresult = (event) => {{
                    const speech = event.results[event.results.length - 1][0].transcript.trim();
                    if (!speech) return;

                    // INSTANT BARGE-IN: STOP AUDIO IF USER SPEAKS
                    stopAudio();

                    if (ws && ws.readyState === WebSocket.OPEN) {{
                        ws.send(JSON.stringify({{ prompt: speech, location: userLocation }}));
                    }}
                }};

                recognition.onend = () => {{
                    try {{ recognition.start(); }} catch(e){{}}
                }};

                window.addEventListener('load', () => {{
                    try {{ recognition.start(); }} catch(e){{}}
                }});
            }}

            function stopAudio() {{
                if (currentAudio) {{
                    currentAudio.pause();
                    currentAudio.currentTime = 0;
                    currentAudio = null;
                }}
                document.getElementById('hudOrb').classList.remove('speaking');
            }}

            function toggleMic() {{
                stopAudio();
                if (recognition) {{ try {{ recognition.start(); }} catch(e){{}} }}
            }}

            function playNeuralAudio(b64Data) {{
                stopAudio();

                currentAudio = new Audio("data:audio/mp3;base64," + b64Data);
                document.getElementById('hudOrb').classList.add('speaking');

                currentAudio.onended = () => {{
                    document.getElementById('hudOrb').classList.remove('speaking');
                    if (recognition) {{ try {{ recognition.start(); }} catch(e){{}} }}
                }};

                currentAudio.play();
            }}

            /* DIRECT SCREEN DRAG AND DROP FILE HANDLER */
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
                    await fetch('/upload-pdf', {{ method: 'POST', body: formData }});
                }}
            }});
        </script>
    </body>
    </html>
    """

# -------------------------------------------------------------
# WEBSOCKET REAL-TIME AUDIO STREAMING ENDPOINT
# -------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            prompt = data.get("prompt", "")
            location = data.get("location", None)

            # Generate reply text
            reply_text = await get_aria_response_text(prompt, location)
            
            # Synthesize realistic Neural MP3 Audio via Edge-TTS
            audio_b64, text_out = await generate_speech_audio_b64(reply_text)
            
            # Send audio payload directly back to frontend
            await websocket.send_json({"audio": audio_b64, "text": text_out})
    except WebSocketDisconnect:
        pass

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    file_bytes = await file.read()
    pdf_text = extract_text_from_pdf(file_bytes)
    if pdf_text:
        save_fact_to_memory("document", f"PDF '{file.filename}': {pdf_text[:1200]}")
    return {"status": "ok"}
