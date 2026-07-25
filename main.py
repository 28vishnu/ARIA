import os
from fastapi import FastAPI
from pydantic import BaseModel
import google.generativeai as genai
from supabase import create_client

app = FastAPI()

# 1. Setup API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# Optional Supabase connection for memory
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

class UserQuery(BaseModel):
    user_id: str = "owner"
    prompt: str

ASSISTANT_NAME = "ARIA"
SYSTEM_INSTRUCTION = f"""You are {ASSISTANT_NAME}, an advanced, highly intelligent AI personal assistant.
You are articulate, resourceful, and sharp.
You assist your user with daily tasks, technical questions, and personal queries.
Always address the user politely and keep answers concise when spoken."""

@app.get("/")
def read_root():
    return {"status": "online", "assistant": ASSISTANT_NAME}

@app.post("/chat")
def chat(data: UserQuery):
    full_prompt = f"{SYSTEM_INSTRUCTION}\n\nUser: {data.prompt}\n{ASSISTANT_NAME}:"
    response = model.generate_content(full_prompt)
    
    return {
        "assistant_name": ASSISTANT_NAME,
        "reply": response.text
    }
