import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from brain.agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("aria")


class AgentManager:
    """
    Registers agents, resolves canonical names/aliases, and selects the most
    suitable specialist.
    """

    VERSION = "1.1.0"
    SELECTION_TIMEOUT_SECONDS = 5.0

    def __init__(self):
        self.agents: List[BaseAgent] = []

        # Fast canonical name -> agent lookup.
        self.agent_registry: Dict[str, BaseAgent] = {}
        self.aliases: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Registration / lookup
    # ------------------------------------------------------------------

    def register(self, agent: BaseAgent):
        if agent is None:
            return

        agent_name = str(getattr(agent, "name", "")).strip().lower()

        if not agent_name:
            logger.warning(
                "[AgentManager] Cannot register unnamed agent."
            )
            return

        existing = self.agent_registry.get(agent_name)

        if existing is not None:
            logger.warning(
                "[AgentManager] Replacing existing agent: %s",
                agent_name,
            )
            try:
                self.agents.remove(existing)
            except ValueError:
                pass

        self.agents.append(agent)
        self.agent_registry[agent_name] = agent

        for alias in getattr(agent, "aliases", ()) or ():
            alias_name = str(alias or "").strip().lower()
            if not alias_name:
                continue
            if alias_name in self.agent_registry and alias_name != agent_name:
                logger.warning(
                    "[AgentManager] Alias '%s' already resolves to a "
                    "registered agent; keeping the existing target.",
                    alias_name,
                )
                continue
            self.aliases[alias_name] = agent_name

        logger.info(
            "[AgentManager] Registered agent: %s (aliases=%s)",
            agent_name,
            list(getattr(agent, "aliases", ()) or ()),
        )

    def get(self, name: str) -> Optional[BaseAgent]:
        """Retrieve a registered agent by canonical name or alias."""
        if not name:
            return None

        key = str(name).strip().lower()
        if not key:
            return None

        agent = self.agent_registry.get(key)
        if agent is not None:
            return agent

        canonical = self.aliases.get(key)
        if canonical:
            return self.agent_registry.get(canonical)

        return None

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """Compatibility alias for `get`."""
        return self.get(name)

    def canonical_name(self, name: str) -> Optional[str]:
        agent = self.get(name)
        return getattr(agent, "name", None) if agent is not None else None

    def list_agents(self) -> List[str]:
        return list(self.agent_registry.keys())

    def list_aliases(self) -> Dict[str, str]:
        return dict(self.aliases)

    def has_agent(self, name: str) -> bool:
        return self.get(name) is not None

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    async def select_agent(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> Tuple[Optional[BaseAgent], float]:

        best_agent = None
        best_score = 0.0

        for agent in self.agents:
            try:
                score = await asyncio.wait_for(
                    agent.can_handle(query, context),
                    timeout=self.SELECTION_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[AgentManager] %s can_handle timed out; skipped.",
                    getattr(agent, "name", "unknown"),
                )
                score = 0.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "[AgentManager] %s can_handle failed; skipped.",
                    getattr(agent, "name", "unknown"),
                )
                score = 0.0

            try:
                score = max(0.0, min(float(score), 1.0))
            except (TypeError, ValueError):
                score = 0.0

            logger.info(
                "[AgentManager] %s score=%.2f (priority=%d)",
                getattr(agent, "name", "unknown"),
                score,
                getattr(agent, "priority", 0),
            )

            if (
                score > best_score
                or (
                    score == best_score
                    and best_agent is not None
                    and getattr(agent, "priority", 0)
                    > getattr(best_agent, "priority", 0)
                )
            ):
                best_score = score
                best_agent = agent

        return best_agent, best_score

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute_agent(
        self,
        agent_name: str,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute one named specialist agent through the reliable base contract.
        """

        context = context if isinstance(context, dict) else {}

        agent = self.get_agent(agent_name)

        if agent is None:
            raise ValueError(f"Agent not found: {agent_name}")

        logger.info(
            "[AgentManager] Executing agent: %s",
            agent_name,
        )

        if callable(getattr(agent, "run", None)):
            return await agent.run(
                query=query,
                context=context,
            )

        if callable(getattr(agent, "execute", None)):
            result = await agent.execute(
                query=query,
                context=context,
            )
            return self._normalize_response(agent, result)

        if callable(getattr(agent, "run", None)):
            return await agent.run(query, context)

        raise RuntimeError(
            f"Agent '{agent_name}' has no executable interface."
        )

    async def execute_agents(self, plan, context=None):
        """
        Execute multiple agents sequentially.

        Each step is a dict with ``agent`` and ``task``. A step only counts as
        successful when the agent returned non-empty usable output.
        """

        results = []

        if not plan:
            return results

        for step in plan:
            if not isinstance(step, dict):
                results.append(
                    {
                        "agent": None,
                        "success": False,
                        "error": "Invalid agent plan step.",
                    }
                )
                continue

            agent_name = step.get("agent")
            task = step.get("task")

            try:
                output = await self.execute_agent(
                    agent_name,
                    task,
                    context,
                )

                success, text, error = self._result_status(output)

                results.append(
                    {
                        "agent": agent_name,
                        "success": success,
                        "result": output,
                        "output": text,
                        "error": error,
                    }
                )

            except asyncio.CancelledError:
                raise

            except Exception as e:
                logger.exception(
                    "[AgentManager] Agent execution failed: %s",
                    agent_name,
                )

                results.append(
                    {
                        "agent": agent_name,
                        "success": False,
                        "error": str(e),
                    }
                )

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize_response(
        self,
        agent: BaseAgent,
        response: Any,
    ) -> AgentResponse:
        if isinstance(response, AgentResponse):
            if response.success and not response.has_output():
                return AgentResponse(
                    success=False,
                    confidence=0.0,
                    agent=response.agent or getattr(agent, "name", "agent"),
                    data=response.data,
                    error="The agent returned success without usable output.",
                )
            return response

        if isinstance(response, dict):
            text = ""
            for key in ("response", "message", "answer", "content", "output", "result"):
                value = response.get(key)
                if value is not None and str(value).strip():
                    text = str(value).strip()
                    break
            success = bool(response.get("success", bool(text))) and bool(text)
            return AgentResponse(
                success=success,
                confidence=float(response.get("confidence", 0.0) or 0.0),
                agent=str(response.get("agent") or getattr(agent, "name", "agent")),
                data=response.get("data") if isinstance(response.get("data"), dict) else response,
                error=response.get("error") or (None if success else "No usable output."),
            )

        text = str(response or "").strip()
        return AgentResponse(
            success=bool(text),
            confidence=0.5 if text else 0.0,
            agent=getattr(agent, "name", "agent"),
            data={"response": text} if text else {},
            error=None if text else "No usable output.",
        )

    def _result_status(self, output: Any) -> Tuple[bool, str, Optional[str]]:
        if isinstance(output, AgentResponse):
            return (
                bool(output.success) and bool(output.has_output()),
                output.output_text(),
                output.error,
            )

        if isinstance(output, dict):
            text = ""
            for key in ("response", "message", "answer", "content", "output", "result"):
                value = output.get(key)
                if value is not None and str(value).strip():
                    text = str(value).strip()
                    break
            success = bool(output.get("success", bool(text))) and bool(text)
            return success, text, output.get("error")

        text = str(output or "").strip()
        return bool(text), text, None if text else "No usable output."

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "version": self.VERSION,
            "agents": self.list_agents(),
            "aliases": self.list_aliases(),
            "count": len(self.agents),
        }
