"""Lossless large-request intake and context assembly for ARIA.

This module deliberately does not call an LLM, execute tools, modify files,
or truncate the master's request. It converts one large request or multiple
ordered message parts into a structured, auditable request packet that can be
handed to the final cognitive integration layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RequestPart:
    """One ordered piece of a master request."""

    part_id: str
    index: int
    text: str
    source: str = "unknown"
    received_at: float = field(default_factory=time.time)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RequestSection:
    """A lossless section detected inside the assembled request."""

    index: int
    title: str
    text: str
    start: int
    end: int

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class LargeRequestPacket:
    """Complete request representation for downstream cognitive processing."""

    request_id: str
    text: str
    parts: Tuple[RequestPart, ...]
    sections: Tuple[RequestSection, ...]
    character_count: int
    part_count: int
    section_count: int
    sha256: str
    intent_hints: Tuple[str, ...]
    constraints: Tuple[str, ...]
    explicit_no_action: bool
    explicit_implementation: bool
    explicit_authorization: bool
    contains_code: bool
    contains_file_paths: bool
    contains_urls: bool
    complete: bool = True
    truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["parts"] = [asdict(part) for part in self.parts]
        data["sections"] = [asdict(section) for section in self.sections]
        return data


class LargeRequestContext:
    """Accumulate and analyze arbitrarily large ordered request parts.

    There is intentionally no fixed 4K/8K/32K request limit here.

    Limits belonging to an LLM provider or transport layer must be handled
    later without destroying this canonical request packet.
    """

    VERSION = "ARIA-LARGE-REQUEST-CONTEXT-20261006"

    _HEADING_RE = re.compile(
        r"(?m)^(?:#{1,6}\s+(.+?)\s*|(?:\d+[.)]|[A-Za-z][.)])\s+(.+?)\s*)$"
    )

    _PATH_RE = re.compile(
        r"(?<![\w.-])(?:[A-Za-z]:[\\/]|/|\.?\./)[^\s`<>\"']+"
    )

    _URL_RE = re.compile(
        r"https?://[^\s<>\"']+",
        re.IGNORECASE,
    )

    _CONSTRAINT_RE = re.compile(
        r"(?im)^\s*(?:[-*]\s*)?"
        r"(?:must|should|need to|needs to|do not|don't|never|only|always|"
        r"must not|cannot|can't)\b.*$"
    )

    _NO_ACTION_PATTERNS = (
        r"\bdo\s+not\s+(?:modify|change|edit|write|create|delete|"
        r"commit|push|deploy|execute|implement)\b",
        r"\bwithout\s+(?:modifying|changing|editing|writing|creating|"
        r"deleting|committing|pushing|deploying|executing|implementing)\b",
        r"\bread[- ]only\b",
        r"\bplan(?:ning)?\s+only\b",
        r"\bexplain\s+(?:the\s+)?phases\b",
    )

    _IMPLEMENT_PATTERNS = (
        r"\bimplement\b",
        r"\bbuild\b",
        r"\bcreate\b",
        r"\bdevelop\b",
        r"\badd\b",
        r"\bfix\b",
        r"\bmodify\b",
        r"\bchange\b",
        r"\breplace\b",
        r"\brefactor\b",
    )

    _AUTH_PATTERNS = (
        r"\bauthori[sz]e\b",
        r"\bauthori[sz]ation\b",
        r"\bapprove\b",
        r"\bapproved\b",
        r"\bpermission\b",
        r"\bpush\s+to\s+github\b",
        r"\bdeploy\b",
    )

    def __init__(self, request_id: Optional[str] = None) -> None:
        self.request_id = request_id or f"req-{uuid.uuid4().hex}"
        self._parts: List[RequestPart] = []
        self._closed = False

    @property
    def part_count(self) -> int:
        return len(self._parts)

    def add_part(
        self,
        text: str,
        *,
        index: Optional[int] = None,
        source: str = "unknown",
        part_id: Optional[str] = None,
    ) -> RequestPart:
        """Append one part without truncating or rewriting it."""

        if self._closed:
            raise RuntimeError("Request context is already finalized")

        if not isinstance(text, str):
            raise TypeError("request part text must be a string")

        if index is None:
            index = len(self._parts)

        if index < 0:
            raise ValueError("part index cannot be negative")

        if any(part.index == index for part in self._parts):
            raise ValueError(f"duplicate request part index: {index}")

        part = RequestPart(
            part_id=part_id or f"{self.request_id}-part-{index}",
            index=index,
            text=text,
            source=source,
        )

        self._parts.append(part)
        self._parts.sort(key=lambda item: item.index)

        return part

    def add_parts(
        self,
        parts: Iterable[Mapping[str, Any]],
    ) -> None:
        """Append multiple parts using their supplied ordering metadata."""

        for item in parts:
            self.add_part(
                str(item.get("text", "")),
                index=item.get("index"),
                source=str(item.get("source", "unknown")),
                part_id=item.get("part_id"),
            )

    def assemble_text(self) -> str:
        """Return the exact ordered request text without truncation."""

        return "".join(
            part.text
            for part in sorted(
                self._parts,
                key=lambda item: item.index,
            )
        )

    def finalize(self) -> LargeRequestPacket:
        """Freeze the request into a complete packet."""

        if not self._parts:
            raise ValueError("cannot finalize an empty request")

        self._closed = True

        text = self.assemble_text()

        sections = tuple(
            self._detect_sections(text)
        )

        lower = text.lower()

        intent_hints = self._intent_hints(lower)

        constraints = tuple(
            self._extract_constraints(text)
        )

        explicit_no_action = self._matches_any(
            lower,
            self._NO_ACTION_PATTERNS,
        )

        explicit_implementation = self._matches_any(
            lower,
            self._IMPLEMENT_PATTERNS,
        )

        explicit_authorization = self._matches_any(
            lower,
            self._AUTH_PATTERNS,
        )

        return LargeRequestPacket(
            request_id=self.request_id,
            text=text,
            parts=tuple(self._parts),
            sections=sections,
            character_count=len(text),
            part_count=len(self._parts),
            section_count=len(sections),
            sha256=hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest(),
            intent_hints=tuple(intent_hints),
            constraints=constraints,
            explicit_no_action=explicit_no_action,
            explicit_implementation=explicit_implementation,
            explicit_authorization=explicit_authorization,
            contains_code=self._contains_code(text),
            contains_file_paths=bool(
                self._PATH_RE.search(text)
            ),
            contains_urls=bool(
                self._URL_RE.search(text)
            ),
            complete=True,
            truncated=False,
        )

    def reset(self) -> None:
        """Reset the context so it can receive a new request."""

        self._parts.clear()
        self._closed = False

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        request_id: Optional[str] = None,
        source: str = "message",