from typing import Optional, Dict, Any, List
import logging
import asyncio

logger = logging.getLogger("aria")


class KnowledgeManager:

    def __init__(
        self,
        document_ai,
        memory_engine,
        state_manager,
        knowledge_database=None,
        knowledge_graph=None,
        learning_engine=None,
        world_model=None,
        memory_router=None,
        skill_manager=None,
        web_search=None,
        llm_router=None,
        event_bus=None,
    ):

        self.document_ai = document_ai
        self.memory_engine = memory_engine
        self.state_manager = state_manager

        self.knowledge_database = knowledge_database
        self.knowledge_graph = knowledge_graph
        self.learning_engine = learning_engine

        self.world_model = world_model
        self.memory_router = memory_router
        self.skill_manager = skill_manager
        self.web_search = web_search
        self.llm_router = llm_router
        self.event_bus = event_bus

    ###########################################################
    # Unified Search Entrypoint
    ###########################################################

    async def search(self, query: str):
        """
        Unified knowledge search entrypoint.
        """
        results = []

        if self.document_ai:
            try:
                docs = None
                if hasattr(self.document_ai, "search"):
                    docs = await self.document_ai.search(query)
                elif hasattr(self.document_ai, "retrieve"):
                    docs = await self.document_ai.retrieve(query)
                elif hasattr(self.document_ai, "semantic_search"):
                    docs = await self.document_ai.semantic_search(query)
                elif hasattr(self.document_ai, "find"):
                    docs = await self.document_ai.find(query)

                if docs:
                    results.extend(docs)
            except Exception:
                pass

        if self.knowledge_database:
            try:
                kb = None
                if hasattr(self.knowledge_database, "search"):
                    kb = await self.knowledge_database.search(query)
                elif hasattr(self.knowledge_database, "retrieve"):
                    kb = await self.knowledge_database.retrieve(query)

                if kb:
                    results.extend(kb)
            except Exception:
                pass

        return results

    ###########################################################
    # Individual Search Methods
    ###########################################################

    async def search_working_memory(self, question: str) -> List[Dict[str, Any]]:
        if self.memory_router and hasattr(self.memory_router, "snapshot"):
            snap = self.memory_router.snapshot()
            if snap:
                return [{
                    "source": "working_memory",
                    "confidence": 0.98,
                    "importance": 90,
                    "content": str(snap),
                }]
        return []

    async def search_memory(self, question: str) -> List[Dict[str, Any]]:
        if self.memory_engine and hasattr(self.memory_engine, "get_relevant_memories"):
            mems = await self.memory_engine.get_relevant_memories(question)
            if mems:
                normalized = []
                for m in mems:
                    content = m.get("content", str(m)) if isinstance(m, dict) else str(m)
                    normalized.append({
                        "source": "memory",
                        "confidence": 0.94,
                        "importance": 80,
                        "content": content,
                    })
                return normalized
        return []

    async def search_database(self, question: str) -> List[Dict[str, Any]]:
        if self.knowledge_database and hasattr(self.knowledge_database, "retrieve"):
            kb_res = await self.knowledge_database.retrieve(question)
            if kb_res:
                normalized = []
                for item in kb_res:
                    content = item.get("content", str(item)) if isinstance(item, dict) else str(item)
                    conf = item.get("confidence", 0.85)
                    imp = item.get("importance", 50)
                    normalized.append({
                        "source": "knowledge_database",
                        "confidence": conf,
                        "importance": imp,
                        "content": content,
                    })
                return normalized
        return []

    async def search_graph(self, question: str) -> List[Dict[str, Any]]:
        if self.knowledge_graph and hasattr(self.knowledge_graph, "search"):
            g_res = await self.knowledge_graph.search(question)
            if g_res:
                normalized = []
                for item in g_res:
                    content = str(item)
                    normalized.append({
                        "source": "knowledge_graph",
                        "confidence": 0.81,
                        "importance": 60,
                        "content": content,
                    })
                return normalized
        return []

    async def search_world(self, question: str) -> List[Dict[str, Any]]:
        if self.world_model and hasattr(self.world_model, "search"):
            w_res = await self.world_model.search(question)
            if asyncio.iscoroutine(w_res):
                w_res = await w_res
            if w_res:
                normalized = []
                for k, v in w_res.items():
                    if v:
                        normalized.append({
                            "source": "world_model",
                            "confidence": 0.91,
                            "importance": 70,
                            "content": f"{k}: {v}",
                        })
                return normalized
        return []

    async def search_documents(self, session_id: str, question: str) -> List[Dict[str, Any]]:
        state = self.state_manager.get_state(session_id)
        if state.get("active_document") and self.document_ai:
            doc_ans = await self.document_ai.answer_question(
                session_id=session_id,
                question=question,
                state=state,
            )
            if doc_ans:
                return [{
                    "source": "document",
                    "confidence": 0.95,
                    "importance": 85,
                    "content": str(doc_ans),
                }]
        return []

    async def search_skills(self, question: str) -> List[Dict[str, Any]]:
        if self.skill_manager and hasattr(self.skill_manager, "route_and_execute"):
            try:
                skill_res = await self.skill_manager.route_and_execute(question, {})
                if skill_res and skill_res.success:
                    msg = skill_res.data.get("response") or skill_res.data.get("message") or str(skill_res.data)
                    return [{
                        "source": "skill",
                        "confidence": 0.80,
                        "importance": 50,
                        "content": msg,
                    }]
            except Exception:
                pass
        return []

    ###########################################################
    # Merge, Rank & Retrieve Pipeline
    ###########################################################

    async def merge_results(
        self,
        *sources,
    ) -> List[Dict[str, Any]]:
        flattened = []
        seen = set()
        for source_list in sources:
            if not source_list:
                continue
            if not isinstance(source_list, list):
                source_list = [source_list]
            for item in source_list:
                if isinstance(item, dict):
                    content = item.get("content", "")
                else:
                    content = str(item)
                    item = {
                        "source": "unknown",
                        "confidence": 0.5,
                        "importance": 50,
                        "content": content,
                    }
                if content not in seen:
                    seen.add(content)
                    flattened.append(item)
        return flattened

    async def rank_results(
        self,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        source_priority = {
            "document": 7,
            "working_memory": 6,
            "memory": 5,
            "knowledge_database": 4,
            "knowledge_graph": 3,
            "world_model": 2,
            "skill": 1,
        }

        def sort_key(item):
            src = item.get("source", "unknown")
            prio = source_priority.get(src, 0)
            conf = item.get("confidence", 0.5)
            imp = item.get("importance", 50)
            return (prio, conf, imp)

        return sorted(results, key=sort_key, reverse=True)

    async def retrieve(
        self,
        session_id: str,
        question: str,
    ) -> List[Dict[str, Any]]:
        try:
            working = await self.search_working_memory(question)
        except Exception:
            logger.exception("Working memory search failed")
            working = []

        try:
            memory = await self.search_memory(question)
        except Exception:
            logger.exception("Memory search failed")
            memory = []

        try:
            knowledge = await self.search_database(question)
        except Exception:
            logger.exception("Database search failed")
            knowledge = []

        try:
            graph = await self.search_graph(question)
        except Exception:
            logger.exception("Graph search failed")
            graph = []

        try:
            world = await self.search_world(question)
        except Exception:
            logger.exception("World model search failed")
            world = []

        try:
            documents = await self.search_documents(session_id, question)
        except Exception:
            logger.exception("Document search failed")
            documents = []

        try:
            skills = await self.search_skills(question)
        except Exception:
            logger.exception("Skills search failed")
            skills = []

        merged = await self.merge_results(
            working,
            memory,
            knowledge,
            graph,
            world,
            documents,
            skills,
        )
        return await self.rank_results(merged)

    ###########################################################
    # Web Decision & Retrieval
    ###########################################################

    async def needs_web(
        self,
        results: List[Dict[str, Any]],
    ) -> bool:
        if not results:
            return True
        top_conf = results[0].get("confidence", 0.0)
        if top_conf < 0.40:
            return True
        return False

    async def search_web(
        self,
        question: str,
    ) -> Optional[Dict[str, Any]]:
        if self.web_search and hasattr(self.web_search, "execute"):
            try:
                res = await self.web_search.execute({"query": question})
                if res and res.success:
                    answer = res.data.get("result") or res.data.get("content") or str(res.data)
                    if self.learning_engine:
                        await self.learning_engine.learn(
                            text=answer,
                            source="web",
                        )
                    return {
                        "source": "web_search",
                        "confidence": 0.75,
                        "importance": 70,
                        "content": answer,
                    }
            except Exception:
                pass
        return None

    ###########################################################
    # Best Answer & Explanation
    ###########################################################

    async def explain_sources(
        self,
        results: List[Dict[str, Any]],
    ) -> List[str]:
        return list(set(item.get("source", "unknown") for item in results))

    async def best_answer(
        self,
        question: str,
        results: List[Dict[str, Any]],
    ) -> str:
        if not results:
            return "I couldn't find any relevant information."

        if len(results) == 1 or results[0].get("confidence", 0) > 0.92:
            return results[0].get("content", "")

        # Multiple results -> synthesize using LLM if available
        if self.llm_router and hasattr(self.llm_router, "chat"):
            evidence_str = "\n\n".join(f"Evidence ({r.get('source')}): {r.get('content')}" for r in results[:5])
            messages = [
                {"role": "system", "content": "You are ARIA, a helpful AI assistant. Synthesize the provided evidence into one coherent answer without inventing facts."},
                {"role": "user", "content": f"Question: {question}\n\n{evidence_str}"}
            ]
            try:
                synth = await self.llm_router.chat(messages)
                if synth:
                    return synth
            except Exception:
                pass

        return results[0].get("content", "")

    async def remember_answer(
        self,
        question: str,
        answer: str,
        source: str,
    ):
        if self.knowledge_database and hasattr(self.knowledge_database, "store"):
            await self.knowledge_database.store(
                title=question[:50],
                content=answer,
                source=source,
            )
        if self.learning_engine and hasattr(self.learning_engine, "learn"):
            await self.learning_engine.learn(
                text=answer,
                source=source,
            )

    ###########################################################
    # Main Search Pipeline
    ###########################################################

    async def answer(
        self,
        session_id,
        question,
    ):
        results = await self.retrieve(session_id, question)

        if await self.needs_web(results):
            web_res = await self.search_web(question)
            if web_res:
                results.insert(0, web_res)

        if not results:
            return None

        final_answer = await self.best_answer(question, results)
        return final_answer

    ###########################################################
    # Learn New Knowledge
    ###########################################################

    async def learn(
        self,
        text,
        source="conversation"
    ):

        if self.learning_engine:

            await self.learning_engine.learn(
                text=text,
                source=source,
            )

    ###########################################################
    # Store Structured Fact
    ###########################################################

    async def remember_fact(
        self,
        subject,
        relation,
        value
    ):

        if self.knowledge_graph:

            await self.knowledge_graph.add_fact(
                subject,
                relation,
                value
            )

    ###########################################################
    # Save Knowledge
    ###########################################################

    async def save_knowledge(
        self,
        title,
        content,
        source="conversation"
    ):

        if self.knowledge_database:

            await self.knowledge_database.store(
                title=title,
                content=content,
                source=source
            )
