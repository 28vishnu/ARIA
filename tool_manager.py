import base64
import httpx
import os
import re

class BaseTool:
    NAME = "base"
    DESCRIPTION = "Base tool"
    CAPABILITIES = []

    async def execute(self, query: str, context_handle, chat_id: str = None) -> dict:
        raise NotImplementedError

class MediaVaultTool(BaseTool):
    NAME = "media"
    DESCRIPTION = "Locate and dispatch stored documents, resumes, PDFs, and files directly to Telegram."
    CAPABILITIES = ["dispatch file", "resume", "send document", "download pdf"]

    async def execute(self, query: str, media_col, chat_id: str = None) -> dict:
        print(f"[TOOL - MEDIA] Locating media file for query: '{query}' and chat_id: {chat_id}")
        if media_col is None or not chat_id: 
            return {"success": False, "source": "media", "content": "Media vault offline or chat ID missing.", "confidence": 0.0, "metadata": {}}
        
        try:
            clean_q = query.lower().strip()
            
            # 1. Smart Alias & Keyword Mapping for Resumes / Documents
            search_query_filter = {}
            if any(k in clean_q for k in ["resume", "cv", "portfolio"]):
                search_query_filter = {"$or": [{"file_name": re.compile("resume|cv|portfolio", re.IGNORECASE)}, {"aliases": "resume"}]}
            else:
                q_regex = re.compile(re.escape(clean_q), re.IGNORECASE)
                search_query_filter = {"$or": [{"file_name": q_regex}, {"caption": q_regex}, {"aliases": q_regex}]}

            target = await media_col.find_one(search_query_filter)

            # 2. If exact or alias match fails, NEVER use a random fallback. List available files instead.
            if not target:
                print("[TOOL - MEDIA] No matching document found via alias/query search.")
                cursor = media_col.find({}, {"file_name": 1}).limit(5)
                available_files = await cursor.to_list(length=5)
                
                if available_files:
                    file_list_str = "\n".join([f"• {f.get('file_name')}" for f in available_files])
                    clarification_msg = (
                        f"I couldn't find a matching document for '{query}' in your Media Vault, Sir.\n\n"
                        f"Here are the documents currently stored in your vault:\n{file_list_str}\n\n"
                        f"Which one would you like me to send?"
                    )
                else:
                    clarification_msg = "Your Media Vault is currently empty, Sir. If you upload your resume or documents, I'll store and remember them permanently."

                return {
                    "success": False, 
                    "source": "media", 
                    "content": clarification_msg, 
                    "confidence": 0.0, 
                    "metadata": {"requires_clarification": True}
                }

            fname = target.get("file_name", "document.pdf")
            raw_bytes = base64.b64decode(target["b64_payload"])
            token = os.getenv("TELEGRAM_TOKEN")
            
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": f"Here is your requested document: '{fname}', Sir."},
                    files={"document": (fname, raw_bytes, "application/octet-stream")}
                )
            print(f"[TOOL - MEDIA] Successfully dispatched '{fname}' to Telegram.")
            return {"success": True, "source": "media", "content": f"File '{fname}' successfully dispatched to your Telegram chat, Sir.", "confidence": 1.0, "metadata": {"file": fname}}
        except Exception as e:
            print(f"[TOOL - MEDIA EXCEPTION]: {e}")
            return {"success": False, "source": "media", "content": f"Dispatch error: {e}", "confidence": 0.0, "metadata": {}}
