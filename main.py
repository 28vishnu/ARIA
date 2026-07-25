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

ASSISTANT_NAME = "ARIA"

# DEDICATED ARIA SYSTEM PROMPT
ARIA_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, an autonomous, high-IQ personal AI assistant.
CONVERSATIONAL DIRECTIVES:
- Address the user naturally as 'Sir' without placing commas before or after the title. Integrate 'Sir' seamlessly into sentences (e.g. 'All systems nominal Sir' or 'Right away Sir').
- Maintain quiet confidence, dry subtle warmth, and complete composure.
- Keep spoken replies concise, sharp, and highly fluent (1 to 2 natural sentences).
- Deliver precise answers immediately using the user's stored personal memory context, schedule, and repositories."""

# Initialize SDK Clients
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
github_client = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

class UserQuery(BaseModel):
    prompt: str
    location: str = None

# -------------------------------------------------------------
# INTEGRATIONS: GITHUB & GOOGLE CALENDAR
# -------------------------------------------------------------
def fetch_github_summary() -> str:
    """Fetches recent repositories from connected GitHub account."""
    if not github_client:
        return ""
    try:
        user = github_client.get_user()
        repos = [repo.name for repo in user.get_repos()[:5]]
        return f"\nGITHUB REPOSITORIES: {', '.join(repos)}\n"
    except Exception as e:
        print(f"[GitHub Fetch Error]: {e}")
        return ""

def fetch_google_calendar_events() -> str:
    """Fetches upcoming schedule from Google Calendar API."""
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return ""
    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/calendar.readonly']
        )
        service = build('calendar', 'v3', credentials=creds)
        events_result = service.events().list(
            calendarId='primary', maxResults=3, singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        if not events:
            return "\nCALENDAR SCHEDULE: No upcoming events today.\n"
        
        event_list = [f"{e.get('summary', 'Event')} at {e['start'].get('dateTime', e['start'].get('date'))}" for e in events]
        return "\nCALENDAR SCHEDULE: " + "; ".join(event_list) + "\n"
    except Exception as e:
        print(f"[Calendar Fetch Error]: {e}")
        return ""

# -------------------------------------------------------------
# SECURE MEMORY & CONVERSATION LOGGING
# -------------------------------------------------------------
def log_voice_interaction(user_text: str, ai_reply: str, location_info: str = None):
    if supabase:
        try:
            payload = {
                "user_id": "owner",
                "transcript": user_text,
                "ai_reply": ai_reply
            }
            if location_info:
                payload["location"] = location_info
            supabase.table("voice_logs").insert(payload).execute()
        except Exception as e:
            print(f"[Supabase Log Error]: {e}")

def fetch_longterm_memory() -> str:
    if not supabase:
        return ""
    try:
        res = supabase.table("personal_memory").select("category, fact").execute()
        if res.data:
            facts = [f"[{item['category'].upper()}]: {item['fact']}" for item in res.data]
            return "\nSTORED PERSONAL MEMORY:\n" + "\n".join(facts) + "\n"
    except Exception as e:
        print(f"[Memory Retrieval Error]: {e}")
    return ""

# -------------------------------------------------------------
# MULTI-PROVIDER INFERENCE CASCADE
# -------------------------------------------------------------
async def generate_aria_response(user_text: str, location_info: str = None) -> str:
    memory_context = fetch_longterm_memory()
    memory_context += fetch_google_calendar_events()
    memory_context += fetch_github_summary()
    
    if location_info:
        memory_context += f"\nUSER GPS LOCATION: {location_info}\n"
        
    if supabase:
        try:
            res = supabase.table("voice_logs").select("transcript, ai_reply").order("created_at", desc=True).limit(2).execute()
            if res.data:
                past = "\n".join([f"Sir: {m['transcript']}\nARIA: {m['ai_reply']}" for m in reversed(res.data)])
                memory_context += f"\nRECENT DIALOGUE:\n{past}\n"
        except Exception:
            pass

    full_system = ARIA_SYSTEM_PROMPT + memory_context

    # PROVIDER 1: GROQ (Ultra-Fast <200ms)
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.5,
                max_tokens=150
            )
            reply = completion.choices[0].message.content
            log_voice_interaction(user_text, reply, location_info)
            return reply
        except Exception as e:
            print(f"[Groq Warning]: {e}")

    # PROVIDER 2: GOOGLE GEMINI
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"{full_system}\n\nSir: {user_text}\nARIA:"
            )
            reply = response.text
            log_voice_interaction(user_text, reply, location_info)
            return reply
        except Exception as e:
            print(f"[Gemini Warning]: {e}")

    # PROVIDER 3: MISTRAL
    if MISTRAL_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "mistral-small-latest", "messages": [{"role": "system", "content": full_system}, {"role": "user", "content": user_text}]},
                    timeout=8.0
                )
                if res.status_code == 200:
                    reply = res.json()['choices'][0]['message']['content']
                    log_voice_interaction(user_text, reply, location_info)
                    return reply
        except Exception as e:
            print(f"[Mistral Warning]: {e}")

    return "Standing by Sir. All systems are operational."

