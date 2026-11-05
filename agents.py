import os
import asyncio
from brain.integrations.public_knowledge import (
    get_weather, 
    get_book_info, 
    get_academic_paper, 
    get_wikipedia_summary,
    get_space_info,
    get_ip_info,
    get_dns_records
)
from brain.system.controller import get_system_telemetry

class SpecialistAgentManager:
    def __init__(self, tool_mgr, llm_router):
        self.tool_mgr = tool_mgr
        self.llm_router = llm_router

    async def dispatch_agent(self, agent_name: str, query: str, chat_id: str = None) -> str:
        agent_name = agent_name.lower()
        print(f"[SPECIALIST AGENT]: Dispatching task to '{agent_name}' agent...")

        q_lower = query.lower()

        # System Control & Health
        if "system status" in q_lower or "cpu" in q_lower or "ram" in q_lower or "battery" in q_lower:
            stats = get_system_telemetry()
            return f"Host System Telemetry: {stats}"

        # Network & IP Lookups
        elif "ip" in q_lower and ("lookup" in q_lower or "check" in q_lower or "info" in q_lower):
            target = query.replace("ip", "").replace("lookup", "").replace("check", "").strip() or "8.8.8.8"
            res = await get_ip_info(target)
            return f"IP Telemetry (Saved to {res.get('saved_path')}): {res}"

        elif "dns" in q_lower:
            domain = query.replace("dns", "").replace("lookup", "").replace("for", "").strip() or "example.com"
            res = await get_dns_records(domain)
            return f"DNS Data (Saved to {res.get('saved_path')}): {res}"

        # Public Knowledge & Weather
        elif "weather" in q_lower:
            city_query = query.replace("weather", "").replace("in", "").strip() or "Visakhapatnam"
            res = await get_weather(city_query)
            return f"Weather Data (Saved to {res.get('saved_path')}): {res}"

        elif "space" in q_lower or "astronaut" in q_lower:
            res = await get_space_info()
            return f"Space Intelligence (Saved to {res.get('saved_path')}): {res}"

        elif "book" in q_lower or "read" in q_lower:
            res = await get_book_info(query)
            return f"Book Intelligence (Saved to {res.get('saved_path') if res else 'N/A'}): {res}"

        elif "paper" in q_lower or "science" in q_lower:
            res = await get_academic_paper(query)
            return f"Academic Research (Saved to {res.get('saved_path') if res else 'N/A'}): {res}"

        elif any(k in q_lower for k in ["what is", "who is", "explain", "wiki"]):
            res = await get_wikipedia_summary(query)
            return f"Wikipedia Knowledge (Saved to {res.get('saved_path') if res else 'N/A'}): {res}"

        # Default Agent Fallbacks
        if agent_name in ("media", "file"):
            res = await self.tool_mgr.execute_tool("media", query, chat_id=chat_id)
            return res.get("content", "Media operation completed.")

        elif agent_name in ("research", "web"):
            res = await self.tool_mgr.execute_tool("web", query, chat_id=chat_id)
            return res.get("content", "Research search completed.")

        elif agent_name in ("memory", "profile"):
            res = await self.tool_mgr.execute_tool("memory", query, chat_id=chat_id)
            return res.get("content", "Memory retrieval completed.")

        elif agent_name in ("coding", "code"):
            messages = [
                {"role": "system", "content": "You are ARIA's senior software engineering agent. Provide clean, production-ready code with concise explanations."},
                {"role": "user", "content": query}
            ]
            return await self.llm_router.chat(messages, temperature=0.1, max_tokens=600)

        else:
            return f"Specialist agent '{agent_name}' processed request: {query}"
