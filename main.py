import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Provider SDKs
from groq import Groq
from google import genai
from mistralai import Mistral
from supabase import create_client

app = FastAPI()

# -------------------------------------------------------------
# 1. FETCH SECRETS & INITIALIZE CLIENTS
# -------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

ASSISTANT_NAME = "ARIA"

SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, a highly intelligent, witty, and deeply loyal personal AI assistant inspired by Iron Man's J.A.R.V.I.S.
PERSONALITY RULES:
- Always address the user as 'Master' or 'Sir' in every single interaction.
- Talk like an authentic, highly capable peer and trusted assistant—warm, slightly witty, confident, and direct.
- Never sound like a formal corporate chatbot or an encyclopedia.
- Since your responses will be read out loud via text-to-speech, keep your replies punchy, concise (2-3 sentences max), and conversational.
- If Master gives an instruction or order, acknowledge it with quiet confidence and report back execution."""

# Initialize AI Provider Clients
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
mistral_client = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

class UserQuery(BaseModel):
    prompt: str

# -------------------------------------------------------------
# MULTI-PROVIDER CASCADE INFERENCE LOGIC
# -------------------------------------------------------------
async def generate_assistant_response(user_text: str) -> str:
    full_prompt = f"{SYSTEM_PROMPT}\n\nMaster: {user_text}\n{ASSISTANT_NAME}:"

    # --- PROVIDER 1: GROQ (Ultra-Fast) ---
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.6,
                max_tokens=200
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"[Groq Warning]: {e}")

    # --- PROVIDER 2: GOOGLE GEMINI ---
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=full_prompt
            )
            return response.text
        except Exception as e:
            print(f"[Gemini Warning]: {e}")

    # --- PROVIDER 3: MISTRAL AI ---
    if mistral_client:
        try:
            res = mistral_client.chat.complete(
                model="mistral-small-latest",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ]
            )
            return res.choices[0].message.content
        except Exception as e:
            print(f"[Mistral Warning]: {e}")

    # --- PROVIDER 4: OPENROUTER (FALLBACK AGGREGATOR) ---
    if OPENROUTER_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "meta-llama/llama-3.3-70b-instruct:free",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_text}
                        ]
                    },
                    timeout=10.0
                )
                if res.status_code == 200:
                    data = res.json()
                    return data['choices'][0]['message']['content']
        except Exception as e:
            print(f"[OpenRouter Warning]: {e}")

    # --- FINAL EMERGENCY FALLBACK ---
    return "Apologies, Master. All external neural links are momentarily busy. Please repeat your instruction."

# -------------------------------------------------------------
# ENDPOINT 1: WEB APP FRONTEND
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def serve_webapp():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{ASSISTANT_NAME} Voice Assistant</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #0f172a;
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
            h1 {{ font-size: 2.5rem; letter-spacing: 2px; color: #38bdf8; margin-bottom: 10px; }}
            .mic-btn {{
                background: #0284c7;
                border: none;
                width: 120px;
                height: 120px;
                border-radius: 50%;
                font-size: 40px;
                color: white;
                cursor: pointer;
                box-shadow: 0 0 25px rgba(56,189,248,0.4);
                transition: transform 0.2s, background 0.2s;
                margin: 30px 0;
            }}
            .mic-btn:active {{ transform: scale(0.95); background: #0369a1; }}
            #status {{ color: #94a3b8; font-size: 1.1rem; min-height: 24px; }}
            #response {{
                margin-top: 20px;
                font-size: 1.2rem;
                line-height: 1.6;
                max-width: 600px;
                background: #1e293b;
                padding: 20px;
                border-radius: 12px;
                border: 1px solid #334155;
            }}
        </style>
    </head>
    <body>
        <h1>{ASSISTANT_NAME}</h1>
        <p>At your command, Master</p>

        <button class="mic-btn" onclick="startListening()">🎤</button>
        <div id="status">Tap the microphone to speak</div>
        <div id="response">Awaiting your instructions, Master...</div>

        <script>
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {{
                document.getElementById('status').innerText = 'Speech recognition not supported in this browser.';
            }} else {{
                const recognition = new SpeechRecognition();
                recognition.lang = 'en-US';

                function startListening() {{
                    document.getElementById('status').innerText = 'Listening...';
                    recognition.start();
                }}

                recognition.onresult = async (event) => {{
                    const userSpeech = event.results[0][0].transcript;
                    document.getElementById('status').innerText = 'Processing: "' + userSpeech + '"';

                    try {{
                        const res = await fetch('/chat', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{ prompt: userSpeech }})
                        }});
                        const data = await res.json();

                        document.getElementById('response').innerText = data.reply;
                        document.getElementById('status').innerText = 'Tap microphone to speak again';

                        const utterance = new SpeechSynthesisUtterance(data.reply);
                        window.speechSynthesis.speak(utterance);
                    }} catch (err) {{
                        document.getElementById('status').innerText = 'Error connecting to server.';
                    }}
                }};
            }}
        </script>
    </body>
    </html>
    """

# -------------------------------------------------------------
# ENDPOINT 2: WEB APP CHAT API
# -------------------------------------------------------------
@app.post("/chat")
async def chat(data: UserQuery):
    reply = await generate_assistant_response(data.prompt)
    return {"assistant": ASSISTANT_NAME, "reply": reply}

# -------------------------------------------------------------
# ENDPOINT 3: TELEGRAM BOT WEBHOOK
# -------------------------------------------------------------
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
                await client.post(telegram_url, json={
                    "chat_id": chat_id,
                    "text": reply
                })
                
    return {"status": "ok"}
