import os
from fastapi import FastAPI
from pydantic import BaseModel
import google.generativeai as genai
from supabase import create_client

app = FastAPI()

# Fetch hidden secrets from Render environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# Initialize Supabase with your Secret Key (runs securely on the server)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

class UserQuery(BaseModel):
    user_id: str = "owner"
    prompt: str

ASSISTANT_NAME = "ARIA"

@app.get("/")
def read_root():
    return {"status": "online", "assistant": ASSISTANT_NAME}

@app.post("/chat")
def chat(data: UserQuery):
    full_prompt = f"You are {ASSISTANT_NAME}, an advanced personal AI assistant. Reply concisely.\nUser: {data.prompt}"
    response = model.generate_content(full_prompt)
    
    return {
        "assistant_name": ASSISTANT_NAME,
        "reply": response.text
    }
