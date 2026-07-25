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
# 1. ENVIRONMENT VARIABLES & CLIENTS
# -------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

ASSISTANT_NAME = "ARIA"

# Sophisticated, Adaptive J.A.R.V.I.S. Persona
SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, an ultra-capable, highly articulate personal AI assistant inspired by Iron Man's J.A.R.V.I.S.
PERFECT CONVERSATION DIRECTIVES:
- Always address the user as 'Master' or 'Sir'.
- Speak in flawless, natural, highly intelligent English.
- Adapt your tone to be calm, confident, poised, and composed—never rushed, never robotic.
- Give complete, precise answers in 1 to 3 well-structured sentences.
- Use natural punctuation (commas and periods) so the voice synthesizer speaks with realistic rhythm and breathing pauses.
- Continuously align your personality to serve as Master's ultimate personal advisor."""

# Initialize SDK Clients
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

class UserQuery(BaseModel):
    prompt: str
    user_wpm: float = 140.0 # Default natural speaking WPM

# -------------------------------------------------------------
# MEMORY & KNOWLEDGE PERSISTENCE
# -------------------------------------------------------------
def store_conversation_memory(user_text: str, ai_reply: str):
    """Asynchronously logs conversation memory into Supabase so ARIA remembers long-term."""
    if supabase:
        try:
            supabase.table("conversations").insert({
                "user_id": "master",
                "user_message": user_text,
                "assistant_reply": ai_reply
            }).execute()
        except Exception as e:
            print(f"[Supabase Memory Warning]: {e}")

# -------------------------------------------------------------
# MULTI-PROVIDER CASCADE INFERENCE
# -------------------------------------------------------------
async def generate_assistant_response(user_text: str) -> str:
    # Retrieve past memory summary if available
    memory_context = ""
    if supabase:
        try:
            res = supabase.table("conversations").select("user_message, assistant_reply").order("created_at", desc=True).limit(3).execute()
            if res.data:
                past = "\n".join([f"User: {m['user_message']}\nARIA: {m['assistant_reply']}" for m in reversed(res.data)])
                memory_context = f"\nRECALL PAST CONVERSATION CONTEXT:\n{past}\n"
        except Exception as e:
            pass

    full_system = SYSTEM_PROMPT + memory_context

    # PROVIDER 1: GROQ (Ultra-Fast <200ms)
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.6,
                max_tokens=180
            )
            reply = completion.choices[0].message.content
            store_conversation_memory(user_text, reply)
            return reply
        except Exception as e:
            print(f"[Groq Warning]: {e}")

    # PROVIDER 2: GEMINI
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"{full_system}\n\nMaster: {user_text}\n{ASSISTANT_NAME}:"
            )
            reply = response.text
            store_conversation_memory(user_text, reply)
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
                    store_conversation_memory(user_text, reply)
                    return reply
        except Exception as e:
            print(f"[Mistral Warning]: {e}")

    return "Standing by, Master. Systems are currently calibrating. Please repeat your instruction."

# -------------------------------------------------------------
# ADAPTIVE VOICE FRONTEND (SPEED MEASUREMENT ENGINE)
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
                font-family: 'Segoe UI', Roboto, Helvetica, sans-serif;
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
            #metrics {{ color: #64748b; font-size: 0.85rem; margin-top: 5px; }}
            #response {{
                margin-top: 25px;
                font-size: 1.25rem;
                line-height: 1.6;
                max-width: 580px;
                background: #0f172a;
                padding: 22px;
                border-radius: 16px;
                border: 1px solid #1e293b;
                box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            }}
        </style>
    </head>
    <body>
        <h1 style="letter-spacing: 4px; color: #38bdf8; margin-bottom: 5px;">{ASSISTANT_NAME}</h1>
        <p style="color: #64748b; margin-top: 0;">Adaptive Neural Interface</p>

        <div id="orb" class="orb" onclick="toggleListening()">🎤</div>
        <div id="status">Tap orb to initiate voice link</div>
        <div id="metrics">Pace Calibration: 1.0x</div>
        <div id="response">Systems nominal, Master. Ready when you are.</div>

        <script>
            let speechStartTime = 0;
            let targetSpeechRate = 1.0; // Perfect natural rate baseline
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if (SpeechRecognition) {{
                recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onstart = () => {{
                    speechStartTime = Date.now();
                    document.getElementById('orb').classList.add('listening');
                    document.getElementById('status').innerText = 'Listening...';
                }};

                recognition.onend = () => {{
                    document.getElementById('orb').classList.remove('listening');
                }};

                recognition.onresult = async (event) => {{
                    const speechEndTime = Date.now();
                    const userSpeech = event.results[0][0].transcript;
                    const durationSeconds = (speechEndTime - speechStartTime) / 1000;
                    
                    // CALCULATE USER SPEAKING SPEED (Words Per Minute)
                    const wordCount = userSpeech.trim().split(/\\s+/).length;
                    if (durationSeconds > 0.5) {{
                        const calculatedWPM = (wordCount / durationSeconds) * 60;
                        
                        // DYNAMICALLY MAP USER SPEED TO ASSISTANT SPEECH RATE (Bounded between 0.9x and 1.1x for perfect natural flow)
                        if (calculatedWPM < 110) targetSpeechRate = 0.92;      // User speaks slow -> AI speaks calm and relaxed
                        else if (calculatedWPM > 170) targetSpeechRate = 1.1; // User speaks fast -> AI speeds up slightly
                        else targetSpeechRate = 1.0;                          // Perfect standard rate
                        
                        document.getElementById('metrics').innerText = 'Detected Pace: ' + Math.round(calculatedWPM) + ' WPM | AI Speed: ' + targetSpeechRate.toFixed(2) + 'x';
                    }}

                    document.getElementById('status').innerText = 'Processing...';

                    try {{
                        const res = await fetch('/chat', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{ prompt: userSpeech, user_wpm: targetSpeechRate }})
                        }});
                        const data = await res.json();

                        document.getElementById('response').innerText = data.reply;
                        document.getElementById('status').innerText = 'Tap to speak again';

                        speakResponse(data.reply, targetSpeechRate);
                    }} catch (err) {{
                        document.getElementById('status').innerText = 'Connection error.';
                    }}
                }};
            }}

            function toggleListening() {{
                if (recognition) recognition.start();
            }}

            function speakResponse(text, speedRate) {{
                window.speechSynthesis.cancel(); // Clear queue
                
                const utterance = new SpeechSynthesisUtterance(text);
                
                // DYNAMIC ADAPTIVE RATE
                utterance.rate = speedRate; 
                utterance.pitch = 1.0; // Natural, poised pitch

                // Select high quality natural voice
                const voices = window.speechSynthesis.getVoices();
                const preferredVoice = voices.find(v => v.lang.includes('en') && (
                    v.name.includes('Natural') || 
                    v.name.includes('Google') || 
                    v.name.includes('Samantha') || 
                    v.name.includes('Daniel') || 
                    v.name.includes('Karen')
                ));
                if (preferredVoice) utterance.voice = preferredVoice;

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