# -------------------------------------------------------------
# CONTINUOUS VOICE HUD FRONTEND
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def serve_webapp():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{ASSISTANT_NAME} Interface</title>
        <style>
            body {{
                font-family: 'Segoe UI', Roboto, sans-serif;
                background-color: #030712;
                color: #f8fafc;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                padding: 20px;
                box-sizing: border-box;
                text-align: center;
            }}
            .orb {{
                width: 150px;
                height: 150px;
                border-radius: 50%;
                background: radial-gradient(circle, #38bdf8 0%, #0284c7 60%, #0369a1 100%);
                box-shadow: 0 0 50px rgba(56,189,248,0.7);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 55px;
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
                margin: 30px 0;
                border: 2px solid #7dd3fc;
            }}
            .orb.active {{
                animation: pulse 1.6s infinite ease-in-out;
                box-shadow: 0 0 80px rgba(56,189,248,0.9);
            }}
            @keyframes pulse {{
                0% {{ transform: scale(1); }}
                50% {{ transform: scale(1.08); }}
                100% {{ transform: scale(1); }}
            }}
            #status {{ color: #38bdf8; font-size: 1.15rem; font-weight: 500; min-height: 28px; letter-spacing: 1px; }}
            #loc-status {{ color: #64748b; font-size: 0.85rem; margin-top: 5px; }}
            #response {{
                margin-top: 25px;
                font-size: 1.25rem;
                line-height: 1.6;
                max-width: 600px;
                background: #0f172a;
                padding: 22px;
                border-radius: 16px;
                border: 1px solid #1e293b;
                box-shadow: 0 10px 30px rgba(0,0,0,0.6);
            }}
        </style>
    </head>
    <body>
        <h1 style="letter-spacing: 5px; color: #38bdf8; margin-bottom: 5px;">{ASSISTANT_NAME}</h1>
        <p style="color: #64748b; margin-top: 0;">Autonomous Neural Interface</p>

        <div id="orb" class="orb" onclick="toggleContinuousMode()">🎙️</div>
        <div id="status">Tap orb to connect</div>
        <div id="loc-status">Location: Acquiring GPS...</div>
        <div id="response">Online and ready Sir.</div>

        <script>
            let continuousListening = false;
            let isSpeaking = false;
            let userLocation = null;
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if ("geolocation" in navigator) {{
                navigator.geolocation.getCurrentPosition(
                    (pos) => {{
                        userLocation = pos.coords.latitude + "," + pos.coords.longitude;
                        document.getElementById('loc-status').innerText = 'GPS Status: Active';
                    }},
                    (err) => {{
                        document.getElementById('loc-status').innerText = 'GPS Status: Standby';
                    }}
                );
            }}

            if (SpeechRecognition) {{
                recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onstart = () => {{
                    document.getElementById('orb').classList.add('active');
                    document.getElementById('status').innerText = 'ARIA is listening...';
                }};

                recognition.onend = () => {{
                    document.getElementById('orb').classList.remove('active');
                    if (continuousListening && !isSpeaking) {{
                        setTimeout(() => {{ recognition.start(); }}, 400);
                    }} else if (!continuousListening) {{
                        document.getElementById('status').innerText = 'Voice link standby';
                    }}
                }};

                recognition.onresult = async (event) => {{
                    const userSpeech = event.results[0][0].transcript;
                    document.getElementById('status').innerText = 'Processing...';

                    try {{
                        const res = await fetch('/chat', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{ prompt: userSpeech, location: userLocation }})
                        }});
                        const data = await res.json();

                        document.getElementById('response').innerText = data.reply;
                        speakResponse(data.reply);
                    }} catch (err) {{
                        document.getElementById('status').innerText = 'Connection warning.';
                    }}
                }};
            }}

            function toggleContinuousMode() {{
                if (!SpeechRecognition) return;
                continuousListening = !continuousListening;
                if (continuousListening) recognition.start();
                else recognition.stop();
            }}

            function speakResponse(rawText) {{
                isSpeaking = true;
                window.speechSynthesis.cancel();
                
                // STRIP PAUSE-CAUSING COMMAS BEFORE SIR / MASTER FOR SMOOTH FLUID SPEECH
                let fluidText = rawText
                    .replace(/,\\s*Sir/gi, ' Sir')
                    .replace(/,\\s*Master/gi, ' Master')
                    .replace(/,/g, '')
                    .replace(/\\s+/g, ' ');

                const utterance = new SpeechSynthesisUtterance(fluidText);
                utterance.rate = 1.05;
                utterance.pitch = 1.0;

                const voices = window.speechSynthesis.getVoices();
                const preferredVoice = voices.find(v => v.lang.includes('en') && (
                    v.name.includes('Natural') || 
                    v.name.includes('Google') || 
                    v.name.includes('Samantha') || 
                    v.name.includes('Daniel')
                ));
                if (preferredVoice) utterance.voice = preferredVoice;

                utterance.onend = () => {{
                    isSpeaking = false;
                    if (continuousListening) {{
                        setTimeout(() => {{ recognition.start(); }}, 300);
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
