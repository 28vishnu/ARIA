import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Provider SDKs
from groq import Groq
from google import genai
from supabase import create_client

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

ASSISTANT_NAME = "ARIA"

# ABSOLUTE SEAMLESS SPEECH DIRECTIVES
ARIA_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, an autonomous, high-IQ personal AI assistant.
CRITICAL SPEECH RULES:
- Never place commas before or after 'Sir' or 'Master'. Write titles cleanly inline without punctuation breaks (e.g., 'All systems nominal Sir' or 'Right away Sir').
- Speak in one continuous, highly articulate, and confident sentence (15-25 words max).
- Your tone should be composed, warm, sharp, and effortless—matching a high-end personal advisor.
- Deliver direct answers immediately without conversational filler."""

# Initialize SDK Clients
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

class UserQuery(BaseModel):
    prompt: str
    location: str = None

# -------------------------------------------------------------
# CONVERSATION & LONG-TERM MEMORY HOOKS
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
    """Retrieves stored facts and preferences from Supabase."""
    if not supabase:
        return ""
    try:
        res = supabase.table("personal_memory").select("category, fact").execute()
        if res.data:
            facts = [f"[{item['category'].upper()}]: {item['fact']}" for item in res.data]
            return "\nPERSONAL MEMORY VAULT:\n" + "\n".join(facts) + "\n"
    except Exception as e:
        print(f"[Memory Retrieval Error]: {e}")
    return ""

# -------------------------------------------------------------
# MULTI-PROVIDER CASCADE INFERENCE
# -------------------------------------------------------------
async def generate_aria_response(user_text: str, location_info: str = None) -> str:
    memory_context = fetch_longterm_memory()
    
    if location_info:
        memory_context += f"\nUSER CURRENT LOCATION: {location_info}\n"
        
    if supabase:
        try:
            res = supabase.table("voice_logs").select("transcript, ai_reply").order("created_at", desc=True).limit(2).execute()
            if res.data:
                past = "\n".join([f"User: {m['transcript']}\nARIA: {m['ai_reply']}" for m in reversed(res.data)])
                memory_context += f"\nRECENT CONVERSATION LOG:\n{past}\n"
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
                contents=f"{full_system}\n\nUser: {user_text}\nARIA:"
            )
            reply = response.text
            log_voice_interaction(user_text, reply, location_info)
            return reply
        except Exception as e:
            print(f"[Gemini Warning]: {e}")

    return "Standing by Sir. Neural links are ready."

# -------------------------------------------------------------
# CONTINUOUS VOICE HUD WITH REAL-TIME GPS LOCATION & SPEECH CLEANER
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
        <p style="color: #64748b; margin-top: 0;">Autonomous AI Personal System</p>

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
                        document.getElementById('loc-status').innerText = 'GPS Status: Permission Denied';
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
                
                let fluidText = rawText
                    .replace(/,\\s*Sir/gi, ' Sir')
                    .replace(/,\\s*Master/gi, ' Master')
                    .replace(/,/g, '');

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
