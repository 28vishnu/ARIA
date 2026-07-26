import os

class SpecialistAgentManager:
    def __init__(self, tool_mgr, llm_router):
        self.tool_mgr = tool_mgr
        self.llm_router = llm_router

    async def dispatch_agent(self, agent_name: str, query: str, chat_id: str = None) -> str:
        """Dispatches tasks to specialized expert agents."""
        agent_name = agent_name.lower()
        print(f"[SPECIALIST AGENT]: Dispatching task to '{agent_name}' agent...")

        if agent_name == "media" or agent_name == "file":
            res = await self.tool_mgr.execute_tool("media", query, chat_id=chat_id)
            return res.get("content", "Media operation completed.")
        
        elif agent_name == "research" or agent_name == "web":
            res = await self.tool_mgr.execute_tool("web", query, chat_id=chat_id)
            return res.get("content", "Research search completed.")

        elif agent_name == "memory" or agent_name == "profile":
            res = await self.tool_mgr.execute_tool("memory", query, chat_id=chat_id)
            return res.get("content", "Memory retrieval completed.")

        elif agent_name == "coding" or agent_name == "code":
            messages = [
                {"role": "system", "content": "You are ARIA's senior software engineering agent. Provide clean, production-ready code with concise explanations."},
                {"role": "user", "content": query}
            ]
            return await self.llm_router.chat(messages, temperature=0.1, max_tokens=600)

        else:
            # Default fallback to general reasoning/tool execution
            return f"Specialist agent '{agent_name}' processed request: {query}"
