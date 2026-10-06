"""Lossless large-request intake and context assembly for ARIA."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RequestPart:
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
    """Build a complete request packet without applying an LLM-sized limit."""

    VERSION = "ARIA-LARGE-REQUEST-CONTEXT-20261006.1"

    _HEADING_RE = re.compile(
        r"(?m)^(?:#{1,6}\s+(.+?)\s*|(?:\d+[.)]|[A-Za-z][.)])\s+(.+?)\s*)$"
    )
    _PATH_RE = re.compile(
        r"(?<![\w.-])(?:[A-Za-z]:[\\/]|/|\.?\.?/)[^\s`<>\"']+"
    )
    _URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
    _CONSTRAINT_RE = re.compile(
        r"(?im)^\s*(?:[-*]\s*)?(?:must|should|need to|needs to|do not|don't|never|only|always|must not|cannot|can't)\b.*$"
    )
    _NO_ACTION_PATTERNS = (
        r"\bdo\s+not\s+(?:modify|change|edit|write|create|delete|commit|push|deploy|execute|implement)\b",
        r"\bwithout\s+(?:modifying|changing|editing|writing|creating|deleting|committing|pushing|deploying|executing|implementing)\b",
        r"\bread[- ]only\b",
        r"\bplan(?:ning)?\s+only\b",
        r"\bexplain\s+(?:the\s+)?phases\b",
    )
    _IMPLEMENT_PATTERNS = (
        r"\bimplement\b", r"\bbuild\b", r"\bcreate\b", r"\bdevelop\b",
        r"\badd\b", r"\bfix\b", r"\bmodify\b", r"\bchange\b", r"\breplace\b",
    )
    _AUTH_PATTERNS = (
        r"\bauthori[sz]e\b", r"\bauthori[sz]ation\b", r"\bapprove\b",
        r"\bapproved\b", r"\bpermission\b", r"\bpush\s+to\s+github\b", r"\bdeploy\b",
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

    def add_parts(self, parts: Iterable[Mapping[str, Any]]) -> None:
        for item in parts:
            self.add_part(
                str(item.get("text", "")),
                index=item.get("index"),
                source=str(item.get("source", "unknown")),
                part_id=item.get("part_id"),
            )

    def assemble_text(self) -> str:
        return "".join(part.text for part in sorted(self._parts, key=lambda item: item.index))

    def finalize(self) -> LargeRequestPacket:
        if not self._parts:
            raise ValueError("cannot finalize an empty request")
        self._closed = True
        text = self.assemble_text()
        lower = text.lower()
        sections = tuple(self._detect_sections(text))
        return LargeRequestPacket(
            request_id=self.request_id,
            text=text,
            parts=tuple(self._parts),
            sections=sections,
            character_count=len(text),
            part_count=len(self._parts),
            section_count=len(sections),
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            intent_hints=tuple(self._intent_hints(lower)),
            constraints=tuple(self._extract_constraints(text)),
            explicit_no_action=self._matches_any(lower, self._NO_ACTION_PATTERNS),
            explicit_implementation=self._matches_any(lower, self._IMPLEMENT_PATTERNS),
            explicit_authorization=self._matches_any(lower, self._AUTH_PATTERNS),
            contains_code=self._contains_code(text),
            contains_file_paths=bool(self._PATH_RE.search(text)),
            contains_urls=bool(self._URL_RE.search(text)),
            complete=True,
            truncated=False,
        )

    def reset(self) -> None:
        self._parts.clear()
        self._closed = False

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        request_id: Optional[str] = None,
        source: str = "message",
    ) -> LargeRequestPacket:
        context = cls(request_id=request_id)
        context.add_part(text, index=0, source=source)
        return context.finalize()

    @classmethod
    def from_parts(
        cls,
        parts: Sequence[str],
        *,
        request_id: Optional[str] = None,
        source: str = "message",
    ) -> LargeRequestPacket:
        context = cls(request_id=request_id)
        for index, text in enumerate(parts):
            context.add_part(text, index=index, source=source)
        return context.finalize()

    @classmethod
    def _detect_sections(cls, text: str) -> List[RequestSection]:
        matches = list(cls._HEADING_RE.finditer(text))
        if not matches:
            return [RequestSection(0, "request", text, 0, len(text))]
        sections: List[RequestSection] = []
        if matches[0].start() > 0:
            sections.append(RequestSection(0, "request", text[:matches[0].start()], 0, matches[0].start()))
        for position, match in enumerate(matches):
            start = match.start()
            end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
            title = (match.group(1) or match.group(2) or "section").strip()
            sections.append(RequestSection(len(sections), title, text[start:end], start, end))
        return sections

    @classmethod
    def _extract_constraints(cls, text: str) -> List[str]:
        values: List[str] = []
        seen = set()
        for line in text.splitlines():
            cleaned = line.strip()
            if not cleaned or not cls._CONSTRAINT_RE.match(cleaned):
                continue
            key = cleaned.casefold()
            if key not in seen:
                seen.add(key)
                values.append(cleaned)
        return values

    @classmethod
    def _intent_hints(cls, lower: str) -> List[str]:
        rules = (
            ("engineering", (r"\bimplement\b", r"\bcode\b", r"\brepository\b", r"\bproject\b", r"\bfix\b")),
            ("research", (r"\bresearch\b", r"\bsearch\b", r"\blatest\b", r"\blook\s+up\b")),
            ("planning", (r"\bplan\b", r"\bphase(?:s)?\b", r"\bdesign\b", r"\barchitecture\b")),
            ("tool", (r"\bcalculate\b", r"\bconvert\b", r"\bexecute\b", r"\bopen\b")),
            ("memory", (r"\bremember\b", r"\bforget\b", r"\bmemorize\b")),
            ("document", (r"\bdocument\b", r"\bpdf\b", r"\bspreadsheet\b", r"\breport\b")),
            ("multimodal", (r"\bimage\b", r"\bphoto\b", r"\bvideo\b", r"\baudio\b", r"\bvoice\b")),
        )
        hints = [name for name, patterns in rules if any(re.search(pattern, lower) for pattern in patterns)]
        return hints or ["answer"]

    @staticmethod
    def _matches_any(text: str, patterns: Sequence[str]) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _contains_code(text: str) -> bool:
        if "```" in text:
            return True
        return bool(re.search(r"(?m)^\s*(?:def |class |import |from |function |const |let |SELECT\s+|</?[A-Za-z])", text))


__all__ = ["RequestPart", "RequestSection", "LargeRequestPacket", "LargeRequestContext"]
