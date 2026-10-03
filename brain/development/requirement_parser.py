"""
ARIA Requirement Parser.

Deterministically converts a Master's natural-language development
request into a structured Requirement object.

This module is intentionally side-effect free.

It does NOT:
    - generate code
    - modify files
    - execute commands
    - deploy
    - push to GitHub
    - call an LLM

Its purpose is to create a reliable machine-readable representation
of the Master's request before the development pipeline begins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ======================================================================
# Requirement model
# ======================================================================


@dataclass(frozen=True)
class Requirement:
    """
    Structured representation of a development requirement.
    """

    raw_text: str

    summary: str

    goals: tuple[str, ...] = ()

    constraints: tuple[str, ...] = ()

    acceptance_criteria: tuple[str, ...] = ()

    requested_files: tuple[str, ...] = ()

    risk_flags: tuple[str, ...] = ()

    requires_approval: bool = False

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        """
        Return a JSON-serializable representation.
        """

        return {
            "raw_text": self.raw_text,
            "summary": self.summary,
            "goals": list(self.goals),
            "constraints": list(self.constraints),
            "acceptance_criteria": list(
                self.acceptance_criteria
            ),
            "requested_files": list(
                self.requested_files
            ),
            "risk_flags": list(
                self.risk_flags
            ),
            "requires_approval": (
                self.requires_approval
            ),
            "metadata": dict(
                self.metadata
            ),
        }


# ======================================================================
# Parser
# ======================================================================


class RequirementParser:
    """
    Deterministically converts a Master's development request into
    structured requirements.

    The parser deliberately avoids guessing implementation details.

    Security principle:
        Explicit negative constraints such as
        "do not deploy" must not be interpreted as a request
        to deploy.

    Example:

        "Create aria_test.txt. Do not modify existing files.
         Do not deploy and do not push to GitHub."

    becomes approximately:

        goals:
            create aria_test.txt

        constraints:
            do not modify existing files
            do not deploy
            do not push to GitHub

        risk_flags:
            []

        requires_approval:
            False
    """

    # ------------------------------------------------------------------
    # Risk terms
    # ------------------------------------------------------------------

    _RISK_TERMS = (
        "secret",
        "password",
        "token",
        "credential",
        "api key",
        "private key",
        "access key",
        "production",
        "deploy",
        "deployment",
        "delete",
        "remove",
        "destroy",
        "database",
        "security",
        "authentication",
        "authorization",
        "github actions",
        "github workflow",
        "workflow",
        ".env",
        "dockerfile",
        "permission",
        "permissions",
        "sudo",
        "shell command",
        "execute command",
    )

    # ------------------------------------------------------------------
    # Terms that normally require Master approval.
    #
    # These are checked only when the requirement is actually asking
    # ARIA to perform the sensitive action.
    # ------------------------------------------------------------------

    _APPROVAL_TERMS = (
        "production",
        "deploy",
        "deployment",
        "delete",
        "remove",
        "destroy",
        "secret",
        "credential",
        "private key",
        "authentication",
        "authorization",
        "github workflow",
        "github actions",
        "workflow",
        "dockerfile",
        "sudo",
        "permission",
        "permissions",
    )

    # ------------------------------------------------------------------
    # Explicit negative phrases.
    #
    # These phrases suppress the corresponding action from the
    # approval/risk interpretation when the action is explicitly
    # forbidden by the Master.
    # ------------------------------------------------------------------

    _NEGATIVE_PREFIXES = (
        "do not",
        "don't",
        "dont",
        "never",
        "must not",
        "should not",
        "shouldn't",
        "without",
        "no",
        "not",
        "avoid",
        "forbid",
        "forbidden",
        "prohibit",
        "prohibited",
    )

    # ------------------------------------------------------------------
    # File extensions recognized as requested files.
    # ------------------------------------------------------------------

    _FILE_EXTENSIONS = (
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".java",
        ".kt",
        ".kts",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".dart",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".sql",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".xml",
        ".txt",
        ".md",
        ".markdown",
        ".rst",
        ".csv",
        ".tsv",
        ".log",
        ".env",
        ".example",
        ".lock",
    )

    # ------------------------------------------------------------------
    # Goal phrases
    # ------------------------------------------------------------------

    _GOAL_PREFIXES = (
        "create ",
        "add ",
        "build ",
        "implement ",
        "write ",
        "generate ",
        "make ",
        "develop ",
        "update ",
        "improve ",
        "fix ",
        "repair ",
        "refactor ",
        "replace ",
        "introduce ",
        "support ",
        "enable ",
        "allow ",
        "change ",
        "modify ",
    )

    # ------------------------------------------------------------------
    # Constraint phrases
    # ------------------------------------------------------------------

    _CONSTRAINT_PHRASES = (
        "do not ",
        "don't ",
        "dont ",
        "never ",
        "must not ",
        "should not ",
        "shouldn't ",
        "without ",
        "only ",
        "just ",
        "exactly ",
        "must remain ",
        "leave unchanged",
        "unchanged",
        "no existing",
        "existing files",
        "existing file",
        "create-only",
        "create only",
        "no modification",
        "no modifications",
        "do not modify",
        "don't modify",
        "do not change",
        "don't change",
        "do not delete",
        "don't delete",
        "do not deploy",
        "don't deploy",
        "do not push",
        "don't push",
    )

    # ------------------------------------------------------------------
    # Acceptance criteria phrases
    # ------------------------------------------------------------------

    _ACCEPTANCE_PHRASES = (
        "test",
        "tests",
        "verify",
        "verification",
        "validate",
        "validation",
        "pass",
        "passes",
        "passing",
        "working",
        "works",
        "expected",
        "acceptance",
        "successful",
        "successfully",
        "exactly",
        "contains exactly",
        "must contain",
        "should contain",
        "output should",
        "result should",
    )

    # ------------------------------------------------------------------
    # Public parser
    # ------------------------------------------------------------------

    def parse(
        self,
        text: str,
    ) -> Requirement:
        """
        Parse a raw development requirement.

        Raises:
            TypeError:
                If the input is not a string.

            ValueError:
                If the requirement is empty.
        """

        if not isinstance(
            text,
            str,
        ):
            raise TypeError(
                "Requirement must be a string."
            )

        raw = text.strip()

        if not raw:
            raise ValueError(
                "Requirement cannot be empty."
            )

        lines = self._normalise_lines(
            raw
        )

        lower_raw = raw.lower()

        # --------------------------------------------------------------
        # Extract structured components.
        # --------------------------------------------------------------

        goals = self._extract_goals(
            lines
        )

        constraints = (
            self._extract_constraints(
                lines
            )
        )

        acceptance_criteria = (
            self._extract_acceptance_criteria(
                lines
            )
        )

        requested_files = (
            self._extract_requested_files(
                raw
            )
        )

        # --------------------------------------------------------------
        # Add deterministic semantic constraints.
        # --------------------------------------------------------------

        constraints = (
            self._add_semantic_constraints(
                lower_raw=lower_raw,
                constraints=constraints,
            )
        )

        # --------------------------------------------------------------
        # Risk analysis.
        # --------------------------------------------------------------

        risk_flags = (
            self._detect_risk_flags(
                lower_raw
            )
        )

        # --------------------------------------------------------------
        # Approval analysis.
        #
        # Crucially, approval is based on an ACTIVE requested action,
        # not merely the presence of a sensitive word.
        # --------------------------------------------------------------

        requires_approval = (
            self._requires_approval(
                lower_raw=lower_raw,
                constraints=constraints,
            )
        )

        # --------------------------------------------------------------
        # Summary.
        # --------------------------------------------------------------

        summary = self._build_summary(
            lines=lines,
            raw=raw,
        )

        # --------------------------------------------------------------
        # Metadata.
        # --------------------------------------------------------------

        metadata = (
            self._build_metadata(
                raw=raw,
                lower_raw=lower_raw,
                requested_files=requested_files,
                risk_flags=risk_flags,
                requires_approval=(
                    requires_approval
                ),
                constraints=constraints,
            )
        )

        return Requirement(
            raw_text=raw,
            summary=summary,
            goals=tuple(
                self._deduplicate(
                    goals
                )
            ),
            constraints=tuple(
                self._deduplicate(
                    constraints
                )
            ),
            acceptance_criteria=tuple(
                self._deduplicate(
                    acceptance_criteria
                )
            ),
            requested_files=tuple(
                self._deduplicate(
                    requested_files
                )
            ),
            risk_flags=tuple(
                sorted(
                    set(
                        risk_flags
                    )
                )
            ),
            requires_approval=(
                requires_approval
            ),
            metadata=metadata,
        )

    # ==================================================================
    # Line normalization
    # ==================================================================

    @staticmethod
    def _normalise_lines(
        raw: str,
    ) -> list[str]:
        """
        Normalize bullet/list formatting without altering the actual
        raw requirement.
        """

        result: list[str] = []

        for line in raw.splitlines():

            cleaned = line.strip()

            if not cleaned:
                continue

            # Remove common list markers.
            cleaned = re.sub(
                r"^\s*(?:[-*•]|\d+[.)])\s*",
                "",
                cleaned,
            )

            cleaned = cleaned.strip()

            if cleaned:
                result.append(
                    cleaned
                )

        if not result:
            result.append(
                raw.strip()
            )

        return result

    # ==================================================================
    # Goal extraction
    # ==================================================================

    def _extract_goals(
        self,
        lines: list[str],
    ) -> list[str]:
        """
        Extract explicit goals.

        A line is considered a goal when it contains an explicit
        action phrase or clearly describes an implementation action.
        """

        goals: list[str] = []

        for line in lines:

            lower = line.lower().strip()

            # Negative instructions are constraints, not goals.
            if self._is_negative_instruction(
                lower
            ):
                continue

            if any(
                lower.startswith(prefix)
                for prefix in self._GOAL_PREFIXES
            ):
                goals.append(
                    line
                )
                continue

            # Common requirement forms.
            if any(
                phrase in lower
                for phrase in (
                    "need a new ",
                    "need to create",
                    "need to build",
                    "i want a new ",
                    "add a new ",
                    "new file ",
                    "new module ",
                    "new feature ",
                    "implement a ",
                    "implement an ",
                )
            ):
                goals.append(
                    line
                )

        return goals

    # ==================================================================
    # Constraint extraction
    # ==================================================================

    def _extract_constraints(
        self,
        lines: list[str],
    ) -> list[str]:
        """
        Extract explicit constraints.
        """

        constraints: list[str] = []

        for line in lines:

            lower = line.lower().strip()

            if any(
                lower.startswith(prefix)
                for prefix in self._CONSTRAINT_PHRASES
            ):
                constraints.append(
                    line
                )
                continue

            if any(
                phrase in lower
                for phrase in (
                    "existing files",
                    "existing file",
                    "same file",
                    "same files",
                    "only create",
                    "create-only",
                    "exact content",
                    "exactly the content",
                    "leave all other",
                    "leave everything else",
                    "do not touch",
                    "don't touch",
                )
            ):
                constraints.append(
                    line
                )

        return constraints

    # ==================================================================
    # Acceptance criteria extraction
    # ==================================================================

    def _extract_acceptance_criteria(
        self,
        lines: list[str],
    ) -> list[str]:
        """
        Extract statements that describe expected results,
        verification, testing, or exact output.
        """

        criteria: list[str] = []

        for line in lines:

            lower = line.lower().strip()

            # Pure constraints should remain constraints.
            if (
                self._is_negative_instruction(
                    lower
                )
                and not any(
                    phrase in lower
                    for phrase in (
                        "test",
                        "verify",
                        "validate",
                        "pass",
                        "working",
                        "successful",
                        "exactly",
                    )
                )
            ):
                continue

            if any(
                phrase in lower
                for phrase in self._ACCEPTANCE_PHRASES
            ):
                criteria.append(
                    line
                )

        return criteria

    # ==================================================================
    # Requested file extraction
    # ==================================================================

    def _extract_requested_files(
        self,
        raw: str,
    ) -> list[str]:
        """
        Extract repository-relative file/path references.

        Supports common source, configuration, documentation,
        data, and text files.
        """

        candidates: list[str] = []

        # --------------------------------------------------------------
        # Backtick-enclosed paths are highly reliable.
        # --------------------------------------------------------------

        for match in re.findall(
            r"`([^`]+)`",
            raw,
        ):

            value = match.strip()

            if self._looks_like_file(
                value
            ):
                candidates.append(
                    value
                )

        # --------------------------------------------------------------
        # Quoted paths.
        # --------------------------------------------------------------

        for match in re.findall(
            r"""["']([^"']+)["']""",
            raw,
        ):

            value = match.strip()

            if self._looks_like_file(
                value
            ):
                candidates.append(
                    value
                )

        # --------------------------------------------------------------
        # Whitespace-delimited candidates.
        # --------------------------------------------------------------

        for token in re.split(
            r"\s+",
            raw,
        ):

            cleaned = token.strip(
                " \t\r\n.,:;()[]{}<>"
            )

            if self._looks_like_file(
                cleaned
            ):
                candidates.append(
                    cleaned
                )

        # --------------------------------------------------------------
        # Explicit filename phrases.
        # --------------------------------------------------------------

        filename_patterns = (
            r"\bfile\s+(?:called|named)\s+([^\s,.;:]+)",
            r"\bfilename\s+([^\s,.;:]+)",
            r"\bfile\s+([A-Za-z0-9_.\-/\\]+)",
            r"\bmodule\s+([A-Za-z0-9_.\-/\\]+)",
            r"\bpath\s+([A-Za-z0-9_.\-/\\]+)",
        )

        for pattern in filename_patterns:

            for match in re.findall(
                pattern,
                raw,
                flags=re.IGNORECASE,
            ):

                value = str(
                    match
                ).strip(
                    " \t\r\n.,:;()[]{}<>"
                )

                if self._looks_like_file(
                    value
                ):
                    candidates.append(
                        value
                    )

        return candidates

    # ==================================================================
    # Semantic constraints
    # ==================================================================

    def _add_semantic_constraints(
        self,
        *,
        lower_raw: str,
        constraints: list[str],
    ) -> list[str]:
        """
        Convert important natural-language safety instructions into
        deterministic machine-readable constraints.

        These are descriptive constraints, not implementation actions.
        """

        result = list(
            constraints
        )

        semantic_rules = (
            (
                (
                    "do not modify existing",
                    "don't modify existing",
                    "do not change existing",
                    "don't change existing",
                    "do not touch existing",
                    "don't touch existing",
                    "no modification of existing",
                    "no modifications to existing",
                    "leave existing files unchanged",
                ),
                "CREATE_ONLY_EXISTING_FILES_PROTECTED",
            ),
            (
                (
                    "do not deploy",
                    "don't deploy",
                    "never deploy",
                    "must not deploy",
                    "deployment is not allowed",
                    "no deployment",
                ),
                "NO_DEPLOYMENT",
            ),
            (
                (
                    "do not push",
                    "don't push",
                    "never push",
                    "must not push",
                    "no github push",
                    "do not push to github",
                    "don't push to github",
                ),
                "NO_GITHUB_PUSH",
            ),
            (
                (
                    "do not delete",
                    "don't delete",
                    "never delete",
                    "must not delete",
                    "no deletion",
                ),
                "NO_DELETE",
            ),
            (
                (
                    "do not change",
                    "don't change",
                    "leave unchanged",
                    "must remain unchanged",
                ),
                "NO_UNREQUESTED_MODIFICATIONS",
            ),
        )

        for phrases, semantic_constraint in (
            semantic_rules
        ):

            if any(
                phrase in lower_raw
                for phrase in phrases
            ):
                result.append(
                    semantic_constraint
                )

        return result

    # ==================================================================
    # Risk detection
    # ==================================================================

    def _detect_risk_flags(
        self,
        lower_raw: str,
    ) -> list[str]:
        """
        Detect sensitive terminology.

        Important:
            A risk flag describes that a sensitive concept appears
            in the request. It does not by itself mean the requested
            action requires approval.

        Example:

            "Do not deploy"

        may produce the risk flag "deploy", while approval remains
        false because deployment is explicitly prohibited.
        """

        flags: list[str] = []

        for term in self._RISK_TERMS:

            if self._term_present(
                lower_raw,
                term,
            ):
                flags.append(
                    term
                )

        return flags

    # ==================================================================
    # Approval detection
    # ==================================================================

    def _requires_approval(
        self,
        *,
        lower_raw: str,
        constraints: list[str],
    ) -> bool:
        """
        Determine whether the requirement actively requests a
        sensitive action.

        Negative instructions suppress approval.

        Examples:

            "deploy this version"
                -> True

            "do not deploy"
                -> False

            "create a file and do not deploy"
                -> False

            "delete the old file"
                -> True
        """

        # --------------------------------------------------------------
        # Explicit global prohibition.
        # --------------------------------------------------------------

        if self._contains_global_no_action(
            lower_raw
        ):
            # A request that is entirely framed as "do not X"
            # does not request X.
            #
            # We still inspect for another active sensitive action
            # below rather than blindly returning False.
            pass

        # --------------------------------------------------------------
        # Check each approval-sensitive term.
        # --------------------------------------------------------------

        for term in self._APPROVAL_TERMS:

            if not self._term_present(
                lower_raw,
                term,
            ):
                continue

            if self._term_is_explicitly_negated(
                lower_raw,
                term,
            ):
                continue

            # "without deployment" is a prohibition.
            if self._is_negated_without_context(
                lower_raw,
                term,
            ):
                continue

            return True

        return False

    # ==================================================================
    # Negation helpers
    # ==================================================================

    def _is_negative_instruction(
        self,
        lower_line: str,
    ) -> bool:
        """
        Detect whether a line is primarily a prohibition.
        """

        value = lower_line.strip()

        return (
            value.startswith(
                self._NEGATIVE_PREFIXES
            )
            or any(
                phrase in value
                for phrase in (
                    "do not ",
                    "don't ",
                    "must not ",
                    "should not ",
                    "never ",
                )
            )
        )

    def _term_is_explicitly_negated(
        self,
        text: str,
        term: str,
    ) -> bool:
        """
        Determine whether a sensitive term is preceded by a
        nearby negative instruction.

        This intentionally uses a bounded local window rather than
        attempting full natural-language semantic parsing.
        """

        escaped = re.escape(
            term
        )

        patterns = (
            rf"\bdo\s+not\s+(?:\w+\s+){{0,4}}{escaped}\b",
            rf"\bdon['’]?t\s+(?:\w+\s+){{0,4}}{escaped}\b",
            rf"\bnever\s+(?:\w+\s+){{0,4}}{escaped}\b",
            rf"\bmust\s+not\s+(?:\w+\s+){{0,4}}{escaped}\b",
            rf"\bshould\s+not\s+(?:\w+\s+){{0,4}}{escaped}\b",
            rf"\bwithout\s+(?:\w+\s+){{0,3}}{escaped}\b",
            rf"\bno\s+(?:\w+\s+){{0,3}}{escaped}\b",
            rf"\bavoid\s+(?:\w+\s+){{0,3}}{escaped}\b",
        )

        return any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            is not None
            for pattern in patterns
        )

    def _is_negated_without_context(
        self,
        text: str,
        term: str,
    ) -> bool:
        """
        Additional bounded check for common phrases such as:

            "without deployment"
            "without deleting"
            "no production deployment"
        """

        escaped = re.escape(
            term
        )

        patterns = (
            rf"\bwithout\s+{escaped}\b",
            rf"\bno\s+{escaped}\b",
            rf"\bwithout\s+\w+\s+{escaped}\b",
            rf"\bno\s+\w+\s+{escaped}\b",
        )

        return any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            is not None
            for pattern in patterns
        )

    def _contains_global_no_action(
        self,
        text: str,
    ) -> bool:
        """
        Detect broad prohibition wording.
        """

        return any(
            phrase in text
            for phrase in (
                "do not",
                "don't",
                "never",
                "must not",
                "should not",
                "without",
            )
        )

    # ==================================================================
    # Token helpers
    # ==================================================================

    @staticmethod
    def _term_present(
        text: str,
        term: str,
    ) -> bool:
        """
        Detect a term safely.

        Multi-word terms are matched as phrases.
        """

        escaped = re.escape(
            term
        )

        if " " in term:
            pattern = (
                rf"(?<!\w){escaped}(?!\w)"
            )
        else:
            pattern = (
                rf"(?<!\w){escaped}(?!\w)"
            )

        return (
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            is not None
        )

    # ==================================================================
    # File helpers
    # ==================================================================

    def _looks_like_file(
        self,
        value: str,
    ) -> bool:
        """
        Determine whether a string resembles a repository file path.
        """

        if not value:
            return False

        value = value.strip()

        if not value:
            return False

        # Avoid treating URLs as repository paths.
        if value.startswith(
            (
                "http://",
                "https://",
                "ftp://",
            )
        ):
            return False

        # Avoid obvious natural-language fragments.
        if any(
            character in value
            for character in (
                '"',
                "'",
                "`",
                "\n",
                "\r",
            )
        ):
            return False

        lower = value.lower()

        # Directory/path references.
        if "/" in value or "\\" in value:
            last_component = re.split(
                r"[/\\]",
                value,
            )[-1]

            if "." in last_component:
                return True

            # Explicit directory paths are useful too.
            return (
                value.startswith(
                    (
                        "./",
                        "../",
                    )
                )
                or lower.startswith(
                    (
                        "brain/",
                        "core/",
                        "tests/",
                        "src/",
                        "app/",
                        "api/",
                        "config/",
                        "docs/",
                    )
                )
            )

        # Dotfiles.
        if value.startswith(".") and len(
            value
        ) > 1:
            return True

        # Known extension.
        if any(
            lower.endswith(
                extension
            )
            for extension in self._FILE_EXTENSIONS
        ):
            return True

        return False

    # ==================================================================
    # Metadata
    # ==================================================================

    def _build_metadata(
        self,
        *,
        raw: str,
        lower_raw: str,
        requested_files: list[str],
        risk_flags: list[str],
        requires_approval: bool,
        constraints: list[str],
    ) -> dict[str, Any]:
        """
        Build deterministic parser metadata.

        Metadata is intentionally compact and JSON-safe.
        """

        create_only = (
            "CREATE_ONLY_EXISTING_FILES_PROTECTED"
            in constraints
        )

        no_deployment = (
            "NO_DEPLOYMENT"
            in constraints
        )

        no_github_push = (
            "NO_GITHUB_PUSH"
            in constraints
        )

        no_delete = (
            "NO_DELETE"
            in constraints
        )

        return {
            "parser": "deterministic-v2",
            "requirement_length": len(raw),
            "requested_file_count": len(
                requested_files
            ),
            "risk_flag_count": len(
                risk_flags
            ),
            "requires_approval": (
                requires_approval
            ),
            "create_only": create_only,
            "no_deployment": no_deployment,
            "no_github_push": no_github_push,
            "no_delete": no_delete,
            "explicit_safety_constraints": [
                constraint
                for constraint in (
                    "CREATE_ONLY_EXISTING_FILES_PROTECTED"
                    if create_only
                    else None,
                    "NO_DEPLOYMENT"
                    if no_deployment
                    else None,
                    "NO_GITHUB_PUSH"
                    if no_github_push
                    else None,
                    "NO_DELETE"
                    if no_delete
                    else None,
                )
                if constraint is not None
            ],
        }

    # ==================================================================
    # Summary
    # ==================================================================

    @staticmethod
    def _build_summary(
        *,
        lines: list[str],
        raw: str,
    ) -> str:
        """
        Produce a concise deterministic summary.

        The parser does not rewrite the Master's meaning.
        """

        if lines:
            return lines[0][:500]

        return raw[:500]

    # ==================================================================
    # Utility
    # ==================================================================

    @staticmethod
    def _deduplicate(
        values: list[str],
    ) -> list[str]:
        """
        Deduplicate while preserving original order.
        """

        result: list[str] = []

        seen: set[str] = set()

        for value in values:

            clean = str(
                value
            ).strip()

            if not clean:
                continue

            key = clean.casefold()

            if key in seen:
                continue

            seen.add(key)

            result.append(
                clean
            )

        return result


__all__ = [
    "Requirement",
    "RequirementParser",
]