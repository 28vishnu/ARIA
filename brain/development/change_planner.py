"""
ARIA Change Planner.

Builds a conservative, deterministic implementation plan from a
parsed Requirement.

This module does NOT:
    - modify files
    - execute commands
    - generate code
    - deploy
    - push to GitHub

Its responsibility is to decide what kind of file changes are
permitted before CodeWriter is allowed to touch the workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .requirement_parser import Requirement


# ======================================================================
# File change
# ======================================================================


@dataclass(frozen=True)
class FileChange:
    """
    A single planned repository change.
    """

    path: str
    action: str
    reason: str
    risk: str = "low"

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "action": self.action,
            "reason": self.reason,
            "risk": self.risk,
        }


# ======================================================================
# Change plan
# ======================================================================


@dataclass(frozen=True)
class ChangePlan:
    """
    Complete deterministic implementation plan.
    """

    requirement: Requirement

    changes: tuple[FileChange, ...] = ()

    tests: tuple[str, ...] = ()

    risks: tuple[str, ...] = ()

    requires_approval: bool = False

    blocked: bool = False

    block_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "changes": [
                change.to_dict()
                for change in self.changes
            ],
            "tests": list(self.tests),
            "risks": list(self.risks),
            "requires_approval": (
                self.requires_approval
            ),
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


# ======================================================================
# Change planner
# ======================================================================


class ChangePlanner:
    """
    Builds a conservative implementation plan.

    The planner is intentionally deterministic.

    Important rule:

        The Master's constraints always take precedence over
        generated implementation suggestions.

    Example:

        "Create aria_test.txt.
         Do not modify any existing files."

    If aria_test.txt already exists:

        blocked = True

    If aria_test.txt does not exist:

        action = "create"

    The planner never silently changes that request into:

        action = "modify"
    """

    # ------------------------------------------------------------------
    # Protected repository prefixes.
    # ------------------------------------------------------------------

    PROTECTED_PREFIXES = (
        ".git/",
        ".github/workflows/",
        ".aria_workspaces/",
        ".aria_workspace/",
    )

    # ------------------------------------------------------------------
    # Protected exact names.
    # ------------------------------------------------------------------

    PROTECTED_NAMES = (
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".env.test",
        ".env.staging",
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "service-account.json",
    )

    # ------------------------------------------------------------------
    # Sensitive filename fragments.
    # ------------------------------------------------------------------

    SENSITIVE_NAME_FRAGMENTS = (
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        "credential",
        "credentials",
        "secret",
        "secrets",
        "password",
        "passwd",
        "token",
        "private_key",
        "private-key",
    )

    # ------------------------------------------------------------------
    # Paths that are especially dangerous to change.
    # ------------------------------------------------------------------

    HIGH_RISK_PATHS = frozenset(
        {
            "main.py",
            "core/bootstrap.py",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "package-lock.json",
        }
    )

    # ------------------------------------------------------------------
    # Allowed action vocabulary.
    # ------------------------------------------------------------------

    VALID_ACTIONS = frozenset(
        {
            "create",
            "modify",
            "inspect",
        }
    )

    # ==================================================================
    # Public API
    # ==================================================================

    def plan(
        self,
        requirement: Requirement,
        *,
        existing_paths: Iterable[str] = (),
    ) -> ChangePlan:
        """
        Build a deterministic change plan.

        Args:
            requirement:
                Parsed Requirement object.

            existing_paths:
                Repository-relative paths currently present in the
                inspected repository.

        Returns:
            ChangePlan

        Raises:
            TypeError:
                If requirement is not a Requirement.
        """

        if not isinstance(
            requirement,
            Requirement,
        ):
            raise TypeError(
                "requirement must be a Requirement."
            )

        existing = self._normalise_existing_paths(
            existing_paths
        )

        risks = list(
            requirement.risk_flags
        )

        changes: list[FileChange] = []

        blocked = False

        block_reasons: list[str] = []

        # --------------------------------------------------------------
        # Extract deterministic requirement constraints.
        # --------------------------------------------------------------

        create_only = (
            self._is_create_only_requirement(
                requirement
            )
        )

        no_modifications = (
            self._forbids_existing_modifications(
                requirement
            )
        )

        no_delete = (
            self._has_constraint(
                requirement,
                "NO_DELETE",
            )
        )

        # --------------------------------------------------------------
        # Explicit requested files.
        # --------------------------------------------------------------

        for raw_path in (
            requirement.requested_files
        ):

            normalized = self._normalise_path(
                raw_path
            )

            # ----------------------------------------------------------
            # Invalid / unsafe path.
            # ----------------------------------------------------------

            if normalized is None:

                blocked = True

                reason = (
                    "Unsafe or invalid repository path "
                    f"requested: {raw_path}"
                )

                block_reasons.append(
                    reason
                )

                risks.append(
                    "unsafe_path"
                )

                continue

            # ----------------------------------------------------------
            # Protected path.
            # ----------------------------------------------------------

            protection_reason = (
                self._protected_path_reason(
                    normalized
                )
            )

            if protection_reason:

                blocked = True

                reason = (
                    f"Protected path requested: "
                    f"{normalized} "
                    f"({protection_reason})"
                )

                block_reasons.append(
                    reason
                )

                risks.append(
                    "protected_path"
                )

                continue

            # ----------------------------------------------------------
            # Determine whether the file exists.
            # ----------------------------------------------------------

            exists = (
                normalized in existing
            )

            # ----------------------------------------------------------
            # Existing file + create-only requirement.
            #
            # This is a hard safety boundary.
            # ----------------------------------------------------------

            if exists and (
                create_only
                or no_modifications
            ):

                blocked = True

                reason = (
                    "Existing file modification is "
                    "forbidden by the requirement: "
                    f"{normalized}"
                )

                block_reasons.append(
                    reason
                )

                risks.append(
                    "existing_file_modification"
                )

                continue

            # ----------------------------------------------------------
            # Determine action.
            # ----------------------------------------------------------

            if exists:
                action = "modify"
            else:
                action = "create"

            # ----------------------------------------------------------
            # Risk classification.
            # ----------------------------------------------------------

            risk = self._path_risk(
                normalized
            )

            if risk == "high":
                risks.append(
                    "high_risk_file"
                )

            elif risk == "critical":
                risks.append(
                    "critical_path"
                )

            # ----------------------------------------------------------
            # Existing file modifications always receive an explicit
            # reason. This prevents downstream components from
            # confusing an inferred modification with a requested one.
            # ----------------------------------------------------------

            if action == "modify":

                reason = (
                    "Explicitly referenced existing "
                    "file; modification is permitted "
                    "by the requirement."
                )

            else:

                reason = (
                    "Explicitly referenced file does "
                    "not currently exist; creation "
                    "is permitted."
                )

            changes.append(
                FileChange(
                    path=normalized,
                    action=action,
                    reason=reason,
                    risk=risk,
                )
            )

        # --------------------------------------------------------------
        # No explicit file path.
        #
        # The development agent may inspect the repository and
        # determine the required implementation.
        # --------------------------------------------------------------

        if (
            not changes
            and not blocked
            and not requirement.requested_files
        ):

            changes.append(
                FileChange(
                    path="",
                    action="inspect",
                    reason=(
                        "No explicit repository file was "
                        "supplied. The development agent "
                        "must inspect the repository before "
                        "selecting implementation files."
                    ),
                    risk="medium",
                )
            )

        # --------------------------------------------------------------
        # Explicitly requested deletion is not represented by the
        # current FileChange action vocabulary.
        #
        # Block it rather than silently translating it into another
        # action.
        # --------------------------------------------------------------

        if no_delete and self._requests_deletion(
            requirement
        ):

            blocked = True

            block_reasons.append(
                "Deletion is explicitly prohibited "
                "by the requirement."
            )

            risks.append(
                "delete_prohibited"
            )

        # --------------------------------------------------------------
        # Determine approval.
        #
        # Approval is required for:
        #   - parser-required approval
        #   - high/critical changes
        #   - sensitive repository paths
        #
        # Explicitly prohibited operations do not create an approval
        # request simply because their words appear in the requirement.
        # --------------------------------------------------------------

        requires_approval = (
            requirement.requires_approval
            or any(
                change.risk
                in {
                    "high",
                    "critical",
                }
                for change in changes
            )
        )

        # --------------------------------------------------------------
        # Protected/unsafe plans must not proceed to CodeWriter.
        # --------------------------------------------------------------

        if blocked:
            risks.append(
                "plan_blocked"
            )

        # --------------------------------------------------------------
        # Tests.
        # --------------------------------------------------------------

        tests = self._build_test_plan(
            requirement
        )

        # --------------------------------------------------------------
        # Stable deduplication.
        # --------------------------------------------------------------

        final_risks = self._deduplicate(
            risks
        )

        final_changes = tuple(
            changes
        )

        final_block_reason = (
            self._combine_block_reasons(
                block_reasons
            )
            if blocked
            else None
        )

        return ChangePlan(
            requirement=requirement,
            changes=final_changes,
            tests=tuple(
                self._deduplicate(
                    tests
                )
            ),
            risks=tuple(
                final_risks
            ),
            requires_approval=(
                requires_approval
            ),
            blocked=blocked,
            block_reason=final_block_reason,
        )

    # ==================================================================
    # Existing path normalization
    # ==================================================================

    def _normalise_existing_paths(
        self,
        paths: Iterable[str],
    ) -> set[str]:
        """
        Normalize repository paths while ignoring invalid values.
        """

        result: set[str] = set()

        for path in paths:

            normalized = self._normalise_path(
                str(path)
            )

            if normalized is None:
                continue

            result.add(
                normalized
            )

        return result

    # ==================================================================
    # Path normalization
    # ==================================================================

    @staticmethod
    def _normalise_path(
        path: str,
    ) -> str | None:
        """
        Normalize a repository-relative path.

        Returns None for unsafe paths.

        The planner rejects:
            - absolute Unix paths
            - Windows drive paths
            - parent traversal
            - empty paths
        """

        if not isinstance(
            path,
            str,
        ):
            return None

        value = path.strip()

        if not value:
            return None

        value = value.replace(
            "\\",
            "/",
        )

        # --------------------------------------------------------------
        # Absolute Unix path.
        # --------------------------------------------------------------

        if value.startswith("/"):
            return None

        # --------------------------------------------------------------
        # Windows drive path.
        # --------------------------------------------------------------

        if (
            len(value) >= 2
            and value[1] == ":"
        ):
            return None

        # --------------------------------------------------------------
        # Normalize ./ prefixes.
        # --------------------------------------------------------------

        while value.startswith(
            "./"
        ):
            value = value[2:]

        if not value:
            return None

        # --------------------------------------------------------------
        # Reject parent traversal.
        # --------------------------------------------------------------

        components = value.split(
            "/"
        )

        if any(
            component == ".."
            for component in components
        ):
            return None

        # --------------------------------------------------------------
        # Reject empty/malformed traversal components.
        # --------------------------------------------------------------

        components = [
            component
            for component in components
            if component
        ]

        if not components:
            return None

        normalized = "/".join(
            components
        )

        return normalized

    # ==================================================================
    # Protected paths
    # ==================================================================

    def _protected_path_reason(
        self,
        path: str,
    ) -> str | None:
        """
        Return a protection reason, or None when the path is safe
        from the planner's protected-path perspective.
        """

        normalized = path.replace(
            "\\",
            "/",
        ).lstrip(
            "./"
        )

        lower = normalized.lower()

        # Exact protected names.
        basename = (
            normalized.rsplit(
                "/",
                1
            )[-1]
            .lower()
        )

        if basename in {
            name.lower()
            for name in self.PROTECTED_NAMES
        }:
            return "protected configuration/credential file"

        # Protected prefixes.
        for prefix in self.PROTECTED_PREFIXES:

            if lower.startswith(
                prefix.lower()
            ):
                return (
                    "protected repository directory"
                )

        # Sensitive filename patterns.
        if self._is_sensitive_filename(
            basename
        ):
            return (
                "credential, secret, or private-key "
                "file"
            )

        # Git internals.
        if (
            lower == ".git"
            or lower.startswith(
                ".git/"
            )
        ):
            return "Git internal data"

        return None

    # ==================================================================
    # Sensitive filenames
    # ==================================================================

    def _is_sensitive_filename(
        self,
        basename: str,
    ) -> bool:
        """
        Detect sensitive credential/secret filenames.
        """

        lower = basename.lower()

        # Do not classify harmless names such as "tokenizer.py"
        # merely because they contain "token".
        #
        # Match stronger credential-oriented patterns.
        strong_fragments = (
            ".pem",
            ".p12",
            ".pfx",
            ".key",
            "credentials",
            "credential",
            "secret",
            "secrets",
            "password",
            "passwd",
            "private_key",
            "private-key",
        )

        return any(
            fragment in lower
            for fragment in strong_fragments
        )

    # ==================================================================
    # Risk classification
    # ==================================================================

    def _path_risk(
        self,
        path: str,
    ) -> str:
        """
        Classify a planned path.

        critical:
            Security/protected paths. These should normally already
            have been blocked.

        high:
            Core runtime/deployment configuration.

        medium:
            Important project configuration.

        low:
            Ordinary source/documentation/test files.
        """

        lower = path.lower()

        if self._is_sensitive_filename(
            lower.rsplit(
                "/",
                1
            )[-1]
        ):
            return "critical"

        if lower in {
            item.lower()
            for item in self.HIGH_RISK_PATHS
        }:
            return "high"

        if lower.startswith(
            (
                "core/",
                "brain/core/",
                "deployment/",
                ".github/",
            )
        ):
            return "high"

        if lower.endswith(
            (
                "pyproject.toml",
                "requirements.txt",
                "package.json",
                "dockerfile",
                ".yaml",
                ".yml",
            )
        ):
            return "medium"

        return "low"

    # ==================================================================
    # Requirement constraint helpers
    # ==================================================================

    @staticmethod
    def _has_constraint(
        requirement: Requirement,
        constraint: str,
    ) -> bool:
        """
        Check semantic constraint metadata first, then raw
        constraint text.
        """

        if constraint in (
            requirement.constraints
        ):
            return True

        metadata = (
            requirement.metadata
            if isinstance(
                requirement.metadata,
                dict,
            )
            else {}
        )

        explicit = metadata.get(
            "explicit_safety_constraints"
        )

        if isinstance(
            explicit,
            (list, tuple, set),
        ) and constraint in explicit:
            return True

        return False

    def _is_create_only_requirement(
        self,
        requirement: Requirement,
    ) -> bool:
        """
        Determine whether the Master explicitly requires creation
        without modifying existing files.
        """

        if self._has_constraint(
            requirement,
            "CREATE_ONLY_EXISTING_FILES_PROTECTED",
        ):
            return True

        metadata = (
            requirement.metadata
            if isinstance(
                requirement.metadata,
                dict,
            )
            else {}
        )

        if metadata.get(
            "create_only"
        ) is True:
            return True

        return any(
            phrase in (
                requirement.raw_text.lower()
            )
            for phrase in (
                "do not modify existing files",
                "don't modify existing files",
                "do not change existing files",
                "don't change existing files",
                "do not touch existing files",
                "don't touch existing files",
                "create only",
                "create-only",
            )
        )

    def _forbids_existing_modifications(
        self,
        requirement: Requirement,
    ) -> bool:
        """
        Determine whether modification of existing files is forbidden.
        """

        if self._is_create_only_requirement(
            requirement
        ):
            return True

        if self._has_constraint(
            requirement,
            "NO_UNREQUESTED_MODIFICATIONS",
        ):
            return True

        raw = requirement.raw_text.lower()

        return any(
            phrase in raw
            for phrase in (
                "do not modify existing",
                "don't modify existing",
                "do not change existing",
                "don't change existing",
                "do not touch existing",
                "don't touch existing",
                "leave existing files unchanged",
            )
        )

    # ==================================================================
    # Deletion detection
    # ==================================================================

    @staticmethod
    def _requests_deletion(
        requirement: Requirement,
    ) -> bool:
        """
        Determine whether the requirement actively requests deletion.

        Negative wording such as "do not delete" does not count.
        """

        text = requirement.raw_text.lower()

        positive_phrases = (
            "delete ",
            "remove ",
            "destroy ",
            "erase ",
            "purge ",
        )

        negative_phrases = (
            "do not delete",
            "don't delete",
            "never delete",
            "must not delete",
            "should not delete",
        )

        if any(
            phrase in text
            for phrase in negative_phrases
        ):
            # Continue checking whether another sentence separately
            # requests deletion.
            cleaned = text

            for phrase in negative_phrases:
                cleaned = cleaned.replace(
                    phrase,
                    "",
                )

            return any(
                phrase in cleaned
                for phrase in positive_phrases
            )

        return any(
            phrase in text
            for phrase in positive_phrases
        )

    # ==================================================================
    # Test planning
    # ==================================================================

    def _build_test_plan(
        self,
        requirement: Requirement,
    ) -> list[str]:
        """
        Build a conservative test plan.

        Natural-language acceptance criteria are retained as
        requirements; the actual TestRunner is responsible for
        deciding which executable test paths are valid.

        This prevents natural-language strings from accidentally
        being passed directly to pytest as filesystem paths.
        """

        tests: list[str] = []

        for criterion in (
            requirement.acceptance_criteria
        ):

            clean = str(
                criterion
            ).strip()

            if not clean:
                continue

            tests.append(
                clean
            )

        if not tests:

            tests.append(
                "Run relevant existing tests and "
                "static validation after changes."
            )

        return tests

    # ==================================================================
    # Utility
    # ==================================================================

    @staticmethod
    def _deduplicate(
        values: Iterable[str],
    ) -> list[str]:
        """
        Stable deduplication.
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

            seen.add(
                key
            )

            result.append(
                clean
            )

        return result

    @staticmethod
    def _combine_block_reasons(
        reasons: list[str],
    ) -> str:
        """
        Produce one bounded deterministic block reason.
        """

        unique = ChangePlanner._deduplicate(
            reasons
        )

        if not unique:
            return (
                "Development plan is blocked "
                "by a safety policy."
            )

        if len(unique) == 1:
            return unique[0][:2000]

        return (
            "; ".join(
                unique[:5]
            )
        )[:3000]


__all__ = [
    "FileChange",
    "ChangePlan",
    "ChangePlanner",
]