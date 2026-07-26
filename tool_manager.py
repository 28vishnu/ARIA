class BaseTool:
    NAME = "base"
    DESCRIPTION = "Base tool"
    CAPABILITIES = []

    async def execute(self, query: str, context_handle) -> str:
        raise NotImplementedError

class MemoryTool(BaseTool):
    NAME = "memory"
    DESCRIPTION = "Search past personal facts, user statements, preferences, and long-term notes."
    CAPABILITIES = ["preferences", "past facts", "user statements", "history"]

    async def execute(self, query: str, memory_collection) -> str:
        if not memory_collection: return ""
        try:
            results = memory_collection.query(query_texts=[query], n_results=5)
            if results and results.get("documents"):
                return "\n".join(results["documents"][0])
        except Exception:
            pass
        return ""

class DocumentTool(BaseTool):
    NAME = "documents"
    DESCRIPTION = "Search semantic vector embeddings inside uploaded PDFs, resumes, certificates, and spreadsheets."
    CAPABILITIES = ["resumes", "certificates", "PDFs", "spreadsheets", "notes"]

    async def execute(self, query: str, documents_collection) -> str:
        if not documents_collection: return ""
        try:
            results = documents_collection.query(query_texts=[query], n_results=4)
            if results and results.get("documents"):
                return "\n".join(results["documents"][0])
        except Exception:
            pass
        return ""

class SearchTool(BaseTool):
    NAME = "web"
    DESCRIPTION = "Search live internet intelligence, news, current events, and weather."
    CAPABILITIES = ["news", "weather", "current events", "live facts"]

    async def execute(self, query: str, tavily_client) -> str:
        if not tavily_client: return ""
        try:
            res = tavily_client.search(query=query, max_results=3)
            results = [f"- {item['title']}: {item['content'][:200]}" for item in res.get("results", [])]
            return "\n".join(results)
        except Exception:
            pass
        return ""

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
        """Dynamically inspects registered tools for capability discovery."""
        descriptions = {}
        for name, tool in self.registry.items():
            descriptions[name] = {
                "description": tool.DESCRIPTION,
                "capabilities": tool.CAPABILITIES
            }
        return descriptions

    async def execute_tool(self, tool_name: str, query: str) -> str:
        tool = self.registry.get(tool_name)
        if not tool: return ""

        if tool_name == "memory":
            return await tool.execute(query, self.memory_col)
        elif tool_name == "documents":
            return await tool.execute(query, self.docs_col)
        elif tool_name == "web":
            return await tool.execute(query, self.tavily)
        return ""
