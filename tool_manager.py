import os
import json
import base64
import asyncio
from datetime import datetime, timezone

class ToolManager:
    def __init__(self, chroma_memory, chroma_docs, mongo_media, mongo_schedule, tavily_client, aria_brain = None):
        self.mem_col = chroma_memory
        self.docs_col = chroma_docs
        self.media_col = mongo_media
        self.schedule_col = mongo_schedule
        self.tavily = tavily_client
        self.brain = aria_brain

    def describe_tools(self) -> dict:
        """Returns descriptive capabilities of all available system tools for the action planner."""
        return {
            "memory": "Searches permanent user memory and personal facts.",
            "documents": "Searches the Chroma vector database for indexed text content, notes, and manuals.",
            "web": "Performs real-time web searches using Tavily for news, facts, and live data.",
            "media": "Manages the Media Vault, retrieving stored files, documents, resumes, PDFs, and metadata.",
            "schedule": "Manages tasks, reminders, calendars, and daily agendas."
        }

    async def execute_tool(self, tool_name: str, query: str, chat_id: str = "default") -> dict:
        """Dispatches tool execution requests with unified brain fallback integration."""
        tool_lower = tool_name.lower().strip()
        
        if tool_lower == "memory":
            return await self._handle_memory(query)
        elif tool_lower == "documents":
            return await self._handle_documents(query)
        elif tool_lower == "web":
            return await self._handle_web(query)
        elif tool_lower == "media":
            return await self._handle_media(query)
        elif tool_lower == "schedule":
            return await self._handle_schedule(query)
        else:
            return {"success": False, "content": f"Unknown tool requested: {tool_name}"}

    async def _handle_memory(self, query: str) -> dict:
        if self.mem_col is None:
            return {"success": False, "content": "Memory vector store offline, Sir."}
        try:
            hits = self.mem_col.query(query_texts=[query], n_results=3)
            docs = hits.get("documents", [[]])[0]
            if not docs:
                return {"success": True, "content": "No specific memories found matching your query, Sir."}
            return {"success": True, "content": "\n".join([f"• {d}" for d in docs])}
        except Exception as e:
            return {"success": False, "content": f"Memory search failed: {e}"}

    async def _handle_documents(self, query: str) -> dict:
        # First consult AriaBrain for unified metadata and alias hits
        if self.brain is not None:
            brain_res = await self.brain.search(query) if hasattr(self.brain.search, '__code__') and asyncio.iscoroutinefunction(self.brain.search) else self.brain.search(query)
            if brain_res and brain_res.get("documents"):
                doc_list = "\n".join([f"• **{d.get('title')}** (`{d.get('filename')}`)\n  *{d.get('summary')}*" for d in brain_res["documents"]])
                return {
                    "success": True,
                    "content": f"Yes, Sir. I found documents matching your request:\n\n{doc_list}"
                }

        if self.docs_col is None:
            return {"success": False, "content": "Document vector store offline, Sir."}
        try:
            hits = self.docs_col.query(query_texts=[query], n_results=3)
            docs = hits.get("documents", [[]])[0]
            if not docs:
                return {"success": True, "content": "No matching document segments found in the vector vault, Sir."}
            return {"success": True, "content": "\n\n--- Document Match ---\n".join(docs)}
        except Exception as e:
            return {"success": False, "content": f"Document search failed: {e}"}

    async def _handle_web(self, query: str) -> dict:
        if self.tavily is None:
            return {"success": False, "content": "Web search unconfigured — Tavily API key missing, Sir."}
        try:
            def _search():
                return self.tavily.search(query=query, max_results=3)
            res = await asyncio_to_thread_safe(_search)
            results = res.get("results", [])
            if not results:
                return {"success": True, "content": "No live web results found, Sir."}
            formatted = [f"• **{r.get('title')}**\n  {r.get('content')}\n  *(Source: {r.get('url')})*" for r in results]
            return {"success": True, "content": "\n\n".join(formatted)}
        except Exception as e:
            return {"success": False, "content": f"Web search failed: {e}"}

    async def _handle_media(self, query: str) -> dict:
        """Unified media vault lookup with AriaBrain alias and summary matching."""
        if self.brain is not None:
            brain_res = await self.brain.search(query) if hasattr(self.brain.search, '__code__') and asyncio.iscoroutinefunction(self.brain.search) else self.brain.search(query)
            if brain_res and brain_res.get("documents"):
                doc_list = "\n".join([f"• **{d.get('title')}** (`{d.get('filename')}`)\n  *{d.get('summary')}*" for d in brain_res["documents"]])
                return {
                    "success": True,
                    "content": f"Yes, Sir. I located the following files in your Media Vault:\n\n{doc_list}"
                }

        if self.media_col is None:
            return {"success": False, "content": "Media Vault storage offline, Sir."}
        try:
            cursor = self.media_col.find({})
            files = await cursor.to_list(length=50)
            if not files:
                return {"success": True, "content": "Your Media Vault is currently empty, Sir."}
            
            q_lower = query.lower()
            matched = []
            for f in files:
                fname = f.get("file_name", "").lower()
                cat = f.get("category", "").lower()
                if any(w in fname or w in cat for w in q_lower.split() if len(w) > 2) or "list" in q_lower or "all" in q_lower or "what" in q_lower:
                    matched.append(f)

            if not matched and not ("list" in q_lower or "all" in q_lower):
                matched = files[:10]

            file_strs = [f"• **{f.get('file_name')}** (Category: {f.get('category', 'General')})" for f in matched]
            return {
                "success": True,
                "content": f"Found {len(matched)} matching document(s) in your Media Vault:\n\n" + "\n".join(file_strs)
            }
        except Exception as e:
            return {"success": False, "content": f"Media vault lookup failed: {e}"}

    async def _handle_schedule(self, query: str) -> dict:
        if self.schedule_col is None:
            return {"success": False, "content": "Schedule subsystem offline, Sir."}
        try:
            cursor = self.schedule_col.find({})
            tasks = await cursor.to_list(length=20)
            if not tasks:
                return {"success": True, "content": "Your schedule is completely clear, Sir."}
            task_strs = [f"• [{t.get('time', 'Today')}] {t.get('task')}" for t in tasks]
            return {"success": True, "content": "Current Schedule & Reminders:\n\n" + "\n".join(task_strs)}
        except Exception as e:
            return {"success": False, "content": f"Schedule retrieval failed: {e}"}

    async def ingest_uploaded_file(self, file_id: str, filename: str, file_bytes: bytes, category: str = "document"):
        """Ingests uploaded files into Mongo Media Vault and registers rich metadata in AriaBrain."""
        if self.media_col is not None:
            await self.media_col.update_one(
                {"file_name": filename},
                {
                    "$set": {
                        "file_id": file_id,
                        "file_name": filename,
                        "category": category,
                        "data_base64": base64.b64encode(file_bytes).decode('utf-8'),
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                },
                upsert=True
            )

        if self.brain is not None:
            extracted_text = f"Document filename: {filename}. Category: {category}."
            from brain.models.request import BrainRequest
            req = BrainRequest(query=filename, metadata={"doc_id": file_id})
            if hasattr(self.brain, "learn"):
                await self.brain.learn(req, filename, extracted_text)

        print(f"[ToolManager]: Successfully ingested and registered file '{filename}' across Vault and Brain, Sir.")

async def asyncio_to_thread_safe(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)
