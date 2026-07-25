import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import google.generativeai as genai
from supabase import create_client

app = FastAPI()

# 1. Fetch Environment Secrets from Render
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

ASSISTANT_NAME = "ARIA"
SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, an advanced, highly capable AI personal assistant.
You are articulate, resourceful, and sharp. Keep spoken/chat replies concise and natural."""

# 2. Configure Services
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Using gemini-1.5-flash for higher free tier quota limits
model = genai.GenerativeModel("gemini-1.5-flash")

# Initialize Supabase if keys exist
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

class UserQuery(BaseModel):
    prompt: str

# -------------------------------------------------------------
# ENDPOINT 1: WEB APP VOICE FRONTEND (HTML + JS)
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
        <p>Your Personal Voice & Telegram Assistant</p>

        <button class="mic-btn" onclick="startListening()">🎤</button>
        <div id="status">Tap the button to speak</div>
        <div id="response">Waiting for input...</div>

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

                        // Voice output
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
# ENDPOINT 2: DIRECT CHAT API (WEB APP)
# -------------------------------------------------------------
@app.post("/chat")
def chat(data: UserQuery):
    try:
        full_prompt = f"{SYSTEM_PROMPT}\nUser: {data.prompt}\n{ASSISTANT_NAME}:"
        response = model.generate_content(full_prompt)
        return {"assistant": ASSISTANT_NAME, "reply": response.text}
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return {
            "assistant": ASSISTANT_NAME, 
            "reply": "I am receiving too many requests right now. Please wait about 30 seconds and try again."
        }

# -------------------------------------------------------------
# ENDPOINT 3: TELEGRAM BOT WEBHOOK
# -------------------------------------------------------------
@app.post("/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    
    # Process text messages from Telegram
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        user_text = data["message"]["text"]
        
        try:
            full_prompt = f"{SYSTEM_PROMPT}\nUser: {user_text}\n{ASSISTANT_NAME}:"
            response = model.generate_content(full_prompt)
            ai_reply = response.text
        except Exception as e:
            print(f"Gemini API Error: {e}")
            ai_reply = "Rate limit reached. Please wait 30 seconds before sending another message."
        
        # Send reply back via Telegram API
        if TELEGRAM_TOKEN:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(telegram_url, json={
                    "chat_id": chat_id,
                    "text": ai_reply
                })
                
    return {"status": "ok"}
