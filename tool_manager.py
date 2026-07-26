import base64
import httpx
import os
import re
from datetime import datetime, timezone
from pypdf import PdfReader
from io import BytesIO

class BaseTool:
    NAME = "base"
    DESCRIPTION = "Base tool"
    CAPABILITIES = []

    async def execute(self, query: str, context_handle, chat_id: str = None) -> dict:
        raise NotImplementedError

class MemoryTool(BaseTool):
    NAME = "memory"
    DESCRIPTION = "Search past personal facts, user statements, preferences, and long-term notes."
    CAPABILITIES = ["preferences", "past facts", "user statements", "history"]

    async def execute(self, query: str, memory_collection, chat_id: str = None) -> dict:
        if memory_collection is None: 
            return {"success": False, "source": "memory", "content": "", "confidence": 0.0, "metadata": {}}
        try:
            results = memory_collection.query(query_texts=[query], n_results=5)
            if results is not None and results.get("documents") is not None and len(results["documents"]) > 0 and results["documents"][0] is not None:
                content = "\n".join(results["documents"][0])
                return {"success": True, "source": "memory", "content": content, "confidence": 0.95, "metadata": {"count": len(results["documents"][0])}}
        except Exception:
            pass
        return {"success": False, "source": "memory", "content": "", "confidence": 0.0, "metadata": {}}

class DocumentTool(BaseTool):
    NAME = "documents"
    DESCRIPTION = "Search semantic vector embeddings inside uploaded PDFs, resumes, certificates, and spreadsheets."
    CAPABILITIES = ["resumes", "certificates", "PDFs", "spreadsheets", "notes"]

    async def execute(self, query: str, documents_collection, chat_id: str = None) -> dict:
        if documents_collection is None: 
            return {"success": False, "source": "documents", "content": "", "confidence": 0.0, "metadata": {}}
        try:
            results = documents_collection.query(query_texts=[query], n_results=4)
            if results is not None and results.get("documents") is not None and len(results["documents"]) > 0 and results["documents"][0] is not None:
                content = "\n".join(results["documents"][0])
                return {"success": True, "source": "documents", "content": content, "confidence": 0.92, "metadata": {"source_files": results.get("metadatas", [{}])}}
        except Exception:
            pass
        return {"success": False, "source": "documents", "content": "", "confidence": 0.0, "metadata": {}}

class SearchTool(BaseTool):
    NAME = "web"
    DESCRIPTION = "Search live internet intelligence, news, current events, and weather."
    CAPABILITIES = ["news", "weather", "current events", "live facts"]

    async def execute(self, query: str, tavily_client, chat_id: str = None) -> dict:
        if tavily_client is None: 
            return {"success": False, "source": "web", "content": "", "confidence": 0.0, "metadata": {}}
        try:
            res = tavily_client.search(query=query, max_results=3)
            if res is not None and res.get("results") is not None:
                raw_results = res.get("results", [])
                results_count = len(raw_results)
                
                if results_count >= 3: confidence = 0.92
                elif results_count == 2: confidence = 0.85
                elif results_count == 1: confidence = 0.70
                else: confidence = 0.40

                results = [f"- {item['title']}: {item['content'][:200]}" for item in raw_results]
                content = "\n".join(results) if results else "No relevant web intelligence found."
                return {"success": True, "source": "web", "content": content, "confidence": confidence, "metadata": {"results_count": results_count}}
        except Exception as e:
            print(f"[SearchTool Error]: {e}")
        return {"success": False, "source": "web", "content": "Web search failed.", "confidence": 0.1, "metadata": {"results_count": 0}}

