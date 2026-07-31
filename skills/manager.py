import logging
from typing import Dict, Any, List, Optional

from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")


class SkillManager:
    """
    Central capability registry for ARIA skills.

    Responsibilities:
    - register skills
    - expose available capabilities to reasoning/planning
    - discover skills dynamically
    - route conversational requests
    - execute planner-selected skills
    - avoid hard-coded command routing
    """

    def __init__(self):
        self.skills: List[BaseSkill] = []
        self._skill_map: Dict[str, BaseSkill] = {}

    # =========================================================
    # REGISTRATION
    # =========================================================

    def register(self, skill: BaseSkill):
        """
        Normalize and register a skill.

        Skill names must be unique because Planner/Executor may
        reference them directly.
        """

        name = str(
            getattr(skill, "name", "")
            or ""
        ).strip().lower()

        if not name:
            raise ValueError(
                "Cannot register a skill without a name."
            )

        skill.name = name

        # Replace an existing skill with the same name rather
        # than silently registering duplicates.
        existing = self._skill_map.get(name)

        if existing is not None:

            self.skills = [
                item
                for item in self.skills
                if item.name != name
            ]

            logger.warning(
                "[SkillManager] Replacing already registered "
                "skill '%s'.",
                name,
            )

        self.skills.append(skill)
        self._skill_map[name] = skill

        logger.info(
            "[SkillManager] Registered skill: '%s'",
            name,
        )

    # =========================================================
    # LOOKUP
    # =========================================================

    def get_skill(
        self,
        skill_name: str,
    ) -> Optional[BaseSkill]:
        """
        Return a registered skill by canonical name.
        """

        normalized = str(
            skill_name or ""
        ).strip().lower()

        return self._skill_map.get(
            normalized
        )

    def has_skill(
        self,
        skill_name: str,
    ) -> bool:

        return (
            self.get_skill(skill_name)
            is not None
        )

    def get_skill_names(self) -> List[str]:
        """
        Return all currently registered skill names.
        """

        return [
            skill.name
            for skill in self.skills
        ]

    # =========================================================
    # CAPABILITY DISCOVERY
    # =========================================================

    def get_capabilities(self) -> List[Dict[str, Any]]:
        """
        Describe everything ARIA can currently do through skills.

        This information can be supplied to:
        - ReasoningEngine
        - Planner
        - ContextBuilder
        - debugging / introspection

        Skills may optionally define:

            description
            capabilities
            input_schema

        Existing skills that do not define them continue working.
        """

        capabilities: List[
            Dict[str, Any]
        ] = []

        for skill in self.skills:

            description = str(
                getattr(
                    skill,
                    "description",
                    "",
                )
                or ""
            ).strip()

            declared_capabilities = getattr(
                skill,
                "capabilities",
                None,
            )

            if not isinstance(
                declared_capabilities,
                list,
            ):
                declared_capabilities = []

            input_schema = getattr(
                skill,
                "input_schema",
                None,
            )

            capabilities.append({
                "name": skill.name,
                "description": description,
                "capabilities": (
                    declared_capabilities
                ),
                "input_schema": input_schema,
            })

        return capabilities

    # =========================================================
    # CAPABILITY MATCHING
    # =========================================================

    async def find_candidates(
        self,
        query: str,
        context: Dict[str, Any],
        minimum_confidence: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Ask every registered skill whether it can handle the
        current request.

        Returns ranked candidates instead of immediately
        executing anything.

        This lets higher cognitive layers reason over available
        capabilities.
        """

        candidates: List[
            Dict[str, Any]
        ] = []

        for skill in self.skills:

            try:

                confidence = (
                    await skill.can_run(
                        query,
                        context,
                    )
                )

                try:
                    confidence = float(
                        confidence
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    confidence = 0.0

                confidence = max(
                    0.0,
                    min(
                        confidence,
                        1.0,
                    ),
                )

                if (
                    confidence
                    >= minimum_confidence
                ):

                    candidates.append({
                        "name": skill.name,
                        "confidence": confidence,
                        "skill": skill,
                    })

            except Exception:

                logger.exception(
                    "[SkillManager] Capability evaluation "
                    "failed for skill '%s'.",
                    skill.name,
                )

        candidates.sort(
            key=lambda item: item[
                "confidence"
            ],
            reverse=True,
        )

        return candidates

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> bool:
        """
        Return True when at least one skill is sufficiently
        confident it can handle the request.
        """

        candidates = (
            await self.find_candidates(
                query=query,
                context=context,
                minimum_confidence=0.30,
            )
        )

        return bool(candidates)

    # =========================================================
    # AUTOMATIC ROUTING
    # =========================================================

    async def route_and_execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> SkillResponse:
        """
        Dynamically select and execute the strongest skill.

        Used primarily for simple single-capability requests.

        Multi-step requests should normally be handled by
        Planner + Executor.
        """

        candidates = (
            await self.find_candidates(
                query=query,
                context=context,
                minimum_confidence=0.30,
            )
        )

        if not candidates:

            logger.warning(
                "[SkillManager] No suitable skill found "
                "for query."
            )

            return SkillResponse(
                success=False,
                confidence=0.0,
                source="skill_manager",
                error=(
                    "No registered skill could confidently "
                    "handle the request."
                ),
            )

        candidate = candidates[0]

        skill = candidate["skill"]
        confidence = candidate[
            "confidence"
        ]

        logger.info(
            "[SkillManager] Routing request to '%s' "
            "(confidence=%.2f).",
            skill.name,
            confidence,
        )

        try:

            result = await skill.execute(
                query,
                context,
            )

            return result

        except Exception as exc:

            logger.exception(
                "[SkillManager] Routed skill '%s' failed.",
                skill.name,
            )

            return SkillResponse(
                success=False,
                confidence=0.0,
                source=skill.name,
                error=str(exc),
            )

    # =========================================================
    # PLANNER-DIRECTED EXECUTION
    # =========================================================

    async def execute_skill(
        self,
        skill_name: str,
        query: str,
        context: Dict[str, Any],
    ) -> SkillResponse:
        """
        Execute a specific capability chosen by Planner.

        Planner does not need command-specific code here.
        It only needs the canonical registered skill name.
        """

        normalized_target = str(
            skill_name or ""
        ).strip().lower()

        skill = self.get_skill(
            normalized_target
        )

        if skill is None:

            available = (
                self.get_skill_names()
            )

            logger.error(
                "[SkillManager] Planner requested unsupported "
                "skill '%s'. Available=%s",
                normalized_target,
                available,
            )

            return SkillResponse(
                success=False,
                confidence=0.0,
                source="skill_manager",
                error=(
                    f"Skill '{normalized_target}' is not "
                    f"registered. Available skills: "
                    f"{available}"
                ),
            )

        logger.info(
            "[SkillManager] Executing planner-selected "
            "skill '%s'.",
            skill.name,
        )

        try:

            return await skill.execute(
                query,
                context,
            )

        except Exception as exc:

            logger.exception(
                "[SkillManager] Planned skill '%s' failed.",
                skill.name,
            )

            return SkillResponse(
                success=False,
                confidence=0.0,
                source=skill.name,
                error=str(exc),
            )
