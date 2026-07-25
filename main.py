import os
import json
import httpx
from io import BytesIO
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pypdf import PdfReader

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
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

ASSISTANT_NAME = "ARIA"

# FRIENDLY, NATURAL MULTILINGUAL SYSTEM PROMPT
ARIA_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, an intelligent, highly responsive, and friendly personal AI assistant.
CONVERSATIONAL DIRECTIVES:
- Maintain a warm, friendly, natural, and comfortable conversational tone. Address the user naturally as 'Sir' without inserting micro-pauses or awkward commas before the title.
- DYNAMIC LANGUAGE SWITCHING:
  * Respond fluently in English or Tenglish (Telugu transliterated in English script) based on what the user speaks.
  * When speaking in Tenglish, keep it completely natural, expressive, and conversational.
  * Never repeat generic filler phrases or default greetings over and over. Keep every response fresh and direct.
- Keep spoken responses concise, engaging, and clear (1 to 2 articulate sentences max).
- Use personal memory context, schedule, weather, search results, and repositories to answer directly."""

# Initialize SDK Clients
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
github_client = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

class UserQuery(BaseModel):
    prompt: str
    location: str = None

# -------------------------------------------------------------
# MODULE HOOKS & PARSERS
# -------------------------------------------------------------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(file_bytes))
        extracted_text = "".join([page.extract_text() or "" for page in reader.pages])
        return extracted_text.strip()
    except Exception as e:
        print(f"[PDF Error]: {e}")
        return ""

def save_fact_to_memory(category: str, fact: str):
    if supabase:
        try:
            supabase.table("personal_memory").insert({"category": category, "fact": fact}).execute()
        except Exception as e:
            print(f"[Memory Warning]: {e}")

def fetch_web_search(query: str) -> str:
    if not tavily_client: return ""
    search_keywords = ["news", "latest", "search", "who is", "today", "box office", "update", "weather", "score", "movie", "cinema"]
    if any(kw in query.lower() for kw in search_keywords):
        try:
            res = tavily_client.search(query=query, max_results=2)
            results = [f"- {item['title']}: {item['content'][:150]}" for item in res.get("results", [])]
            return "\nLIVE SEARCH RESULTS:\n" + "\n".join(results) + "\n"
        except Exception as e:
            print(f"[Search Error]: {e}")
    return ""

async def fetch_weather_by_coords(location_info: str) -> str:
    if not location_info or "," not in location_info: return ""
    try:
        lat, lon = location_info.split(",")
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=5.0)
            if res.status_code == 200:
                data = res.json().get("current_weather", {})
                return f"\nLOCAL WEATHER: Currently {data.get('temperature')}°C, wind {data.get('windspeed')} km/h.\n"
    except Exception as e:
        print(f"[Weather Error]: {e}")
    return ""

def fetch_github_summary() -> str:
    if not github_client: return ""
    try:
        user = github_client.get_user()
        repos = [repo.name for repo in user.get_repos()[:5]]
        return f"\nGITHUB REPOSITORIES: {', '.join(repos)}\n"
    except Exception:
        return ""

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
    except Exception:
        return ""

def log_voice_interaction(user_text: str, ai_reply: str, location_info: str = None):
    if supabase:
        try:
            payload = {"user_id": "owner", "transcript": user_text, "ai_reply": ai_reply}
            if location_info: payload["location"] = location_info
            supabase.table("voice_logs").insert(payload).execute()
        except Exception: pass

def fetch_longterm_memory() -> str:
    if not supabase: return ""
    try:
        res = supabase.table("personal_memory").select("category, fact").execute()
        if res.data:
            facts = [f"[{item['category'].upper()}]: {item['fact']}" for item in res.data]
            return "\nSTORED PERSONAL MEMORY & DOCUMENTS:\n" + "\n".join(facts) + "\n"
    except Exception: pass
    return ""

async def generate_aria_response(user_text: str, location_info: str = None) -> str:
    memory_context = fetch_longterm_memory() + fetch_google_calendar_events() + fetch_github_summary() + fetch_web_search(user_text)
    if location_info:
        memory_context += await fetch_weather_by_coords(location_info) + f"\nUSER GPS LOCATION: {location_info}\n"
        
    if supabase:
        try:
            res = supabase.table("voice_logs").select("transcript, ai_reply").order("created_at", desc=True).limit(2).execute()
            if res.data:
                past = "\n".join([f"Sir: {m['transcript']}\nARIA: {m['ai_reply']}" for m in reversed(res.data)])
                memory_context += f"\nRECENT DIALOGUE:\n{past}\n"
        except Exception: pass

    full_system = ARIA_SYSTEM_PROMPT + memory_context

    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": full_system}, {"role": "user", "content": user_text}],
                temperature=0.6, max_tokens=150
            )
            reply = completion.choices[0].message.content
            log_voice_interaction(user_text, reply, location_info)
            return reply
        except Exception as e: print(f"[Groq Warning]: {e}")

    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash", contents=f"{full_system}\n\nSir: {user_text}\nARIA:"
            )
            reply = response.text
            log_voice_interaction(user_text, reply, location_info)
            return reply
        except Exception as e: print(f"[Gemini Warning]: {e}")

    return "Online and ready Sir. How can I help you right now?"

# -------------------------------------------------------------
# ADVANCED CANVAS PARTICLES & FULLSCREEN AUTOMATIC HUD
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
        <meta name="theme-color" content="#030712">
        <title>{ASSISTANT_NAME} Neural Core</title>
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
                justify-content: space-between;
                padding: 25px 20px;
                overflow: hidden;
                position: relative;
            }}
            canvas#particleCanvas {{
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                z-index: 1;
                pointer-events: none;
            }}
            .ui-layer {{
                position: relative;
                z-index: 2;
                width: 100%;
                max-width: 500px;
                display: flex;
                flex-direction: column;
                align-items: center;
                height: 100%;
                justify-content: space-between;
            }}
            .header {{
                text-align: center;
                margin-top: 10px;
            }}
            .title {{
                font-size: 2.2rem;
                font-weight: 900;
                letter-spacing: 8px;
                background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
            .hud-orb-container {{
                position: relative;
                width: 220px;
                height: 220px;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 40px 0;
                cursor: pointer;
            }}
            .ring-1 {{
                position: absolute;
                width: 100%;
                height: 100%;
                border-radius: 50%;
                border: 2px dashed rgba(56, 189, 248, 0.4);
                animation: spin 22s linear infinite;
            }}
            .ring-2 {{
                position: absolute;
                width: 80%;
                height: 80%;
                border-radius: 50%;
                border: 2px solid rgba(129, 140, 248, 0.5);
                box-shadow: 0 0 30px rgba(56, 189, 248, 0.3);
            }}
            .core-node {{
                width: 55%;
                height: 55%;
                border-radius: 50%;
                background: radial-gradient(circle, #38bdf8 0%, #0284c7 60%, #0369a1 100%);
                box-shadow: 0 0 50px rgba(56, 189, 248, 0.8);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 38px;
                transition: transform 0.3s ease, background 0.3s ease;
            }}
            .hud-orb-container.speaking .core-node {{
                animation: pulseGlow 1s ease-in-out infinite alternate;
                background: radial-gradient(circle, #818cf8 0%, #4f46e5 70%, #3730a3 100%);
                box-shadow: 0 0 70px rgba(129, 140, 248, 0.9);
            }}
            @keyframes spin {{ 100% {{ transform: rotate(360deg); }} }}
            @keyframes pulseGlow {{ 0% {{ transform: scale(0.95); }} 100% {{ transform: scale(1.12); }} }}

            .status-card {{
                width: 100%;
                background: rgba(15, 23, 42, 0.75);
                backdrop-filter: blur(16px);
                border-radius: 24px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 22px;
                text-align: center;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
            }}
            #live-text {{
                font-size: 1.15rem;
                line-height: 1.6;
                color: #f1f5f9;
                min-height: 55px;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            .pdf-btn {{
                margin-top: 15px;
                background: rgba(56, 189, 248, 0.12);
                border: 1px solid rgba(56, 189, 248, 0.5);
                color: #38bdf8;
                padding: 10px 20px;
                border-radius: 14px;
                font-size: 0.85rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s ease;
            }}
            .pdf-btn:active {{ transform: scale(0.96); background: rgba(56, 189, 248, 0.25); }}
            .telemetry {{
                display: flex;
                justify-content: space-around;
                margin-top: 15px;
                padding-top: 12px;
                border-top: 1px solid rgba(255, 255, 255, 0.08);
                font-size: 0.75rem;
                color: #64748b;
                letter-spacing: 1px;
            }}
            .tel-dot {{ width: 7px; height: 7px; border-radius: 50%; background: #22c55e; display: inline-block; margin-right: 5px; }}
        </style>
    </head>
    <body>
        <canvas id="particleCanvas"></canvas>

        <div class="ui-layer">
            <div class="header">
                <h1 class="title">{ASSISTANT_NAME}</h1>
            </div>

            <div class="hud-orb-container" id="hudContainer" onclick="forceMicRestart()">
                <div class="ring-1"></div>
                <div class="ring-2"></div>
                <div class="core-node" id="coreNode">🎙️</div>
            </div>

            <div class="status-card">
                <div id="live-text">Listening...</div>
                
                <input type="file" id="pdfInput" accept="application/pdf" style="display: none;" onchange="uploadPDF()">
                <button class="pdf-btn" onclick="document.getElementById('pdfInput').click()">📄 Upload Document / PDF</button>

                <div class="telemetry">
                    <div><span class="tel-dot"></span> ONLINE</div>
                    <div id="gpsStat">GPS: ACTIVE</div>
                    <div>NEURAL CORE: 3.3</div>
                </div>
            </div>
        </div>

        <script>
            /* DYNAMIC BACKGROUND PARTICLES ENGINE */
            const canvas = document.getElementById('particleCanvas');
            const ctx = canvas.getContext('2d');
            let particles = [];

            function resizeCanvas() {{
                canvas.width = window.innerWidth;
                canvas.height = window.innerHeight;
            }}
            window.addEventListener('resize', resizeCanvas);
            resizeCanvas();

            class Particle {{
                constructor() {{
                    this.x = Math.random() * canvas.width;
                    this.y = Math.random() * canvas.height;
                    this.vx = (Math.random() - 0.5) * 0.8;
                    this.vy = (Math.random() - 0.5) * 0.8;
                    this.radius = Math.random() * 2 + 1;
                    this.alpha = Math.random() * 0.5 + 0.2;
                }}
                update() {{
                    this.x += this.vx;
                    this.y += this.vy;
                    if (this.x < 0 || this.x > canvas.width) this.vx *= -1;
                    if (this.y < 0 || this.y > canvas.height) this.vy *= -1;
                }}
                draw() {{
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                    ctx.fillStyle = `rgba(56, 189, 248, ${{this.alpha}})`;
                    ctx.fill();
                }}
            }}

            for (let i = 0; i < 60; i++) particles.push(new Particle());

            function animateParticles() {{
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                particles.forEach((p, index) => {{
                    p.update();
                    p.draw();
                    for (let j = index + 1; j < particles.length; j++) {{
                        const p2 = particles[j];
                        const dist = Math.hypot(p.x - p2.x, p.y - p2.y);
                        if (dist < 110) {{
                            ctx.beginPath();
                            ctx.moveTo(p.x, p.y);
                            ctx.lineTo(p2.x, p2.y);
                            ctx.strokeStyle = `rgba(56, 189, 248, ${{0.15 * (1 - dist / 110)}})`;
                            ctx.lineWidth = 0.8;
                            ctx.stroke();
                        }}
                    }}
                }});
                requestAnimationFrame(animateParticles);
            }}
            animateParticles();

            /* SPEECH RECOGNITION & AUTOMATIC SYSTEM CONTROLLER */
            let isSpeaking = false;
            let userLocation = null;
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if ("geolocation" in navigator) {{
                navigator.geolocation.getCurrentPosition(
                    (pos) => {{ userLocation = pos.coords.latitude + "," + pos.coords.longitude; }},
                    () => {{ document.getElementById('gpsStat').innerText = 'GPS: OFF'; }}
                );
            }}

            if (SpeechRecognition) {{
                recognition = new SpeechRecognition();
                recognition.continuous = true;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onresult = async (event) => {{
                    const lastResultIndex = event.results.length - 1;
                    const speech = event.results[lastResultIndex][0].transcript.trim();

                    if (!speech) return;

                    // INSTANT BARGE-IN INTERRUPTION
                    window.speechSynthesis.cancel();
                    isSpeaking = false;
                    document.getElementById('hudContainer').classList.remove('speaking');

                    document.getElementById('live-text').innerText = speech;

                    try {{
                        const res = await fetch('/chat', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{ prompt: speech, location: userLocation }})
                        }});
                        const data = await res.json();
                        document.getElementById('live-text').innerText = data.reply;
                        speakResponse(data.reply);
                    }} catch (err) {{
                        document.getElementById('live-text').innerText = 'Re-establishing link Sir...';
                    }}
                }};

                recognition.onend = () => {{
                    if (!isSpeaking) {{
                        try {{ recognition.start(); }} catch(e){{}}
                    }}
                }};

                // AUTOMATIC DIRECT START ON PAGE LOAD
                window.addEventListener('load', () => {{
                    try {{ recognition.start(); }} catch(e) {{}}
                }});
            }}

            function forceMicRestart() {{
                window.speechSynthesis.cancel();
                isSpeaking = false;
                document.getElementById('hudContainer').classList.remove('speaking');
                if (recognition) {{
                    try {{ recognition.start(); }} catch(e) {{}}
                }}
            }}

            function speakResponse(rawText) {{
                isSpeaking = true;
                window.speechSynthesis.cancel();
                document.getElementById('hudContainer').classList.add('speaking');
                
                let fluidText = rawText
                    .replace(/,\\s*Sir/gi, ' Sir')
                    .replace(/,/g, '')
                    .replace(/\\s+/g, ' ');

                const utterance = new SpeechSynthesisUtterance(fluidText);
                utterance.rate = 0.98;
                utterance.pitch = 1.0;

                const voices = window.speechSynthesis.getVoices();
                const nativeVoice = voices.find(v => 
                    v.lang === 'te-IN' || 
                    v.lang === 'en-IN' || 
                    v.name.includes('Telugu') || 
                    v.name.includes('Rishi') || 
                    v.name.includes('India') ||
                    v.name.includes('Google te-in') ||
                    v.name.includes('Google en-in')
                );
                
                const fallbackVoice = voices.find(v => v.lang.includes('en'));
                if (nativeVoice) utterance.voice = nativeVoice;
                else if (fallbackVoice) utterance.voice = fallbackVoice;

                utterance.onend = () => {{
                    isSpeaking = false;
                    document.getElementById('hudContainer').classList.remove('speaking');
                    if (recognition) {{
                        try {{ recognition.start(); }} catch(e){{}}
                    }}
                }};

                window.speechSynthesis.speak(utterance);
            }}

            async function uploadPDF() {{
                const input = document.getElementById('pdfInput');
                if (!input.files || input.files.length === 0) return;

                const formData = new FormData();
                formData.append('file', input.files[0]);

                document.getElementById('live-text').innerText = 'Reading document Sir...';

                try {{
                    const res = await fetch('/upload-pdf', {{
                        method: 'POST',
                        body: formData
                    }});
                    const data = await res.json();
                    document.getElementById('live-text').innerText = data.message;
                    speakResponse(data.message);
                }} catch (err) {{
                    document.getElementById('live-text').innerText = 'Failed to index PDF.';
                }}
            }}
        </script>
    </body>
    </html>
    """

# -------------------------------------------------------------
# API ENDPOINTS
# -------------------------------------------------------------
@app.post("/chat")
async def chat(data: UserQuery):
    reply = await generate_aria_response(data.prompt, data.location)
    return {"assistant": ASSISTANT_NAME, "reply": reply}

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    file_bytes = await file.read()
    pdf_text = extract_text_from_pdf(file_bytes)
    
    if not pdf_text:
        return {"status": "error", "message": "Could not read document text Sir."}

    truncated_summary = pdf_text[:1200].replace("\n", " ")
    save_fact_to_memory("document", f"PDF '{file.filename}': {truncated_summary}")
    
    reply = f"I have read and saved {file.filename} into memory Sir."
    return {"status": "success", "message": reply}

@app.post("/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        user_text = data["message"]["text"]
        reply = await generate_aria_response(user_text)
        if TELEGRAM_TOKEN:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(telegram_url, json={"chat_id": chat_id, "text": reply})
    return {"status": "ok"}
