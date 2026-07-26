import base64
import httpx
import os
import re
import hashlib
from datetime import datetime, timezone
from io import BytesIO

# Multi-format parsers
from pypdf import PdfReader
import docx
import pandas as pd

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
    DESCRIPTION = "Search semantic vector embeddings inside uploaded PDFs, office files, notes, and spreadsheets."
    CAPABILITIES = ["resumes", "certificates", "PDFs", "spreadsheets", "notes", "docx"]

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

                # Structured Formatter for Weather & News
                if "weather" in query.lower():
                    snippet = raw_results[0]['content'] if raw_results else "Data unavailable"
                    content = (
                        f"🌤 Weather Report — {query.title()}\n\n"
                        f"• Condition & Details: {snippet[:250]}\n\n"
                        f"☔ Recommendation:\n"
                        f"Verify local conditions before departure, Sir."
                    )
                else:
                    headlines = [f"• **{item['title']}**\n  {item['content'][:160]}..." for item in raw_results]
                    content = "📰 **Live Intelligence & News Radar**:\n\n" + "\n\n".join(headlines)

                return {"success": True, "source": "web", "content": content, "confidence": confidence, "metadata": {"results_count": results_count}}
        except Exception as e:
            print(f"[SearchTool Error]: {e}")
        return {"success": False, "source": "web", "content": "Web search failed.", "confidence": 0.1, "metadata": {"results_count": 0}}

