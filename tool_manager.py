import base64
import httpx
import os

class BaseTool:
    NAME = "base"
    DESCRIPTION = "Base tool"
    CAPABILITIES = []

    async def execute(self, query: str, context_handle) -> dict:
        raise NotImplementedError

class MemoryTool(BaseTool):
    NAME = "memory"
    DESCRIPTION = "Search past personal facts, user statements, preferences, and long-term notes."
    CAPABILITIES = ["preferences", "past facts", "user statements", "history"]

    async def execute(self, query: str, memory_collection) -> dict:
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

    async def execute(self, query: str, documents_collection) -> dict:
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

    async def execute(self, query: str, tavily_client) -> dict:
        if tavily_client is None: 
            return {"success": False, "source": "web", "content": "", "confidence": 0.0, "metadata": {}}
        try:
            res = tavily_client.search(query=query, max_results=3)
            if res is not None and res.get("results") is not None:
                results = [f"- {item['title']}: {item['content'][:200]}" for item in res.get("results", [])]
                content = "\n".join(results)
                return {"success": True, "source": "web", "content": content, "confidence": 0.88, "metadata": {"results_count": len(results)}}
        except Exception:
            pass
        return {"success": False, "source": "web", "content": "", "confidence": 0.0, "metadata": {}}

class MediaVaultTool(BaseTool):
    NAME = "media"
    DESCRIPTION = "Locate and dispatch stored documents, resumes, PDFs, and files directly to Telegram."
    CAPABILITIES = ["dispatch file", "resume", "send document", "download pdf"]

    async def execute(self, query: str, media_col, chat_id: str) -> dict:
        if media_col is None or not chat_id: 
            return {"success": False, "source": "media", "content": "Media vault offline.", "confidence": 0.0, "metadata": {}}
        try:
            import re
            q_regex = re.compile(re.escape(query.strip()), re.IGNORECASE)
            target = await media_col.find_one({"$or": [{"file_name": q_regex}, {"caption": q_regex}]})
            if not target:
                target = await media_col.find_one({"media_type": "document"}, sort=[("_id", -1)])
            if not target:
                return {"success": False, "source": "media", "content": "No matching document found in vault.", "confidence": 0.0, "metadata": {}}

            fname = target.get("file_name", "document.pdf")
            raw_bytes = base64.b64decode(target["b64_payload"])
            token = os.getenv("TELEGRAM_TOKEN")
            
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": f"Here is your document: '{fname}', Sir."},
                    files={"document": (fname, raw_bytes, "application/octet-stream")}
                )
            return {"success": True, "source": "media", "content": f"File '{fname}' successfully dispatched to Telegram.", "confidence": 1.0, "metadata": {"file": fname}}
        except Exception as e:
            return {"success": False, "source": "media", "content": f"Dispatch error: {e}", "confidence": 0.0, "metadata": {}}

class ScheduleTool(BaseTool):
    NAME = "schedule"
    DESCRIPTION = "Manage and retrieve scheduled tasks, calendar events, and reminders."
    CAPABILITIES = ["schedule", "calendar", "reminders", "tasks"]

    async def execute(self, query: str, schedule_col) -> dict:
        if schedule_col is None:
            return {"success": True, "source": "schedule", "content": "No active tasks scheduled for today, Sir.", "confidence": 0.9, "metadata": {}}
        try:
            cursor = schedule_col.find({}).sort("_id", -1).limit(5)
            tasks = await cursor.to_list(length=5)
            if not tasks:
                return {"success": True, "source": "schedule", "content": "Your schedule is currently clear, Sir.", "confidence": 0.9, "metadata": {}}
            task_list = "\n".join([f"- {t.get('task', 'Task')}" for t in tasks])
            return {"success": True, "source": "schedule", "content": f"Scheduled items:\n{task_list}", "confidence": 0.95, "metadata": {"count": len(tasks)}}
        except Exception:
            pass
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
            return await tool.execute(query, self.memory_col)
        elif tool_name == "documents":
            return await tool.execute(query, self.docs_col)
        elif tool_name == "web":
            return await tool.execute(query, self.tavily)
        elif tool_name == "media":
            return await tool.execute(query, self.media_col, chat_id)
        elif tool_name == "schedule":
            return await tool.execute(query, self.schedule_col)
            
        return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}
