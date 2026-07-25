import os
import json
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

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

# DYNAMIC DUAL-LANGUAGE SYSTEM PROMPT
ARIA_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, an autonomous, high-IQ personal AI assistant inspired by J.A.R.V.I.S.
CONVERSATIONAL DIRECTIVES:
- Address the user naturally as 'Sir' without placing commas before or after the title. Integrate 'Sir' seamlessly into sentences (e.g. 'All systems nominal Sir' or 'Right away Sir').
- DYNAMIC LANGUAGE SWITCHING:
  * If the user speaks in English, respond in clear, articulate English.
  * If the user speaks in Telugu or Tenglish, respond naturally using English/Latin script for seamless speech synthesis.
  * DO NOT repeat fixed greetings or phrases unless relevant. Keep replies unique, context-aware, and fresh every time.
- Maintain quiet confidence, dry subtle warmth, and complete composure.
- Keep spoken replies concise, sharp, and highly fluent (1 to 2 natural sentences max).
- Deliver precise answers immediately using stored personal memory context, schedule, weather, search results, and repositories."""

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
# INTEGRATION FUNCTIONS
# -------------------------------------------------------------
def fetch_web_search(query: str) -> str:
    if not tavily_client: return ""
    search_keywords = ["news", "latest", "search", "who is", "today", "box office", "update", "weather", "score", "movie", "cinema"]
    if any(kw in query.lower() for kw in search_keywords):
        try:
            res = tavily_client.search(query=query, max_results=2)
            results = [f"- {item['title']}: {item['content'][:150]}" for item in res.get("results", [])]
            return "\nLIVE TAVILY SEARCH RESULTS:\n" + "\n".join(results) + "\n"
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
    except Exception as e:
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
    except Exception as e:
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
            return "\nSTORED PERSONAL MEMORY:\n" + "\n".join(facts) + "\n"
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
                temperature=0.5, max_tokens=150
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

    return "Standing by Sir. All core systems operational."

# -------------------------------------------------------------
# FULLSCREEN HUD FRONTEND WITH ACCURATE SPEECH-ONLY INTERRUPTION
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
        <title>{ASSISTANT_NAME} AI</title>
        <style>
            * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #030712;
                color: #f8fafc;
                margin: 0;
                padding: 0;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: space-between;
                padding: 30px 20px;
                overflow: hidden;
            }}
            .header {{
                text-align: center;
                margin-top: 10px;
            }}
            .title {{
                font-size: 2.2rem;
                font-weight: 800;
                letter-spacing: 6px;
                background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin: 0;
            }}
            .subtitle {{
                color: #64748b;
                font-size: 0.8rem;
                letter-spacing: 2px;
                text-transform: uppercase;
                margin-top: 4px;
            }}
            /* ARC REACTOR HUD EFFECT */
            .hud-container {{
                position: relative;
                width: 220px;
                height: 220px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
            }}
            .outer-ring {{
                position: absolute;
                width: 100%;
                height: 100%;
                border-radius: 50%;
                border: 2px dashed rgba(56, 189, 248, 0.4);
                animation: rotate 20s linear infinite;
            }}
            .inner-ring {{
                position: absolute;
                width: 75%;
                height: 75%;
                border-radius: 50%;
                border: 2px solid rgba(56, 189, 248, 0.6);
                box-shadow: 0 0 25px rgba(56, 189, 248, 0.3);
            }}
            .core-orb {{
                width: 50%;
                height: 50%;
                border-radius: 50%;
                background: radial-gradient(circle, #38bdf8 0%, #0284c7 70%, #0369a1 100%);
                box-shadow: 0 0 40px rgba(56, 189, 248, 0.8);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 35px;
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }}
            .hud-container.listening .core-orb {{
                animation: pulseCore 1.2s ease-in-out infinite alternate;
                background: radial-gradient(circle, #f43f5e 0%, #e11d48 70%, #9f1239 100%);
                box-shadow: 0 0 60px rgba(244, 63, 94, 0.9);
            }}
            @keyframes rotate {{ 100% {{ transform: rotate(360deg); }} }}
            @keyframes pulseCore {{ 0% {{ transform: scale(0.95); }} 100% {{ transform: scale(1.15); }} }}

            /* TELEMETRY CARDS */
            .status-panel {{
                width: 100%;
                max-width: 500px;
                background: rgba(15, 23, 42, 0.7);
                backdrop-filter: blur(12px);
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 0.08);
                padding: 20px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.5);
            }}
            #status-text {{
                color: #38bdf8;
                font-size: 1rem;
                font-weight: 600;
                letter-spacing: 1px;
                margin-bottom: 8px;
            }}
            #response-box {{
                font-size: 1.1rem;
                line-height: 1.5;
                color: #e2e8f0;
                min-height: 60px;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            .telemetry-row {{
                display: flex;
                justify-content: space-around;
                margin-top: 15px;
                padding-top: 12px;
                border-top: 1px solid rgba(255,255,255,0.05);
                font-size: 0.75rem;
                color: #64748b;
            }}
            .tel-item {{ display: flex; align-items: center; gap: 5px; }}
            .dot {{ width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 class="title">{ASSISTANT_NAME}</h1>
            <div class="subtitle">Neural Autonomous Interface</div>
        </div>

        <div class="hud-container" id="hud" onclick="toggleListening()">
            <div class="outer-ring"></div>
            <div class="inner-ring"></div>
            <div class="core-orb" id="orb">🎙️</div>
        </div>

        <div class="status-panel">
            <div id="status-text">SYSTEM STANDBY</div>
            <div id="response-box">Online and at your service, Sir.</div>
            <div class="telemetry-row">
                <div class="tel-item"><div class="dot"></div> LINK: ACTIVE</div>
                <div class="tel-item" id="gps-stat">GPS: CALIBRATING</div>
                <div class="tel-item">ENGINE: GROQ 3.3</div>
            </div>
        </div>

        <script>
            let continuousMode = true;
            let isSpeaking = false;
            let userLocation = null;
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if ("geolocation" in navigator) {{
                navigator.geolocation.getCurrentPosition(
                    (pos) => {{
                        userLocation = pos.coords.latitude + "," + pos.coords.longitude;
                        document.getElementById('gps-stat').innerText = 'GPS: LOCKED';
                    }},
                    (err) => {{ document.getElementById('gps-stat').innerText = 'GPS: OFF'; }}
                );
            }}

            if (SpeechRecognition) {{
                recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onstart = () => {{
                    document.getElementById('hud').classList.add('listening');
                    if (!isSpeaking) {{
                        document.getElementById('status-text').innerText = 'LISTENING...';
                    }}
                }};

                recognition.onend = () => {{
                    document.getElementById('hud').classList.remove('listening');
                    if (continuousMode && !isSpeaking) {{
                        setTimeout(() => {{ try {{ recognition.start(); }} catch(e){{}} }}, 400);
                    }} else if (!continuousMode) {{
                        document.getElementById('status-text').innerText = 'STANDBY';
                    }}
                }};

                recognition.onresult = async (event) => {{
                    const speech = event.results[0][0].transcript;
                    if (!speech || speech.trim().length === 0) return;

                    // INTERRUPT ARIA'S SPEECH ONLY WHEN A REAL USER COMMAND IS DETECTED
                    window.speechSynthesis.cancel();
                    isSpeaking = false;

                    document.getElementById('status-text').innerText = 'PROCESSING...';

                    try {{
                        const res = await fetch('/chat', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{ prompt: speech, location: userLocation }})
                        }});
                        const data = await res.json();
                        document.getElementById('response-box').innerText = data.reply;
                        speakResponse(data.reply);
                    }} catch (err) {{
                        document.getElementById('status-text').innerText = 'CONNECTION ERROR';
                    }}
                }};
            }}

            function toggleListening() {{
                window.speechSynthesis.cancel();
                isSpeaking = false;
                if (recognition) {{
                    try {{ recognition.start(); }} catch(e) {{ recognition.stop(); }}
                }}
            }}

            function speakResponse(rawText) {{
                isSpeaking = true;
                window.speechSynthesis.cancel();
                
                // STRIP PUNCTUATION GAP BEFORE SIR FOR ONE-BREATH DELIVERY
                let fluidText = rawText
                    .replace(/,\\s*Sir/gi, ' Sir')
                    .replace(/,\\s*Master/gi, ' Master')
                    .replace(/,/g, '')
                    .replace(/\\s+/g, ' ');

                const utterance = new SpeechSynthesisUtterance(fluidText);
                utterance.rate = 0.95;
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
                
                const fallbackVoice = voices.find(v => 
                    v.lang.includes('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Samantha') || v.name.includes('Daniel'))
                );

                if (nativeVoice) {{
                    utterance.voice = nativeVoice;
                }} else if (fallbackVoice) {{
                    utterance.voice = fallbackVoice;
                }}

                utterance.onend = () => {{
                    isSpeaking = false;
                    document.getElementById('status-text').innerText = 'LISTENING...';
                    if (continuousMode) {{
                        setTimeout(() => {{ try {{ recognition.start(); }} catch(e){{}} }}, 300);
                    }}
                }};

                window.speechSynthesis.speak(utterance);
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
