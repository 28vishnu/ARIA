from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Iterable, Mapping
from typing import Any

from .contracts.engineering_experience import (
    EngineeringExperience,
    EngineeringExperienceContext,
    ExperienceKind,
    ExperienceLearningResult,
    ExperienceMatch,
    ExperienceOutcome,
    ExperienceQuery,
)


class AuthoritativeExperienceEngine:
    """
    Persistent engineering learning boundary.

    This component records engineering outcomes and retrieves prior
    experience without allowing historical experience to override
    current evidence.

    Historical experience is advisory.
    Current execution evidence remains authoritative.
    """

    def __init__(
        self,
        *,
        store: Any | None = None,
        knowledge_engine: Any | None = None,
        max_memory_items: int = 2000,
    ) -> None:
        self.store = store
        self.knowledge_engine = knowledge_engine
        self.max_memory_items = max(100, int(max_memory_items))
        self._memory: dict[str, EngineeringExperience] = {}

    def record(
        self,
        experience: EngineeringExperience,
    ) -> ExperienceLearningResult:
        if not experience.experience_id:
            return ExperienceLearningResult(
                rejected=("Experience requires an experience_id.",)
            )

        if not experience.session_id:
            return ExperienceLearningResult(
                rejected=("Experience requires a session_id.",)
            )

        if not experience.summary.strip():
            return ExperienceLearningResult(
                rejected=("Experience requires a summary.",)
            )

        normalized = self._normalize(experience)

        self._memory[normalized.experience_id] = normalized

        self._trim_memory()

        self._persist(normalized)

        return ExperienceLearningResult(
            recorded=(normalized,),
            recommendations=self._recommend_from_experience(
                normalized
            ),
        )

    def learn_from_session(
        self,
        *,
        session: Any,
        outcome: Any | None = None,
        verification: Any | None = None,
        diagnosis: Any | None = None,
        recovery: Any | None = None,
        acceptance: Any | None = None,
    ) -> ExperienceLearningResult:
        """
        Convert a completed engineering session into reusable experience.

        The method intentionally creates several focused memories rather
        than one enormous opaque memory.
        """
        session_id = self._session_value(session, "session_id")

        if not session_id:
            return ExperienceLearningResult(
                rejected=("Session has no session_id.",)
            )

        experiences: list[EngineeringExperience] = []

        requirement = self._session_value(
            session,
            "requirement",
            default="",
        )

        if not isinstance(requirement, str):
            requirement = self._object_text(requirement)

        outcome_text = self._object_text(outcome)
        verification_text = self._object_text(verification)
        diagnosis_text = self._object_text(diagnosis)
        recovery_text = self._object_text(recovery)
        acceptance_text = self._object_text(acceptance)

        if outcome is not None:
            experiences.append(
                self._build_outcome_experience(
                    session_id=session_id,
                    requirement=requirement,
                    outcome=outcome_text,
                )
            )

        if diagnosis is not None:
            experiences.append(
                self._build_diagnosis_experience(
                    session_id=session_id,
                    requirement=requirement,
                    diagnosis=diagnosis_text,
                )
            )

        if recovery is not None:
            experiences.append(
                self._build_recovery_experience(
                    session_id=session_id,
                    requirement=requirement,
                    recovery=recovery_text,
                )
            )

        if verification is not None:
            experiences.append(
                self._build_verification_experience(
                    session_id=session_id,
                    requirement=requirement,
                    verification=verification_text,
                )
            )

        if acceptance is not None:
            experiences.append(
                self._build_acceptance_experience(
                    session_id=session_id,
                    requirement=requirement,
                    acceptance=acceptance_text,
                )
            )

        if not experiences:
            experiences.append(
                self._build_session_summary_experience(
                    session_id=session_id,
                    requirement=requirement,
                    session=session,
                )
            )

        recorded: list[EngineeringExperience] = []
        rejected: list[str] = []
        recommendations: list[str] = []
        warnings: list[str] = []

        for experience in experiences:
            result = self.record(experience)

            recorded.extend(result.recorded)
            rejected.extend(result.rejected)
            recommendations.extend(result.recommendations)
            warnings.extend(result.warnings)

        return ExperienceLearningResult(
            recorded=tuple(recorded),
            rejected=tuple(rejected),
            recommendations=tuple(
                dict.fromkeys(recommendations)
            ),
            warnings=tuple(dict.fromkeys(warnings)),
            metadata={
                "session_id": session_id,
                "experience_count": len(recorded),
            },
        )

    def recall(
        self,
        query: ExperienceQuery,
    ) -> EngineeringExperienceContext:
        experiences = list(self._memory.values())

        if self.store is not None:
            experiences.extend(self._load_persisted())

        unique: dict[str, EngineeringExperience] = {}

        for experience in experiences:
            unique[experience.experience_id] = experience

        matches: list[ExperienceMatch] = []

        for experience in unique.values():
            if experience.confidence < query.min_confidence:
                continue

            if query.kind is not None and experience.kind != query.kind:
                continue

            if query.outcome is not None and experience.outcome != query.outcome:
                continue

            if query.failure_signature:
                if not self._contains_match(
                    experience.failure_signatures,
                    query.failure_signature,
                ):
                    continue

            if query.root_cause:
                if not self._contains_match(
                    experience.root_causes,
                    query.root_cause,
                ):
                    continue

            score, fields = self._score(
                experience,
                query,
            )

            if score <= 0.0:
                continue

            matches.append(
                ExperienceMatch(
                    experience=experience,
                    score=score,
                    matched_fields=tuple(fields),
                )
            )

        matches.sort(
            key=lambda item: (
                item.score,
                item.experience.confidence,
            ),
            reverse=True,
        )

        matches = matches[: max(1, query.limit)]

        recommendations = self._recommend_from_matches(matches)

        return EngineeringExperienceContext(
            query=query,
            matches=tuple(matches),
            recommendations=tuple(recommendations),
        )

    def recommend(
        self,
        *,
        requirement: str,
        failure_text: str = "",
        root_cause: str = "",
        tags: Iterable[str] = (),
        limit: int = 5,
    ) -> EngineeringExperienceContext:
        query = ExperienceQuery(
            query=requirement,
            tags=tuple(tags),
            failure_signature=(
                self._normalize_signature(failure_text)
                if failure_text
                else None
            ),
            root_cause=root_cause or None,
            limit=limit,
        )

        return self.recall(query)

    def forget_session(
        self,
        session_id: str,
    ) -> int:
        """
        Remove only experiences belonging to a specific engineering session.

        This is useful for explicit cleanup and test isolation.
        """
        ids = [
            experience_id
            for experience_id, experience in self._memory.items()
            if experience.session_id == session_id
        ]

        for experience_id in ids:
            self._memory.pop(experience_id, None)

        return len(ids)

    def _build_outcome_experience(
        self,
        *,
        session_id: str,
        requirement: str,
        outcome: str,
    ) -> EngineeringExperience:
        positive = self._looks_positive(outcome)

        return self._make_experience(
            session_id=session_id,
            kind=(
                ExperienceKind.SUCCESS
                if positive
                else ExperienceKind.FAILURE
            ),
            outcome=(
                ExperienceOutcome.POSITIVE
                if positive
                else ExperienceOutcome.NEGATIVE
            ),
            summary=(
                "Engineering session completed successfully."
                if positive
                else "Engineering session did not complete successfully."
            ),
            context={
                "requirement": requirement,
                "outcome": outcome[:4000],
            },
            lessons=self._extract_lessons(outcome),
            successful_actions=(
                self._extract_success_actions(outcome)
                if positive
                else ()
            ),
            failed_actions=(
                self._extract_failure_actions(outcome)
                if not positive
                else ()
            ),
            confidence=0.75,
        )

    def _build_diagnosis_experience(
        self,
        *,
        session_id: str,
        requirement: str,
        diagnosis: str,
    ) -> EngineeringExperience:
        root_causes = self._extract_terms(
            diagnosis,
            (
                "syntax",
                "import",
                "name",
                "type",
                "assertion",
                "file",
                "path",
                "permission",
                "timeout",
                "dependency",
                "configuration",
                "environment",
                "interface",
                "logic",
                "state",
                "integration",
                "resource",
            ),
        )

        return self._make_experience(
            session_id=session_id,
            kind=ExperienceKind.DIAGNOSIS,
            outcome=ExperienceOutcome.POSITIVE,
            summary="Root-cause diagnosis produced engineering evidence.",
            context={
                "requirement": requirement,
                "diagnosis": diagnosis[:5000],
            },
            root_causes=tuple(root_causes),
            failure_signatures=(
                self._normalize_signature(diagnosis),
            ),
            lessons=self._extract_lessons(diagnosis),
            confidence=0.70,
        )

    def _build_recovery_experience(
        self,
        *,
        session_id: str,
        requirement: str,
        recovery: str,
    ) -> EngineeringExperience:
        positive = self._looks_positive(recovery)

        return self._make_experience(
            session_id=session_id,
            kind=ExperienceKind.RECOVERY,
            outcome=(
                ExperienceOutcome.POSITIVE
                if positive
                else ExperienceOutcome.MIXED
            ),
            summary=(
                "Recovery workflow produced a successful repair/retest path."
                if positive
                else "Recovery workflow contained incomplete or unsuccessful work."
            ),
            context={
                "requirement": requirement,
                "recovery": recovery[:5000],
            },
            repair_actions=self._extract_actions(recovery),
            lessons=self._extract_lessons(recovery),
            confidence=0.72,
        )

    def _build_verification_experience(
        self,
        *,
        session_id: str,
        requirement: str,
        verification: str,
    ) -> EngineeringExperience:
        positive = self._looks_positive(verification)

        return self._make_experience(
            session_id=session_id,
            kind=ExperienceKind.VERIFICATION,
            outcome=(
                ExperienceOutcome.POSITIVE
                if positive
                else ExperienceOutcome.NEGATIVE
            ),
            summary=(
                "Verification produced positive evidence."
                if positive
                else "Verification exposed a failure or evidence gap."
            ),
            context={
                "requirement": requirement,
                "verification": verification[:5000],
            },
            lessons=self._extract_lessons(verification),
            confidence=0.80,
        )

    def _build_acceptance_experience(
        self,
        *,
        session_id: str,
        requirement: str,
        acceptance: str,
    ) -> EngineeringExperience:
        positive = self._looks_accepted(acceptance)

        return self._make_experience(
            session_id=session_id,
            kind=ExperienceKind.ACCEPTANCE,
            outcome=(
                ExperienceOutcome.POSITIVE
                if positive
                else ExperienceOutcome.NEGATIVE
            ),
            summary=(
                "Engineering acceptance judgment accepted the requirement."
                if positive
                else "Engineering acceptance judgment rejected or could not prove the requirement."
            ),
            context={
                "requirement": requirement,
                "acceptance": acceptance[:5000],
            },
            lessons=self._extract_lessons(acceptance),
            confidence=0.90,
        )

    def _build_session_summary_experience(
        self,
        *,
        session_id: str,
        requirement: str,
        session: Any,
    ) -> EngineeringExperience:
        summary = self._object_text(session)

        return self._make_experience(
            session_id=session_id,
            kind=ExperienceKind.REPLAN,
            outcome=ExperienceOutcome.UNKNOWN,
            summary="Engineering session state was recorded for future context.",
            context={
                "requirement": requirement,
                "session_summary": summary[:5000],
            },
            confidence=0.45,
        )

    def _make_experience(
        self,
        *,
        session_id: str,
        kind: ExperienceKind,
        outcome: ExperienceOutcome,
        summary: str,
        context: Mapping[str, Any] | None = None,
        evidence_ids: Iterable[str] = (),
        changed_paths: Iterable[str] = (),
        failure_signatures: Iterable[str] = (),
        root_causes: Iterable[str] = (),
        repair_actions: Iterable[str] = (),
        successful_actions: Iterable[str] = (),
        failed_actions: Iterable[str] = (),
        lessons: Iterable[str] = (),
        tags: Iterable[str] = (),
        confidence: float = 0.0,
    ) -> EngineeringExperience:
        raw_identity = (
            f"{session_id}|{kind.value}|{summary}|"
            f"{time.time_ns()}"
        )

        experience_id = (
            "exp-"
            + hashlib.sha256(
                raw_identity.encode("utf-8")
            ).hexdigest()[:20]
        )

        return EngineeringExperience(
            experience_id=experience_id,
            session_id=session_id,
            kind=kind,
            outcome=outcome,
            summary=summary,
            context=dict(context or {}),
            evidence_ids=tuple(evidence_ids),
            changed_paths=tuple(changed_paths),
            failure_signatures=tuple(
                failure_signatures
            ),
            root_causes=tuple(root_causes),
            repair_actions=tuple(repair_actions),
            successful_actions=tuple(successful_actions),
            failed_actions=tuple(failed_actions),
            lessons=tuple(lessons),
            tags=tuple(tags),
            confidence=max(0.0, min(1.0, confidence)),
        )

    def _normalize(
        self,
        experience: EngineeringExperience,
    ) -> EngineeringExperience:
        return EngineeringExperience(
            experience_id=experience.experience_id.strip(),
            session_id=experience.session_id.strip(),
            kind=experience.kind,
            outcome=experience.outcome,
            summary=experience.summary.strip(),
            context=dict(experience.context),
            evidence_ids=tuple(
                dict.fromkeys(
                    str(value)
                    for value in experience.evidence_ids
                )
            ),
            changed_paths=tuple(
                dict.fromkeys(
                    str(value)
                    for value in experience.changed_paths
                )
            ),
            failure_signatures=tuple(
                dict.fromkeys(
                    self._normalize_signature(value)
                    for value in experience.failure_signatures
                    if str(value).strip()
                )
            ),
            root_causes=tuple(
                dict.fromkeys(
                    str(value).strip().lower()
                    for value in experience.root_causes
                    if str(value).strip()
                )
            ),
            repair_actions=tuple(
                dict.fromkeys(
                    str(value).strip()
                    for value in experience.repair_actions
                    if str(value).strip()
                )
            ),
            successful_actions=tuple(
                dict.fromkeys(
                    str(value).strip()
                    for value in experience.successful_actions
                    if str(value).strip()
                )
            ),
            failed_actions=tuple(
                dict.fromkeys(
                    str(value).strip()
                    for value in experience.failed_actions
                    if str(value).strip()
                )
            ),
            lessons=tuple(
                dict.fromkeys(
                    str(value).strip()
                    for value in experience.lessons
                    if str(value).strip()
                )
            ),
            tags=tuple(
                dict.fromkeys(
                    str(value).strip().lower()
                    for value in experience.tags
                    if str(value).strip()
                )
            ),
            confidence=max(
                0.0,
                min(1.0, float(experience.confidence)),
            ),
            reusable=experience.reusable,
            metadata=dict(experience.metadata),
        )

    def _persist(
        self,
        experience: EngineeringExperience,
    ) -> None:
        if self.store is None:
            return

        payload = experience.to_dict()

        for method_name in (
            "save_experience",
            "record_experience",
            "save",
            "store",
        ):
            method = getattr(self.store, method_name, None)

            if not callable(method):
                continue

            try:
                method(
                    experience.experience_id,
                    payload,
                )
                return
            except TypeError:
                try:
                    method(payload)
                    return
                except Exception:
                    continue
            except Exception:
                continue

    def _load_persisted(self) -> list[EngineeringExperience]:
        if self.store is None:
            return []

        for method_name in (
            "list_experiences",
            "load_experiences",
            "get_experiences",
        ):
            method = getattr(self.store, method_name, None)

            if not callable(method):
                continue

            try:
                result = method()
            except Exception:
                continue

            if not isinstance(result, Iterable):
                continue

            loaded: list[EngineeringExperience] = []

            for item in result:
                if isinstance(item, EngineeringExperience):
                    loaded.append(item)
                elif isinstance(item, Mapping):
                    try:
                        loaded.append(
                            EngineeringExperience.from_dict(item)
                        )
                    except Exception:
                        continue

            return loaded

        return []

    def _trim_memory(self) -> None:
        if len(self._memory) <= self.max_memory_items:
            return

        ordered = sorted(
            self._memory.values(),
            key=lambda item: (
                item.confidence,
                item.experience_id,
            ),
        )

        remove_count = len(self._memory) - self.max_memory_items

        for experience in ordered[:remove_count]:
            self._memory.pop(
                experience.experience_id,
                None,
            )

    def _score(
        self,
        experience: EngineeringExperience,
        query: ExperienceQuery,
    ) -> tuple[float, list[str]]:
        score = 0.0
        fields: list[str] = []

        query_text = query.query.lower().strip()

        if query_text:
            tokens = self._tokens(query_text)

            haystack = " ".join(
                (
                    experience.summary,
                    *experience.lessons,
                    *experience.successful_actions,
                    *experience.failed_actions,
                    *experience.repair_actions,
                    *experience.tags,
                    *experience.root_causes,
                )
            ).lower()

            matched = [
                token
                for token in tokens
                if token in haystack
            ]

            if matched:
                score += min(
                    0.45,
                    0.08 * len(matched),
                )
                fields.append("text")

        if query.tags:
            overlap = set(
                tag.lower()
                for tag in query.tags
            ) & set(experience.tags)

            if overlap:
                score += min(
                    0.25,
                    0.10 * len(overlap),
                )
                fields.append("tags")

        if query.failure_signature:
            if self._contains_match(
                experience.failure_signatures,
                query.failure_signature,
            ):
                score += 0.40
                fields.append("failure_signature")

        if query.root_cause:
            if self._contains_match(
                experience.root_causes,
                query.root_cause,
            ):
                score += 0.40
                fields.append("root_cause")

        score *= 0.5 + (
            0.5 * experience.confidence
        )

        return min(1.0, score), fields

    @staticmethod
    def _contains_match(
        values: Iterable[str],
        target: str,
    ) -> bool:
        target = str(target).strip().lower()

        if not target:
            return False

        return any(
            target in str(value).lower()
            or str(value).lower() in target
            for value in values
        )

    def _recommend_from_matches(
        self,
        matches: Iterable[ExperienceMatch],
    ) -> list[str]:
        recommendations: list[str] = []

        for match in matches:
            experience = match.experience

            for lesson in experience.lessons:
                if lesson not in recommendations:
                    recommendations.append(
                        lesson
                    )

            for action in experience.successful_actions:
                recommendation = (
                    f"Previously successful action: {action}"
                )

                if recommendation not in recommendations:
                    recommendations.append(
                        recommendation
                    )

            for action in experience.repair_actions:
                recommendation = (
                    f"Previously used repair action: {action}"
                )

                if recommendation not in recommendations:
                    recommendations.append(
                        recommendation
                    )

        return recommendations[:10]

    @staticmethod
    def _recommend_from_experience(
        experience: EngineeringExperience,
    ) -> list[str]:
        recommendations = list(
            experience.lessons
        )

        recommendations.extend(
            f"Previously successful action: {action}"
            for action in experience.successful_actions
        )

        return list(
            dict.fromkeys(recommendations)
        )[:10]

    @staticmethod
    def _session_value(
        session: Any,
        name: str,
        default: Any = None,
    ) -> Any:
        if isinstance(session, Mapping):
            return session.get(name, default)

        value = getattr(session, name, default)

        if callable(value):
            try:
                return value()
            except TypeError:
                return default
            except Exception:
                return default

        return value

    @staticmethod
    def _object_text(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        for name in (
            "summary",
            "rationale",
            "message",
            "diagnostics",
            "error",
        ):
            candidate = getattr(value, name, None)

            if candidate:
                return str(candidate)

        if isinstance(value, Mapping):
            return str(dict(value))

        if hasattr(value, "to_dict"):
            try:
                return str(value.to_dict())
            except Exception:
                pass

        return str(value)

    @staticmethod
    def _normalize_signature(
        text: str,
    ) -> str:
        normalized = re.sub(
            r"\s+",
            " ",
            str(text).strip().lower(),
        )

        normalized = re.sub(
            r"/app/[^\s:'\"]+",
            "<path>",
            normalized,
        )

        normalized = re.sub(
            r"\b\d+\b",
            "<n>",
            normalized,
        )

        return normalized[:1000]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token
            for token in re.findall(
                r"[a-zA-Z0-9_]{3,}",
                text.lower(),
            )
            if token
            not in {
                "the",
                "and",
                "that",
                "with",
                "from",
                "this",
                "into",
                "have",
                "should",
                "must",
            }
        }

    @staticmethod
    def _looks_positive(text: str) -> bool:
        lowered = text.lower()

        positive = (
            "accepted",
            "success",
            "successful",
            "passed",
            "satisfied",
            "recovered",
            "verified",
            "completed",
        )

        negative = (
            "failed",
            "failure",
            "blocked",
            "rejected",
            "error",
            "unsatisfied",
        )

        positive_score = sum(
            lowered.count(item)
            for item in positive
        )

        negative_score = sum(
            lowered.count(item)
            for item in negative
        )

        return positive_score > negative_score

    @staticmethod
    def _looks_accepted(text: str) -> bool:
        lowered = text.lower()

        return (
            "accepted" in lowered
            or "acceptance_status='accepted'" in lowered
            or '"status": "accepted"' in lowered
            or "'status': 'accepted'" in lowered
        )

    @staticmethod
    def _extract_lessons(
        text: str,
    ) -> tuple[str, ...]:
        patterns = (
            r"lesson[s]?:\s*(.+)",
            r"learned:\s*(.+)",
            r"recommendation[s]?:\s*(.+)",
            r"next action[s]?:\s*(.+)",
        )

        results: list[str] = []

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                value = match.group(1).strip()

                if value:
                    results.append(value[:1000])

        return tuple(
            dict.fromkeys(results)
        )[:10]

    @staticmethod
    def _extract_actions(
        text: str,
    ) -> tuple[str, ...]:
        patterns = (
            r"repair(?:ed)?\s*[:\-]\s*(.+)",
            r"action[s]?:\s*(.+)",
            r"fixed\s*[:\-]\s*(.+)",
        )

        results: list[str] = []

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                value = match.group(1).strip()

                if value:
                    results.append(value[:1000])

        return tuple(
            dict.fromkeys(results)
        )[:10]

    @staticmethod
    def _extract_success_actions(
        text: str,
    ) -> tuple[str, ...]:
        if not text:
            return ()

        return tuple(
            line.strip()
            for line in text.splitlines()
            if any(
                marker in line.lower()
                for marker in (
                    "passed",
                    "success",
                    "verified",
                    "completed",
                )
            )
        )[:10]

    @staticmethod
    def _extract_failure_actions(
        text: str,
    ) -> tuple[str, ...]:
        if not text:
            return ()

        return tuple(
            line.strip()
            for line in text.splitlines()
            if any(
                marker in line.lower()
                for marker in (
                    "failed",
                    "failure",
                    "error",
                    "blocked",
                )
            )
        )[:10]

    @staticmethod
    def _extract_terms(
        text: str,
        candidates: Iterable[str],
    ) -> tuple[str, ...]:
        lowered = text.lower()

        return tuple(
            candidate
            for candidate in candidates
            if candidate in lowered
        )