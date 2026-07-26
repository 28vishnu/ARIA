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
        print("[TOOL - MEMORY] Executing vector memory search...")
        if memory_collection is None: 
            print("[TOOL - MEMORY] Error: memory_collection is None")
            return {"success": False, "source": "memory", "content": "", "confidence": 0.0, "metadata": {}}
        try:
            results = memory_collection.query(query_texts=[query], n_results=5)
            if results is not None and results.get("documents") is not None and len(results["documents"]) > 0 and results["documents"][0] is not None:
                content = "\n".join(results["documents"][0])
                print(f"[TOOL - MEMORY] Found {len(results['documents'][0])} matching memory entries.")
                return {"success": True, "source": "memory", "content": content, "confidence": 0.95, "metadata": {"count": len(results["documents"][0])}}
        except Exception as e:
            print(f"[TOOL - MEMORY EXCEPTION]: {e}")
        return {"success": False, "source": "memory", "content": "", "confidence": 0.0, "metadata": {}}

class DocumentTool(BaseTool):
    NAME = "documents"
    DESCRIPTION = "Search semantic vector embeddings inside uploaded PDFs, resumes, certificates, and spreadsheets."
    CAPABILITIES = ["resumes", "certificates", "PDFs", "spreadsheets", "notes"]

    async def execute(self, query: str, documents_collection) -> dict:
        print("[TOOL - DOCUMENTS] Executing vector document vault search...")
        if documents_collection is None: 
            print("[TOOL - DOCUMENTS] Error: documents_collection is None")
            return {"success": False, "source": "documents", "content": "", "confidence": 0.0, "metadata": {}}
        try:
            results = documents_collection.query(query_texts=[query], n_results=4)
            if results is not None and results.get("documents") is not None and len(results["documents"]) > 0 and results["documents"][0] is not None:
                content = "\n".join(results["documents"][0])
                print(f"[TOOL - DOCUMENTS] Found {len(results['documents'][0])} matching document chunks.")
                return {"success": True, "source": "documents", "content": content, "confidence": 0.92, "metadata": {"source_files": results.get("metadatas", [{}])}}
        except Exception as e:
            print(f"[TOOL - DOCUMENTS EXCEPTION]: {e}")
        return {"success": False, "source": "documents", "content": "", "confidence": 0.0, "metadata": {}}

class SearchTool(BaseTool):
    NAME = "web"
    DESCRIPTION = "Search live internet intelligence, news, current events, and weather."
    CAPABILITIES = ["news", "weather", "current events", "live facts"]

    async def execute(self, query: str, tavily_client) -> dict:
        print("[TOOL - WEB] Executing Tavily web search...")
        if tavily_client is None: 
            print("[TOOL - WEB] Error: tavily_client is None")
            return {"success": False, "source": "web", "content": "", "confidence": 0.0, "metadata": {}}
        try:
            res = tavily_client.search(query=query, max_results=3)
            if res is not None and res.get("results") is not None:
                results = [f"- {item['title']}: {item['content'][:200]}" for item in res.get("results", [])]
                content = "\n".join(results)
                print(f"[TOOL - WEB] Retrieved {len(results)} web results.")
                return {"success": True, "source": "web", "content": content, "confidence": 0.88, "metadata": {"results_count": len(results)}}
        except Exception as e:
            print(f"[TOOL - WEB EXCEPTION]: {e}")
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
        print(f"[TOOL MANAGER] Dispatching tool execution for: '{tool_name}' with query: '{query}'")
        tool = self.registry.get(tool_name)
        if tool is None: 
            print(f"[TOOL MANAGER] Warning: Tool '{tool_name}' not found in registry.")
            return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}

        if tool_name == "memory":
            if self.memory_col is None:
                return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}
            return await tool.execute(query, self.memory_col)
        elif tool_name == "documents":
            if self.docs_col is None:
                return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}
            return await tool.execute(query, self.docs_col)
        elif tool_name == "web":
            if self.tavily is None:
                return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}
            return await tool.execute(query, self.tavily)
            
        return {"success": False, "source": tool_name, "content": "", "confidence": 0.0, "metadata": {}}
