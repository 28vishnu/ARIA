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
            if results and results.get("documents") and results["documents"][0]:
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
            if results and results.get("documents") and results["documents"][0]:
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
            results = [f"- {item['title']}: {item['content'][:200]}" for item in res.get("results", [])]
            content = "\n".join(results)
            return {"success": True, "source": "web", "content": content, "confidence": 0.88, "metadata": {"results_count": len(results)}}
        except Exception:
            pass
        return {"success": False, "source": "web", "content": "", "confidence": 0.0, "metadata": {}}

class ToolManager:
    def __init__(self, memory_col, docs_col, tavily):
        self.registry = {
            "memory": MemoryTool(),
            "documents": DocumentTool(),
            "web": SearchTool()
        }
        self.memory_col = memory_col
        self.docs_col = docs_col
        self.tavily = tavily

    def describe_tools(self) -> dict:
        descriptions = {}
        for name, tool in self.registry.items():
            descriptions[name] = {
                "description": tool.DESCRIPTION,
                "capabilities": tool.CAPABILITIES
            }
        return descriptions

    async def execute_tool(self, tool_name: str, query: str) -> dict:
        tool = self.registry.get(tool_name)
        if tool is None: 
            return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}

        if tool_name == "memory":
            return await tool.execute(query, self.memory_col)
        elif tool_name == "documents":
            return await tool.execute(query, self.docs_col)
        elif tool_name == "web":
            return await tool.execute(query, self.tavily)
        return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}
