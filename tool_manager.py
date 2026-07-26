import base64
import re
import httpx
from datetime import datetime, timezone, timedelta
from docx import Document
from pypdf import PdfReader
import openpyxl
from io import BytesIO

class MemoryTool:
    async def execute(self, query: str, memory_collection) -> str:
        try:
            results = memory_collection.query(query_texts=[query], n_results=5)
            if results and results.get("documents"):
                return "[VECTOR MEMORY]:\n" + "\n".join(results["documents"][0])
        except Exception:
            pass
        return ""

class DocumentTool:
    async def execute(self, query: str, documents_collection) -> str:
        try:
            results = documents_collection.query(query_texts=[query], n_results=4)
            if results and results.get("documents"):
                return "[VECTOR DOCUMENTS]:\n" + "\n".join(results["documents"][0])
        except Exception:
            pass
        return ""

class SearchTool:
    async def execute(self, query: str, tavily_client) -> str:
        if not tavily_client: return ""
        try:
            res = tavily_client.search(query=query, max_results=3)
            results = [f"- {item['title']}: {item['content'][:200]}" for item in res.get("results", [])]
            return "[WEB INTELLIGENCE]:\n" + "\n".join(results)
        except Exception:
            pass
        return ""

class ToolManager:
    def __init__(self, memory_col, docs_col, tavily):
        self.tools = {
            "memory": MemoryTool(),
            "documents": DocumentTool(),
            "web": SearchTool()
        }
        self.memory_col = memory_col
        self.docs_col = docs_col
        self.tavily = tavily

    async def execute_plan(self, plan: dict, user_message: str) -> str:
        collected_context = []
        tools_to_run = plan.get("tools", [])

        for tool_name in tools_to_run:
            if tool_name == "memory" and self.memory_col:
                res = await self.tools["memory"].execute(user_message, self.memory_col)
                if res: collected_context.append(res)
            elif tool_name == "documents" and self.docs_col:
                res = await self.tools["documents"].execute(user_message, self.docs_col)
                if res: collected_context.append(res)
            elif tool_name == "web" and self.tavily:
                res = await self.tools["web"].execute(user_message, self.tavily)
                if res: collected_context.append(res)

        return "\n\n".join(collected_context)
