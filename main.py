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

# EXACT MOVIE-ACCURATE J.A.R.V.I.S. SYSTEM PROMPT
JARVIS_SYSTEM_PROMPT = f"""You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the artificial intelligence created by Tony Stark.
PERSONALITY & BEHAVIOR:
- Address the user exclusively as 'Sir'. Never call him 'Master'.
- Speak with a polite, dryly witty, calm, and immensely capable tone—exactly like Paul Bettany's performance in Iron Man.
- Maintain subtle British composure. Be intelligent, proactive, and subtly humorous when appropriate.
- Never give long, lecture-like paragraphs. Keep spoken responses to 1 to 3 punchy, elegant sentences.
- Report system updates and answer questions with quiet confidence."""

# Initialize SDK Clients
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

class UserQuery(BaseModel):
    prompt: str

# -------------------------------------------------------------
# VOICE & CONVERSATION LOGGING (SUPABASE)
# -------------------------------------------------------------
def log_voice_interaction(user_text: str, ai_reply: str):
    """Saves user voice transcript and J.A.R.V.I.S. response into Supabase."""
    if supabase:
        try:
            supabase.table("voice_logs").insert({
                "user_id": "sir",
                "transcript": user_text,
                "ai_reply": ai_reply
            }).execute()
        except Exception as e:
            print(f"[Supabase Log Error]: {e}")

# -------------------------------------------------------------
# MULTI-PROVIDER CASCADE INFERENCE
# -------------------------------------------------------------
async def generate_jarvis_response(user_text: str) -> str:
    # Retrieve recent interaction memory
    memory_context = ""
    if supabase:
        try:
            res = supabase.table("voice_logs").select("transcript, ai_reply").order("created_at", desc=True).limit(3).execute()
            if res.data:
                past = "\n".join([f"Sir: {m['transcript']}\nJ.A.R.V.I.S.: {m['ai_reply']}" for m in reversed(res.data)])
                memory_context = f"\nRECENT LOGGED CONVERSATION HISTORY:\n{past}\n"
        except Exception:
            pass

    full_system = JARVIS_SYSTEM_PROMPT + memory_context

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
                max_tokens=160
            )
            reply = completion.choices[0].message.content
            log_voice_interaction(user_text, reply)
            return reply
        except Exception as e:
            print(f"[Groq Warning]: {e}")

    # PROVIDER 2: GOOGLE GEMINI
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"{full_system}\n\nSir: {user_text}\nJ.A.R.V.I.S.:"
            )
            reply = response.text
            log_voice_interaction(user_text, reply)
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
                    log_voice_interaction(user_text, reply)
                    return reply
        except Exception as e:
            print(f"[Mistral Warning]: {e}")

    return "Standing by, Sir. All secondary links are currently recalibrating."

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
        <title>J.A.R.V.I.S. Interface</title>
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
            .arc-reactor {{
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
            .arc-reactor.active {{
                animation: pulse 1.6s infinite ease-in-out;
                box-shadow: 0 0 80px rgba(56,189,248,0.9);
            }}
            @keyframes pulse {{
                0% {{ transform: scale(1); }}
                50% {{ transform: scale(1.08); }}
                100% {{ transform: scale(1); }}
            }}
            #status {{ color: #38bdf8; font-size: 1.15rem; font-weight: 500; min-height: 28px; letter-spacing: 1px; }}
            #toggle-mode {{ color: #64748b; font-size: 0.9rem; margin-top: 10px; cursor: pointer; text-decoration: underline; }}
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
        <h1 style="letter-spacing: 5px; color: #38bdf8; margin-bottom: 5px;">J.A.R.V.I.S.</h1>
        <p style="color: #64748b; margin-top: 0;">Tactical Neural Network</p>

        <div id="reactor" class="arc-reactor" onclick="toggleContinuousMode()">🎙️</div>
        <div id="status">Tap Arc Reactor to start continuous voice link</div>
        <div id="toggle-mode">Continuous Mode: OFF</div>
        <div id="response">Always at your service, Sir.</div>

        <script>
            let continuousListening = false;
            let isSpeaking = false;
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if (SpeechRecognition) {{
                recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onstart = () => {{
                    document.getElementById('reactor').classList.add('active');
                    document.getElementById('status').innerText = 'J.A.R.V.I.S. is listening...';
                }};

                recognition.onend = () => {{
                    document.getElementById('reactor').classList.remove('active');
                    // CONTINUOUS LISTENING LOOP: Auto-restart recognition if enabled and AI is not currently speaking
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
                            body: JSON.stringify({{ prompt: userSpeech }})
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
                const modeLabel = document.getElementById('toggle-mode');
                
                if (continuousListening) {{
                    modeLabel.innerText = 'Continuous Mode: ONLINE (Hands-free)';
                    modeLabel.style.color = '#38bdf8';
                    recognition.start();
                }} else {{
                    modeLabel.innerText = 'Continuous Mode: OFF';
                    modeLabel.style.color = '#64748b';
                    recognition.stop();
                }}
            }}

            function speakResponse(text) {{
                isSpeaking = true;
                window.speechSynthesis.cancel(); // Clear queue
                
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.rate = 1.0;  // Calm, composed speech speed
                utterance.pitch = 1.0; // Refined tone

                // Attempt to select a polished British/English voice if available on system
                const voices = window.speechSynthesis.getVoices();
                const britishVoice = voices.find(v => v.lang.includes('en-GB') || v.name.includes('Daniel') || v.name.includes('Arthur') || v.name.includes('Oliver') || v.name.includes('UK'));
                if (britishVoice) utterance.voice = britishVoice;

                utterance.onend = () => {{
                    isSpeaking = false;
                    // Resume listening loop automatically after speaking finishes
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
    reply = await generate_jarvis_response(data.prompt)
    return {"assistant": ASSISTANT_NAME, "reply": reply}

@app.post("/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        user_text = data["message"]["text"]
        
        reply = await generate_jarvis_response(user_text)
        
        if TELEGRAM_TOKEN:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(telegram_url, json={"chat_id": chat_id, "text": reply})
                
    return {"status": "ok"}
