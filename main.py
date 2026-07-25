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

# Crisp, Professional J.A.R.V.I.S. Persona
SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, a highly intelligent, crisp, and loyal AI personal assistant inspired by Iron Man's J.A.R.V.I.S.
CORE DIRECTIVES:
- Address the user as 'Master' or 'Sir' naturally.
- Be extremely concise, direct, and witty. Speak in 1-2 sharp sentences.
- Never list bullet points or use markdown formatting in plain speech.
- Sound like a trusted, highly efficient peer—calm, confident, and immediate."""

# Initialize SDK Clients
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

class UserQuery(BaseModel):
    prompt: str

# -------------------------------------------------------------
# MULTI-PROVIDER FAST CASCADE
# -------------------------------------------------------------
async def generate_assistant_response(user_text: str) -> str:
    full_prompt = f"{SYSTEM_PROMPT}\n\nMaster: {user_text}\n{ASSISTANT_NAME}:"

    # PROVIDER 1: GROQ (Ultra-Fast <200ms)
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.5,
                max_tokens=150
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"[Groq Warning]: {e}")

    # PROVIDER 2: GEMINI
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=full_prompt
            )
            return response.text
        except Exception as e:
            print(f"[Gemini Warning]: {e}")

    # PROVIDER 3: MISTRAL HTTP
    if MISTRAL_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "mistral-small-latest", "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_text}]},
                    timeout=8.0
                )
                if res.status_code == 200:
                    return res.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"[Mistral Warning]: {e}")

    # PROVIDER 4: OPENROUTER
    if OPENROUTER_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "meta-llama/llama-3.3-70b-instruct:free", "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_text}]},
                    timeout=8.0
                )
                if res.status_code == 200:
                    return res.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"[OpenRouter Warning]: {e}")

    return "Standing by, Master. All neural channels are busy. Please repeat."

# -------------------------------------------------------------
# WEB APP FRONTEND (HIGH-SPEED VOICE ENGINE)
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def serve_webapp():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{ASSISTANT_NAME} HUD</title>
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
                width: 140px;
                height: 140px;
                border-radius: 50%;
                background: radial-gradient(circle, #38bdf8 0%, #0284c7 70%, #0369a1 100%);
                box-shadow: 0 0 40px rgba(56,189,248,0.6);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 50px;
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
                margin: 30px 0;
            }}
            .orb.listening {{
                animation: pulse 1.5s infinite;
                box-shadow: 0 0 60px rgba(56,189,248,0.9);
            }}
            @keyframes pulse {{
                0% {{ transform: scale(1); }}
                50% {{ transform: scale(1.08); }}
                100% {{ transform: scale(1); }}
            }}
            #status {{ color: #38bdf8; font-size: 1.1rem; font-weight: 500; min-height: 24px; }}
            #response {{
                margin-top: 25px;
                font-size: 1.25rem;
                line-height: 1.5;
                max-width: 550px;
                background: #0f172a;
                padding: 20px;
                border-radius: 16px;
                border: 1px solid #1e293b;
                box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            }}
        </style>
    </head>
    <body>
        <h1 style="letter-spacing: 4px; color: #38bdf8;">{ASSISTANT_NAME}</h1>
        <p style="color: #64748b;">Awaiting Your Command, Master</p>

        <div id="orb" class="orb" onclick="toggleListening()">🎤</div>
        <div id="status">Tap orb to initiate voice link</div>
        <div id="response">Systems nominal, Master.</div>

        <script>
            let isListening = false;
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if (SpeechRecognition) {{
                recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onstart = () => {{
                    document.getElementById('orb').classList.add('listening');
                    document.getElementById('status').innerText = 'Listening...';
                }};

                recognition.onend = () => {{
                    document.getElementById('orb').classList.remove('listening');
                }};

                recognition.onresult = async (event) => {{
                    const speech = event.results[0][0].transcript;
                    document.getElementById('status').innerText = 'Processing...';

                    try {{
                        const res = await fetch('/chat', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{ prompt: speech }})
                        }});
                        const data = await res.json();

                        document.getElementById('response').innerText = data.reply;
                        document.getElementById('status').innerText = 'Tap to speak again';

                        speakResponse(data.reply);
                    }} catch (err) {{
                        document.getElementById('status').innerText = 'Connection error.';
                    }}
                }};
            }}

            function toggleListening() {{
                if (recognition) recognition.start();
            }}

            function speakResponse(text) {{
                window.speechSynthesis.cancel(); // Clear old speech queue immediately
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.rate = 1.15; // Faster, natural cadence
                utterance.pitch = 1.0;

                // Pick smooth English voice if available
                const voices = window.speechSynthesis.getVoices();
                const preferredVoice = voices.find(v => v.lang.includes('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Samantha')));
                if (preferredVoice) utterance.voice = preferredVoice;

                window.speechSynthesis.speak(utterance);
            }}
        </script>
    </body>
    </html>
    """

# -------------------------------------------------------------
# API ENDPOINTS (SIMULTANEOUS WEB + TELEGRAM WORKFLOW)
# -------------------------------------------------------------
@app.post("/chat")
async def chat(data: UserQuery):
    reply = await generate_assistant_response(data.prompt)
    return {"assistant": ASSISTANT_NAME, "reply": reply}

@app.post("/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        user_text = data["message"]["text"]
        
        reply = await generate_assistant_response(user_text)
        
        if TELEGRAM_TOKEN:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(telegram_url, json={"chat_id": chat_id, "text": reply})
                
    return {"status": "ok"}