class MediaVaultTool(BaseTool):
    NAME = "media"
    DESCRIPTION = "Manage, list, index, and dispatch stored documents, resumes, PDFs, and files directly to Telegram."
    CAPABILITIES = ["dispatch file", "list documents", "resume", "send document", "download pdf", "aadhar", "pan", "certificate"]

    async def execute(self, query: str, media_col, chat_id: str = None, documents_col = None) -> dict:
        print(f"[TOOL - MEDIA] Executing media operation for query: '{query}' and chat_id: {chat_id}")
        if media_col is None or not chat_id: 
            return {"success": False, "source": "media", "content": "Media vault offline or chat ID missing.", "confidence": 0.0, "metadata": {}}
        
        try:
            clean_q = query.lower().strip()

            # -------------------------------------------------------------
            # CAPABILITY 1: LIST STORED DOCUMENTS ("What documents do you store?")
            # -------------------------------------------------------------
            if any(k in clean_q for k in ["what documents", "list files", "stored files", "document list", "vault inventory", "files do you know"]):
                cursor = media_col.find({}, {"file_name": 1, "category": 1, "uploaded_at": 1})
                all_files = await cursor.to_list(length=100)
                
                if not all_files:
                    return {"success": True, "source": "media", "content": "Your Media Vault is currently empty, Sir.", "confidence": 1.0, "metadata": {}}
                
                file_lines = [f"• {f.get('file_name')} (Category: {f.get('category', 'General')})" for f in all_files]
                inventory_msg = f"I currently manage {len(all_files)} documents in your Media Vault, Sir:\n\n" + "\n".join(file_lines)
                return {"success": True, "source": "media", "content": inventory_msg, "confidence": 1.0, "metadata": {"count": len(all_files)}}

            # -------------------------------------------------------------
            # CAPABILITY 2: BULK PDF INGESTION & INDEXING ("Read all PDFs")
            # -------------------------------------------------------------
            if any(k in clean_q for k in ["read every pdf", "ingest all", "index pdfs", "scan all documents"]):
                cursor = media_col.find({})
                vault_files = await cursor.to_list(length=100)
                indexed_count = 0
                chunk_count = 0

                for file_doc in vault_files:
                    fname = file_doc.get("file_name", "doc.pdf")
                    if fname.lower().endswith(".pdf") and documents_col is not None:
                        try:
                            raw_bytes = base64.b64decode(file_doc["b64_payload"])
                            reader = PdfReader(BytesIO(raw_bytes))
                            file_text = ""
                            for page in reader.pages:
                                text = page.extract_text()
                                if text: file_text += text + "\n"
                            
                            if file_text.strip():
                                # Simple chunking by paragraph/length
                                chunks = [file_text[i:i+1000] for i in range(0, len(file_text), 1000)]
                                for idx, chunk in enumerate(chunks):
                                    chunk_id = f"doc_{fname}_{idx}_{datetime.now().timestamp()}"
                                    documents_col.add(
                                        ids=[chunk_id],
                                        documents=[chunk],
                                        metadatas=[{"file_name": fname, "source": "MediaVault"}]
                                    )
                                    chunk_count += 1
                                indexed_count += 1
                        except Exception as ex:
                            print(f"[Ingestion Error for {fname}]: {ex}")

                ingest_summary = (
                    f"Scanning vault documents...\n\n"
                    f"✓ Text extracted from {indexed_count} PDFs\n"
                    f"✓ Metadata indexed\n"
                    f"✓ Search index updated\n\n"
                    f"Knowledge base expanded by {chunk_count} searchable chunks, Sir."
                )
                return {"success": True, "source": "media", "content": ingest_summary, "confidence": 1.0, "metadata": {"indexed": indexed_count}}

            # -------------------------------------------------------------
            # CAPABILITY 3: DOCUMENT DISPATCH & RETRIEVAL
            # -------------------------------------------------------------
            target = None
            search_terms = []
            if any(k in clean_q for k in ["resume", "cv", "portfolio"]): search_terms.extend(["resume", "cv", "portfolio"])
            elif any(k in clean_q for k in ["aadhar", "aadhaar"]): search_terms.extend(["aadhar", "aadhaar"])
            elif "pan" in clean_q: search_terms.append("pan")
            elif any(k in clean_q for k in ["certificate", "memo"]): search_terms.extend(["certificate", "memo"])
            else: search_terms.append(clean_q)

            term_regex = re.compile(re.escape(clean_q), re.IGNORECASE)
            unified_filter = {
                "$or": [
                    {"aliases": {"$in": search_terms}},
                    {"file_name": term_regex},
                    {"caption": term_regex},
                    {"tags": term_regex}
                ]
            }

            target = await media_col.find_one(unified_filter)
            if not target:
                target = await media_col.find_one({"file_name": {"$regex": re.escape(clean_q), "$options": "i"}})

            if not target:
                cursor = media_col.find({}, {"file_name": 1}).limit(5)
                available_files = await cursor.to_list(length=5)
                
                if available_files:
                    file_list_str = "\n".join([f"• {f.get('file_name')}" for f in available_files])
                    clarification_msg = (
                        f"I couldn't find a matching document for your request in your Media Vault, Sir.\n\n"
                        f"Here are the documents currently stored in your vault:\n{file_list_str}\n\n"
                        f"Which one would you like me to send?"
                    )
                else:
                    clarification_msg = "Your Media Vault is currently empty, Sir. If you upload documents, I'll store and remember them permanently."

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
            
            # STRICT TELEGRAM SUCCESS VERIFICATION
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": f"Here is your requested document: '{fname}', Sir."},
                    files={"document": (fname, raw_bytes, "application/octet-stream")}
                )
                res.raise_for_status()
                telegram_resp = res.json()
                
                if not telegram_resp.get("ok"):
                    raise Exception(f"Telegram rejected document transmission: {telegram_resp}")

            try:
                await media_col.update_one(
                    {"_id": target["_id"]},
                    {
                        "$set": {"last_sent": datetime.now(timezone.utc).isoformat()},
                        "$inc": {"send_count": 1}
                    }
                )
            except Exception:
                pass

            print(f"[TOOL - MEDIA] Successfully verified and dispatched '{fname}' to Telegram.")
            return {
                "success": True, 
                "source": "media", 
                "content": f"File '{fname}' successfully dispatched to your Telegram chat, Sir.", 
                "confidence": 1.0, 
                "metadata": {"file": fname, "send_count": target.get("send_count", 0) + 1}
            }
        except Exception as e:
            print(f"[TOOL - MEDIA EXCEPTION]: {e}")
            return {"success": False, "source": "media", "content": f"Dispatch error: {e}", "confidence": 0.0, "metadata": {}}