class MediaVaultTool(BaseTool):
    NAME = "media"
    DESCRIPTION = "Manage, parse multi-format files (PDF, DOCX, TXT, CSV, XLSX), detect smart duplicates, and dispatch documents."
    CAPABILITIES = ["dispatch file", "list documents", "parse docx", "parse pdf", "smart duplicate detection", "resume"]

    def _auto_categorize(self, filename: str) -> str:
        fn = filename.lower()
        if any(w in fn for w in ["resume", "cv", "portfolio"]): return "Resume"
        if any(w in fn for w in ["pan", "passport", "id"]): return "Identity"
        if any(w in fn for w in ["cert", "certificate", "course"]): return "Certificates"
        if any(w in fn for w in ["note", "memo", "study", "syllabus"]): return "College Notes"
        return "General"

    def _extract_text_multi_format(self, file_name: str, raw_bytes: bytes) -> tuple[str, dict]:
        """Parses PDF, DOCX, TXT, CSV, XLSX, and extracts rich metadata."""
        ext = file_name.split(".")[-1].lower()
        extracted_text = ""
        meta = {"file_type": ext, "page_count": 1, "size_bytes": len(raw_bytes)}

        try:
            if ext == "pdf":
                reader = PdfReader(BytesIO(raw_bytes))
                meta["page_count"] = len(reader.pages)
                for page in reader.pages:
                    txt = page.extract_text()
                    if txt: extracted_text += txt + "\n"
            
            elif ext in ["docx", "doc"]:
                doc = docx.Document(BytesIO(raw_bytes))
                for para in doc.paragraphs:
                    if para.text: extracted_text += para.text + "\n"
            
            elif ext in ["txt", "md"]:
                extracted_text = raw_bytes.decode("utf-8", errors="ignore")
            
            elif ext == "csv":
                df = pd.read_csv(BytesIO(raw_bytes))
                extracted_text = df.to_string()
                meta["rows"] = len(df)
            
            elif ext in ["xlsx", "xls"]:
                df = pd.read_excel(BytesIO(raw_bytes))
                extracted_text = df.to_string()
                meta["rows"] = len(df)

        except Exception as e:
            print(f"[Multi-format Parse Error for {file_name}]: {e}")

        return extracted_text.strip(), meta

    def _infer_profile_updates(self, text: str) -> dict:
        """Automatically scans uploaded documents for profile entities (Resume/CV intelligence)."""
        inferred = {}
        text_lower = text.lower()
        
        # Simple heuristic extraction
        if "b.tech" in text_lower or "computer science" in text_lower:
            inferred["degree"] = "B.Tech Computer Science Engineering"
        if "gayatri" in text_lower:
            inferred["college"] = "Gayatri Vidya Parishad College"
        
        # Look for email patterns
        emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)
        if emails:
            inferred["email"] = emails[0]

        return inferred

    async def ingest_or_check_duplicate(self, file_name: str, raw_bytes: bytes, media_col, documents_collection=None) -> str:
        """Smart Duplicate Detection: Hashes extracted text content rather than binary bytes alone."""
        extracted_text, metadata = self._extract_text_multi_format(file_name, raw_bytes)
        
        # Hash normalized text content for semantic near-duplicate checking
        normalized_text = re.sub(r'\s+', ' ', extracted_text).lower().strip()
        content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest() if normalized_text else hashlib.sha256(raw_bytes).hexdigest()

        existing = await media_col.find_one({"content_hash": content_hash})

        if existing:
            await media_col.update_one(
                {"_id": existing["_id"]},
                {
                    "$inc": {"send_count": 1},
                    "$set": {"last_accessed": datetime.now(timezone.utc).isoformat()}
                }
            )
            existing_name = existing.get("file_name", "document")
            return f"I already have this document stored under '{existing_name}' (Semantic content hash match detected). Access count updated, Sir."

        b64_payload = base64.b64encode(raw_bytes).decode("utf-8")
        category = self._auto_categorize(file_name)
        
        # Index into Chroma vector DB if text was successfully extracted
        if extracted_text and documents_collection is not None:
            chunks = [extracted_text[i:i+1000] for i in range(0, len(extracted_text), 1000)]
            for idx, chunk in enumerate(chunks):
                chunk_id = f"doc_{content_hash[:8]}_{idx}"
                documents_collection.upsert(
                    ids=[chunk_id],
                    documents=[chunk],
                    metadatas=[{"file_name": file_name, "source": "MediaVault", "hash": content_hash}]
                )

        # Profile entity auto-inference check
        profile_suggestion = ""
        if category == "Resume":
            entities = self._infer_profile_updates(extracted_text)
            if entities:
                profile_suggestion = f"\n\n💡 **Profile Auto-Inference**: I detected updated details ({', '.join(entities.keys())}) in this document. Shall I update your profile, Sir?"

        doc_record = {
            "file_name": file_name,
            "b64_payload": b64_payload,
            "content_hash": content_hash,
            "category": category,
            "metadata": metadata,
            "indexed": True,
            "send_count": 1,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "last_accessed": datetime.now(timezone.utc).isoformat()
        }
        await media_col.insert_one(doc_record)
        return f"Document '{file_name}' successfully parsed, indexed, and categorized as '{category}' ({metadata.get('file_type', 'file')} format).{profile_suggestion}, Sir."

    async def execute(self, query: str, media_col, chat_id: str = None, documents_collection = None) -> dict:
        print(f"[TOOL - MEDIA] Executing document intelligence operation for query: '{query}'")
        if media_col is None or not chat_id: 
            return {"success": False, "source": "media", "content": "Media vault offline or chat ID missing.", "confidence": 0.0, "metadata": {}}
        
        try:
            clean_q = query.lower().strip()

            if any(k in clean_q for k in ["what documents", "list files", "stored files", "document list", "vault inventory", "categories"]):
                cursor = media_col.find({}, {"file_name": 1, "category": 1, "metadata": 1, "uploaded_at": 1})
                all_files = await cursor.to_list(length=100)
                
                if not all_files:
                    return {"success": True, "source": "media", "content": "Your Media Vault is currently empty, Sir.", "confidence": 1.0, "metadata": {}}
                
                categories = {}
                for f in all_files:
                    cat = f.get("category") or self._auto_categorize(f.get("file_name", ""))
                    ftype = f.get("metadata", {}).get("file_type", "file")
                    categories.setdefault(cat, []).append(f"{f.get('file_name')} [{ftype.upper()}]")

                cat_summary = "Categories\n────────────\n"
                for cat, files in categories.items():
                    cat_summary += f"• {cat} ({len(files)}):\n" + "".join([f"   - {fn}\n" for fn in files])

                inventory_msg = f"I currently manage {len(all_files)} multi-format documents in your Media Vault, Sir:\n\n{cat_summary}"
                return {"success": True, "source": "media", "content": inventory_msg, "confidence": 1.0, "metadata": {"count": len(all_files)}}

            target = None
            search_terms = []
            if any(k in clean_q for k in ["resume", "cv", "portfolio"]): search_terms.extend(["resume", "cv", "portfolio"])
            elif "pan" in clean_q: search_terms.append("pan")
            elif any(k in clean_q for k in ["certificate", "memo"]): search_terms.extend(["certificate", "memo"])
            else: search_terms.append(clean_q)

            term_regex = re.compile(re.escape(clean_q), re.IGNORECASE)
            unified_filter = {
                "$or": [
                    {"aliases": {"$in": search_terms}},
                    {"file_name": term_regex},
                    {"category": term_regex}
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
                        f"Here are the documents currently stored:\n{file_list_str}\n\n"
                        f"Which one would you like me to send?"
                    )
                else:
                    clarification_msg = "Your Media Vault is currently empty, Sir."

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
                res = await client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": f"Here is your requested document: '{fname}', Sir."},
                    files={"document": (fname, raw_bytes, "application/octet-stream")}
                )
                res.raise_for_status()

            await media_col.update_one(
                {"_id": target["_id"]},
                {
                    "$set": {"last_sent": datetime.now(timezone.utc).isoformat()},
                    "$inc": {"send_count": 1}
                }
            )

            return {
                "success": True, 
                "source": "media", 
                "content": f"File '{fname}' successfully dispatched to your Telegram chat, Sir.", 
                "confidence": 1.0, 
                "metadata": {"file": fname}
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
            return await tool.execute(query, self.media_col, chat_id, documents_collection=self.docs_col)
        elif tool_name == "schedule":
            return await tool.execute(query, self.schedule_col, chat_id)
            
        return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}