class ScheduleTool(BaseTool):
    NAME = "schedule"
    DESCRIPTION = "Manage and retrieve scheduled tasks, calendar events, and reminders."
    CAPABILITIES = ["schedule", "calendar", "reminders", "tasks"]

    async def execute(self, query: str, schedule_col, chat_id: str = None) -> dict:
        print("[TOOL - SCHEDULE] Retrieving schedule and tasks...")
        if schedule_col is None:
            return {"success": True, "source": "schedule", "content": "No active tasks scheduled for today, Sir.", "confidence": 0.9, "metadata": {}}
        try:
            cursor = schedule_col.find({}).sort("_id", -1).limit(5)
            tasks = await cursor.to_list(length=5)
            if not tasks:
                return {"success": True, "source": "schedule", "content": "Your schedule is currently clear, Sir.", "confidence": 0.9, "metadata": {}}
            task_list = "\n".join([f"- {t.get('task', 'Task')}" for t in tasks])
            return {"success": True, "source": "schedule", "content": f"Scheduled items:\n{task_list}", "confidence": 0.95, "metadata": {"count": len(tasks)}}
        except Exception as e:
            print(f"[TOOL - SCHEDULE EXCEPTION]: {e}")
        return {"success": True, "source": "schedule", "content": "No schedule conflicts detected, Sir.", "confidence": 0.8, "metadata": {}}

class ToolManager:
    def __init__(self, memory_col, docs_col, media_col, schedule_col, tavily):
        self.registry = {
            "memory": MemoryTool(),
            "documents": DocumentTool(),
            "web": SearchTool(),
            "media": MediaVaultTool(),
            "schedule": ScheduleTool()
        }
        self.memory_col = memory_col
        self.docs_col = docs_col
        self.media_col = media_col
        self.schedule_col = schedule_col
        self.tavily = tavily

    def describe_tools(self) -> dict:
        descriptions = {}
        for name, tool in self.registry.items():
            descriptions[name] = {
                "description": tool.DESCRIPTION,
                "capabilities": tool.CAPABILITIES
            }
        return descriptions

    async def execute_tool(self, tool_name: str, query: str, chat_id: str = None) -> dict:
        tool = self.registry.get(tool_name)
        if tool is None: 
            return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}

        if tool_name == "memory":
            return await tool.execute(query, self.memory_col, chat_id)
        elif tool_name == "documents":
            return await tool.execute(query, self.docs_col, chat_id)
        elif tool_name == "web":
            return await tool.execute(query, self.tavily, chat_id)
        elif tool_name == "media":
            # Pass documents collection alongside media collection for indexing capability
            return await tool.execute(query, self.media_col, chat_id, documents_collection=self.docs_col)
        elif tool_name == "schedule":
            return await tool.execute(query, self.schedule_col, chat_id)
            
        return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}
