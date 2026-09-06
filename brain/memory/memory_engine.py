import re
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger("aria")

SCHEMA_VERSION = 3
MEMORY_SCHEMA_VERSION = 4

MEMORY_TYPES = {
    "personal",
    "preference",
    "goal",
    "project",
    "decision",
    "document",
    "fact",
    "schedule",
    "relationship",
    "skill",
    "event",
    "contact"
}

IMPORTANCE = {
    "low": 0.25,
    "medium": 0.5,
    "high": 0.75,
    "critical": 1.0
}


# =========================================================
# SENSITIVE / PII MEMORY PROTECTION
# =========================================================
#
# ARIA must never store or expose highly sensitive identity,
# financial, authentication, or security credentials.
#
# Protection is applied at multiple layers:
#
#   1. Input extraction
#   2. LLM-extracted memory validation
#   3. Database storage
#   4. Database retrieval
#   5. Broad personal-memory retrieval
#
# Existing sensitive records are filtered during retrieval.
# =========================================================

SENSITIVE_MEMORY_KEY_PATTERNS = (
    "aadhaar",
    "aadhar",
    "uidai",
    "pan_number",
    "pan_card",
    "passport_number",
    "passport_id",
    "voter_id",
    "voter_number",
    "driving_license",
    "driver_license",
    "license_number",
    "bank_account",
    "account_number",
    "credit_card",
    "debit_card",
    "card_number",
    "cvv",
    "cvc",
    "pin",
    "password",
    "passcode",
    "otp",
    "one_time_password",
    "secret",
    "private_key",
    "api_key",
    "access_token",
    "refresh_token",
    "auth_token",
    "security_answer",
)

SENSITIVE_QUERY_PATTERNS = (
    r"\baadhaar\b",
    r"\baadhar\b",
    r"\buidai\b",
    r"\bpan\s+(?:number|card)\b",
    r"\bpassport\s+(?:number|id)\b",
    r"\bvoter\s*(?:id|number)\b",
    r"\bdriving\s*licen[cs]e\b",
    r"\blicen[cs]e\s+number\b",
    r"\bbank\s+account\b",
    r"\baccount\s+number\b",
    r"\bcredit\s+card\b",
    r"\bdebit\s+card\b",
    r"\bcard\s+number\b",
    r"\bcvv\b",
    r"\bcvc\b",
    r"\botp\b",
    r"\bpassword\b",
    r"\bpasscode\b",
    r"\bprivate\s+key\b",
    r"\bapi\s+key\b",
    r"\baccess\s+token\b",
    r"\brefresh\s+token\b",
    r"\bauth(?:entication)?\s+token\b",
)

# Highly sensitive numeric identifiers.
SENSITIVE_VALUE_PATTERNS = (
    re.compile(
        r"\b\d{4}\s?\d{4}\s?\d{4}\b"
    ),
    re.compile(
        r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        re.IGNORECASE
    ),
)


def _normalized_memory_key(key: Any) -> str:
    """
    Convert a memory key into a safe comparison form.
    """

    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(key or "").lower()
    ).strip("_")


def _is_sensitive_memory_key(key: Any) -> bool:
    """
    Determine whether a memory key refers to sensitive data.
    """

    normalized = _normalized_memory_key(key)

    if not normalized:
        return False

    return any(
        pattern in normalized
        for pattern in SENSITIVE_MEMORY_KEY_PATTERNS
    )


def _contains_sensitive_query(query: Any) -> bool:
    """
    Detect queries requesting highly sensitive information.
    """

    text = str(query or "").lower()

    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in SENSITIVE_QUERY_PATTERNS
    )


def _contains_sensitive_value(value: Any) -> bool:
    """
    Detect highly sensitive identifiers inside a value.

    This intentionally focuses on high-confidence identifiers such
    as Aadhaar and PAN rather than blocking ordinary numbers.
    """

    if value is None:
        return False

    if isinstance(value, (list, tuple, set)):
        return any(
            _contains_sensitive_value(item)
            for item in value
        )

    if isinstance(value, dict):
        return any(
            _contains_sensitive_value(item)
            for item in value.values()
        )

    text = str(value).strip()

    if not text:
        return False

    for pattern in SENSITIVE_VALUE_PATTERNS:
        if pattern.search(text):
            return True

    return False


def _is_sensitive_memory(memory: Any) -> bool:
    """
    Determine whether an entire memory record is sensitive.
    """

    if not isinstance(memory, dict):
        return False

    key = memory.get("key")

    if _is_sensitive_memory_key(key):
        return True

    value = memory.get("value")

    if _contains_sensitive_value(value):
        return True

    return False


class MemoryEngine:

    def __init__(
        self,
        mongo_db,
        llm_router=None,
        working_memory=None,
        learning_engine=None,
    ):
        self.db = mongo_db
        self.llm_router = llm_router
        self.working_memory = (
            working_memory
            if working_memory is not None
            else None
        )
        self.learning_engine = learning_engine

        self.memory_col = (
            mongo_db["personal_memory"]
            if mongo_db is not None else None
        )
        self.profile_col = (
            mongo_db["user_profile"]
            if mongo_db is not None else None
        )

        self.short_term_memory = []

    # =========================================================
    # SHORT-TERM MEMORY
    # =========================================================

    def add_short_term_memory(
        self,
        user,
        assistant,
    ):

        self.short_term_memory.append(
            {
                "user": user,
                "assistant": assistant,
            }
        )

        if len(self.short_term_memory) > 20:
            self.short_term_memory.pop(0)

    def recent_context(
        self,
        limit=5,
    ):

        return self.short_term_memory[-limit:]

    def clear_short_term_memory(self):

        self.short_term_memory.clear()

    # =========================================================
    # PREFETCH
    # =========================================================

    async def prefetch(self, route, session_id):
        """
        Prepare memory required by the current route.

        Prefetch is intentionally lightweight. It does not generate
        responses and does not mutate long-term memory.
        """

        if not route:
            return {}

        route_name = getattr(route, "name", None)

        if route_name is None:
            route_name = str(route)

        route_name = str(
            route_name
        ).lower().strip()

        context = {
            "route": route_name,
            "session_id": session_id,
            "memory_available": self.memory_col is not None,
        }

        if any(
            token in route_name
            for token in (
                "memory",
                "conversation",
                "chat",
                "personal",
                "profile",
            )
        ):
            context["recent_context"] = self.recent_context(
                limit=5
            )

        if self.working_memory is not None:
            try:
                semantic = self.working_memory.semantic()

                context["semantic_memory_available"] = (
                    semantic is not None
                )

            except Exception:
                logger.exception(
                    "[MemoryEngine] Semantic memory prefetch failed."
                )

                context["semantic_memory_available"] = False

        else:
            context["semantic_memory_available"] = False

        return context

    # =========================================================
    # SEMANTIC MEMORY
    # =========================================================

    def _update_semantic_memory(
        self,
        memory,
    ):
        """
        Mirror important memories into the semantic graph.
        """

        if not self.working_memory:
            return

        # Never mirror sensitive memory into semantic memory.
        if _is_sensitive_memory(memory):
            logger.warning(
                "[MemorySecurity] Blocked sensitive memory "
                "from semantic memory."
            )
            return

        try:
            semantic = self.working_memory.semantic()

            if semantic is None:
                return

            semantic.add_node(
                node_id=memory.get("key"),
                node_type=memory.get(
                    "category",
                    "general"
                ),
                value=str(
                    memory.get("value")
                ),
                metadata={
                    "importance": memory.get(
                        "importance"
                    ),
                    "confidence": memory.get(
                        "confidence"
                    ),
                },
            )

            logger.info(
                "[SemanticMemory] Mirrored memory '%s' into graph.",
                memory.get(
                    "key",
                    "unknown"
                ),
            )

        except Exception:
            logger.exception(
                "[MemoryEngine] Semantic memory update failed."
            )

    # =========================================================
    # DATABASE INITIALISATION
    # =========================================================

    async def initialize_indexes(self):

        if self.memory_col is None:
            return

        try:
            await self.memory_col.create_index(
                "key"
            )

            await self.memory_col.create_index(
                "category"
            )

            await self.memory_col.create_index(
                "memory_type"
            )

            await self.memory_col.create_index(
                "updated_at"
            )

            await self.memory_col.create_index(
                [
                    ("key", 1),
                    ("value", 1)
                ]
            )

            logger.info(
                "[MemoryEngine] MongoDB indexes initialized."
            )

        except Exception as exc:
            logger.warning(
                "[MemoryEngine] Index creation note: %s",
                exc
            )

    # =========================================================
    # PROFILE
    # =========================================================

    async def get_profile(self) -> dict:

        if self.profile_col is None:
            return {}

        try:
            profile = await self.profile_col.find_one({})

            if not profile:
                return {}

            profile.pop(
                "_id",
                None
            )

            # Never expose sensitive profile fields through
            # this general profile method.
            safe_profile = {}

            for key, value in profile.items():

                if _is_sensitive_memory_key(key):
                    continue

                if _contains_sensitive_value(value):
                    continue

                safe_profile[key] = value

            return safe_profile

        except Exception:
            logger.exception(
                "[MemoryEngine] Failed to load profile."
            )

            return {}

    # =========================================================
    # NORMALISATION
    # =========================================================

    def _normalize(
        self,
        value: str
    ) -> str:

        value = value.strip()

        value = re.sub(
            r"\s+",
            " ",
            value
        )

        return value.strip(
            " .,!? "
        )

    def _normalize_key(
        self,
        subject: str
    ) -> str:
        """
        Convert equivalent human wording into one canonical
        memory key.
        """

        subject = subject.lower().strip()

        subject = subject.replace(
            "favourite",
            "favorite"
        )

        subject = subject.replace(
            "colour",
            "color"
        )

        subject = re.sub(
            r"^favorite\s+",
            "",
            subject
        )

        subject = re.sub(
            r"[^a-z0-9\s_]",
            "",
            subject
        )

        subject = re.sub(
            r"\s+",
            "_",
            subject
        )

        return f"favorite_{subject}"

    def _validate_value(
        self,
        value: str
    ) -> bool:

        if not value:
            return False

        cleaned = value.strip().lower()

        invalid = {
            "",
            "it",
            "that",
            "this",
            "something",
            "nothing",
            "everything"
        }

        return (
            len(cleaned) >= 2
            and cleaned not in invalid
        )

    # =========================================================
    # SHOULD MEMORY BE USED?
    # =========================================================

    def should_use_memory(
        self,
        query: str,
        intent: Optional[Any] = None
    ) -> bool:
        """
        Determine whether the query should use personal memory.
        """

        if not query:
            return False

        q = query.lower().strip()

        intent_name = (
            getattr(
                intent,
                "name",
                ""
            ).lower()
            if intent
            else ""
        )

        if intent_name in (
            "research",
            "coding",
            "web search",
            "tool"
        ):
            return False

        # Never use personal memory as a source for highly
        # sensitive identity/security requests.
        if _contains_sensitive_query(q):
            return False

        personal_patterns = (
            r"\bmy\b",
            r"\bmine\b",
            r"\bi\b",
            r"\bme\b",
            r"\bdo you remember\b",
            r"\bremember\b",
            r"\brecall\b",
            r"\babout me\b",
            r"\babout myself\b",
            r"\bwhat do you know about me\b",
            r"\bwhat have i told you\b",
        )

        if any(
            re.search(
                pattern,
                q
            )
            for pattern in personal_patterns
        ):
            return True

        factual_starters = (
            "who founded",
            "who is",
            "who was",
            "what is",
            "what was",
            "where is",
            "where was",
            "when was",
            "how does",
            "how do",
            "explain",
            "calculate",
        )

        if q.startswith(
            factual_starters
        ):
            return False

        return True

    # =========================================================
    # SHOULD THIS MESSAGE BE STORED?
    # =========================================================

    def _should_extract(
        self,
        text: str
    ) -> bool:

        if not text:
            return False

        # -----------------------------------------------------
        # SENSITIVE DATA PROTECTION
        # -----------------------------------------------------
        #
        # Never extract highly sensitive identity/security data.
        # This happens before deterministic or LLM extraction.
        # -----------------------------------------------------

        if _contains_sensitive_value(text):

            logger.warning(
                "[MemorySecurity] Sensitive identifier detected; "
                "memory extraction blocked."
            )

            return False

        if _contains_sensitive_query(text):

            # Questions requesting sensitive information are
            # not personal memories and must never be stored.
            return False

        lower = text.lower().strip()

        greetings = {
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "good morning",
            "good evening",
            "bye"
        }

        if lower in greetings:
            return False

        question_prefixes = (
            "what ",
            "what's ",
            "what is ",
            "who ",
            "where ",
            "when ",
            "why ",
            "how ",
            "do i ",
            "did i ",
            "can i "
        )

        if lower.startswith(
            question_prefixes
        ):
            return False

        if re.fullmatch(
            r"[\d+\-*/.()\s]+",
            text
        ):
            return False

        return True

    # =========================================================
    # CENTRAL MEMORY EXTRACTOR
    # =========================================================

    def _extract_memory(
        self,
        text: str
    ) -> Optional[Dict[str, Any]]:

        original = text.strip()
        lower = original.lower().strip()

        # -----------------------------------------------------
        # 1. NAME
        # -----------------------------------------------------

        name_patterns = [
            r"\bmy name is\s+([a-zA-Z][a-zA-Z .'-]{1,80})",
            r"\bi am called\s+([a-zA-Z][a-zA-Z .'-]{1,80})",
            r"\bi'm called\s+([a-zA-Z][a-zA-Z .'-]{1,80})"
        ]

        for pattern in name_patterns:

            match = re.search(
                pattern,
                original,
                re.IGNORECASE
            )

            if match:

                value = self._clean_clause(
                    match.group(1)
                )

                return {
                    "key": "name",
                    "value": value,
                    "category": "identity",
                    "memory_type": "fact",
                    "importance": 0.75,
                    "is_list": False
                }

        # -----------------------------------------------------
        # 2. PREFERRED NAME
        # -----------------------------------------------------

        preferred_name_patterns = [
            r"\bcall me\s+([a-zA-Z][a-zA-Z .'-]{1,50})",
            r"\bi prefer to be called\s+([a-zA-Z][a-zA-Z .'-]{1,50})",
            r"\bpreferred name is\s+([a-zA-Z][a-zA-Z .'-]{1,50})"
        ]

        for pattern in preferred_name_patterns:

            match = re.search(
                pattern,
                original,
                re.IGNORECASE
            )

            if match:

                value = self._clean_clause(
                    match.group(1)
                )

                return {
                    "key": "preferred_name",
                    "value": value,
                    "category": "identity",
                    "memory_type": "preference",
                    "importance": 0.75,
                    "is_list": False
                }

        # -----------------------------------------------------
        # 3. ADDRESSING PREFERENCE
        # -----------------------------------------------------

        if re.search(
            r"\b(?:don't|do not)\s+call me\s+(?:by|with)\s+my name\b",
            lower
        ):

            return {
                "key": "address_by_name",
                "value": "false",
                "category": "interaction_preference",
                "memory_type": "preference",
                "importance": 0.75,
                "is_list": False
            }

        # -----------------------------------------------------
        # 4. BIRTHDAY
        # -----------------------------------------------------

        birthday_patterns = [
            r"\bmy birthday is\s+(.+)",
            r"\bmy date of birth is\s+(.+)",
            r"\bi was born on\s+(.+)"
        ]

        for pattern in birthday_patterns:

            match = re.search(
                pattern,
                original,
                re.IGNORECASE
            )

            if match:

                value = self._clean_clause(
                    match.group(1)
                )

                return {
                    "key": "birthday",
                    "value": value,
                    "category": "personal",
                    "memory_type": "fact",
                    "importance": 0.75,
                    "is_list": False
                }

        # -----------------------------------------------------
        # 5. FAVORITES
        # -----------------------------------------------------

        fav_match = re.search(
            r"\bmy favou?rite\s+"
            r"([a-zA-Z0-9 ]+?)\s+is\s+"
            r"([^,.!?]+)",
            original,
            re.IGNORECASE
        )

        if fav_match:

            subject = fav_match.group(1)

            value = self._clean_clause(
                fav_match.group(2)
            )

            return {
                "key": self._normalize_key(
                    subject
                ),
                "value": value,
                "category": "preference",
                "memory_type": "preference",
                "importance": 0.5,
                "is_list": False
            }

        # -----------------------------------------------------
        # 6. STUDY / EDUCATION
        # -----------------------------------------------------

        study_match = re.search(
            r"\bi (?:study|am studying)\s+([^,.!?]+)",
            original,
            re.IGNORECASE
        )

        if study_match:

            value = self._clean_clause(
                study_match.group(1)
            )

            return {
                "key": "field_of_study",
                "value": value,
                "category": "education",
                "memory_type": "fact",
                "importance": 0.5,
                "is_list": False
            }

        # -----------------------------------------------------
        # 7. GENERAL LIKES
        # -----------------------------------------------------

        like_match = re.search(
            r"\bi\s+(?:like|love)\s+([^.!?]+)",
            original,
            re.IGNORECASE
        )

        if like_match:

            segment = self._clean_clause(
                like_match.group(1)
            )

            items = self._parse_preference_items(
                segment
            )

            if items:

                return {
                    "key": "user_likes",
                    "value": items,
                    "category": "preference",
                    "memory_type": "preference",
                    "importance": 0.25,
                    "is_list": True
                }

        # -----------------------------------------------------
        # 8. GENERAL "I PREFER"
        # -----------------------------------------------------

        prefer_match = re.search(
            r"\bi prefer\s+([^.!?]+)",
            original,
            re.IGNORECASE
        )

        if prefer_match:

            segment = self._clean_clause(
                prefer_match.group(1)
            )

            if not re.search(
                r"\b(?:but|don't|do not|call me|called)\b",
                segment,
                re.IGNORECASE
            ):

                return {
                    "key": "general_preference",
                    "value": segment,
                    "category": "interaction_preference",
                    "memory_type": "preference",
                    "importance": 0.5,
                    "is_list": False
                }

        return None

    # =========================================================
    # CLAUSE CLEANING
    # =========================================================

    def _clean_clause(
        self,
        value: str
    ) -> str:

        value = value.strip()

        value = re.split(
            r"\s+(?:but|and\s+i|because|although|however)\s+",
            value,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0]

        return self._normalize(
            value
        )

    # =========================================================
    # LIST PREFERENCES
    # =========================================================

    def _parse_preference_items(
        self,
        segment: str
    ) -> list[str]:

        segment = self._normalize(
            segment
        )

        segment = re.split(
            r"\s+(?:but|however|although|except)\s+",
            segment,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0]

        segment = re.sub(
            r"\s+\band\b\s+",
            ",",
            segment,
            flags=re.IGNORECASE
        )

        items = []

        for raw in segment.split(","):

            item = self._normalize(
                raw
            )

            item = re.sub(
                r"^(?:that|this|it|something)\s+",
                "",
                item,
                flags=re.IGNORECASE
            )

            item = self._normalize(
                item
            )

            if self._validate_value(item):
                items.append(item)

        unique_items = []

        for item in items:

            if item.lower() not in {
                existing.lower()
                for existing in unique_items
            }:
                unique_items.append(item)

        return unique_items

    # =========================================================
    # MEMORY RECORD BUILDER
    # =========================================================

    def _build_memory_record(
        self,
        memory: Dict[str, Any]
    ):

        now = datetime.now(
            timezone.utc
        ).isoformat()

        imp = memory.get(
            "importance",
            0.5
        )

        if isinstance(imp, str):

            imp = {
                "low": 0.25,
                "medium": 0.5,
                "high": 0.75,
                "critical": 1.0,
            }.get(
                imp.lower(),
                0.5
            )

        try:
            imp = float(imp)

        except (
            TypeError,
            ValueError
        ):
            imp = 0.5

        return {

            "key": memory["key"],

            "value": memory["value"],

            "summary": memory.get(
                "summary",
                str(memory["value"])
            ),

            "category": memory.get(
                "category",
                "general"
            ),

            "memory_type": memory.get(
                "memory_type",
                "fact"
            ),

            "importance": imp,

            "confidence": memory.get(
                "confidence",
                1.0
            ),

            "source": memory.get(
                "source",
                "conversation"
            ),

            "entities": memory.get(
                "entities",
                []
            ),

            "relationships": memory.get(
                "relationships",
                []
            ),

            "topics": memory.get(
                "topics",
                []
            ),

            "aliases": memory.get(
                "aliases",
                []
            ),

            "tags": memory.get(
                "tags",
                []
            ),

            "embedding_id": memory.get(
                "embedding_id"
            ),

            "document_id": memory.get(
                "document_id"
            ),

            "created_at": now,

            "updated_at": now,

            "last_accessed": now,

            "access_count": 0,

            "schema_version": MEMORY_SCHEMA_VERSION
        }

    # =========================================================
    # STORE MEMORY
    # =========================================================

    async def get_memory(
        self,
        key: str
    ) -> Optional[dict]:
        """
        Fetch an existing memory by key.

        Sensitive records are never returned through this helper.
        """

        if self.memory_col is None:
            return None

        try:

            memory = await self.memory_col.find_one(
                {"key": key}
            )

            if _is_sensitive_memory(memory):
                logger.warning(
                    "[MemorySecurity] Blocked sensitive memory retrieval "
                    "for key: %s",
                    _normalized_memory_key(key)
                )
                return None

            return memory

        except Exception:
            logger.exception(
                "[MemoryEngine] Failed to get memory."
            )

            return None

    async def _store_extracted_memory(
        self,
        memory: Dict[str, Any]
    ) -> dict:

        if self.memory_col is None:
            return {
                "success": False
            }

        if not isinstance(memory, dict):
            return {
                "success": False
            }

        # =====================================================
        # FINAL SECURITY GATE
        # =====================================================
        #
        # This protects both deterministic extraction and
        # LLM-generated memory extraction.
        # =====================================================

        if _is_sensitive_memory(memory):

            logger.warning(
                "[MemorySecurity] Blocked sensitive memory storage: %s",
                _normalized_memory_key(
                    memory.get("key")
                )
            )

            return {
                "success": False,
                "action": "blocked_sensitive_memory",
            }

        key = str(
            memory.get(
                "key",
                ""
            )
        ).strip()

        if not key:
            return {
                "success": False
            }

        value = memory.get(
            "value"
        )

        if value in (
            None,
            ""
        ):
            return {
                "success": False
            }

        # Never allow a sensitive identifier to pass through
        # under an unrelated/custom key.
        if _contains_sensitive_value(value):

            logger.warning(
                "[MemorySecurity] Blocked sensitive memory value."
            )

            return {
                "success": False,
                "action": "blocked_sensitive_memory",
            }

        # Always store canonical keys.
        if key.startswith(
            "favorite_"
        ):
            key = self._normalize_key(
                key.replace(
                    "favorite_",
                    "",
                    1
                )
            )

        # Final key security check after normalization.
        if _is_sensitive_memory_key(key):

            logger.warning(
                "[MemorySecurity] Blocked sensitive normalized "
                "memory key: %s",
                key
            )

            return {
                "success": False,
                "action": "blocked_sensitive_memory",
            }

        memory["key"] = key

        existing = await self.memory_col.find_one(
            {
                "key": key
            }
        )

        # -----------------------------------------------------
        # Legacy-key migration
        # -----------------------------------------------------

        if key == "favorite_color":

            legacy = await self.memory_col.find_one(
                {
                    "key": "favorite_colour"
                }
            )

            if (
                legacy is not None
                and existing is None
            ):

                existing = legacy

                await self.memory_col.update_one(
                    {
                        "_id": legacy["_id"]
                    },
                    {
                        "$set": {
                            "key": "favorite_color",
                            "updated_at": datetime.now(
                                timezone.utc
                            ).isoformat()
                        }
                    }
                )

        if existing is not None:

            # Existing sensitive record protection.
            if _is_sensitive_memory(existing):

                logger.warning(
                    "[MemorySecurity] Refusing to update "
                    "sensitive existing memory: %s",
                    key
                )

                return {
                    "success": False,
                    "action": "blocked_sensitive_memory",
                }

            existing["value"] = value

            existing["updated_at"] = datetime.now(
                timezone.utc
            ).isoformat()

            await self.update_memory(
                existing.get("_id"),
                existing
            )

            updated_memory = dict(
                existing
            )

            updated_memory.update(
                memory
            )

            updated_memory["key"] = key
            updated_memory["value"] = value
            updated_memory["updated_at"] = (
                existing["updated_at"]
            )

            # Never mirror sensitive data.
            if not _is_sensitive_memory(
                updated_memory
            ):
                self._update_semantic_memory(
                    updated_memory
                )

            logger.info(
                "[Memory] Updated existing memory: %s",
                key,
            )

            return {
                "success": True,
                "key": key,
                "value": str(value),
                "action": "update"
            }

        imp_val = memory.get(
            "importance",
            0.5
        )

        if isinstance(
            imp_val,
            str
        ):

            is_perm = imp_val in (
                "high",
                "critical"
            )

        else:

            try:
                is_perm = (
                    float(imp_val) >= 0.75
                )

            except (
                TypeError,
                ValueError
            ):
                is_perm = False

        memory["is_permanent"] = is_perm

        # -----------------------------------------------------
        # LIST MEMORY
        # -----------------------------------------------------

        if memory.get(
            "is_list"
        ):

            stored = []

            for item in value:

                if not self._validate_value(
                    item
                ):
                    continue

                # Protect individual list items.
                if _contains_sensitive_value(
                    item
                ):
                    logger.warning(
                        "[MemorySecurity] Blocked sensitive "
                        "list-memory item."
                    )
                    continue

                item_memory = dict(
                    memory
                )

                item_memory["value"] = item

                record = self._build_memory_record(
                    item_memory
                )

                existing_item = (
                    await self.memory_col.find_one(
                        {
                            "key": key,
                            "value": item
                        }
                    )
                )

                if (
                    existing_item
                    and existing_item.get(
                        "value"
                    ) == item
                ):

                    stored.append(
                        item
                    )

                    continue

                version = 1
                history = []

                if existing_item:

                    version = (
                        existing_item.get(
                            "version",
                            1
                        )
                        + 1
                    )

                    history = existing_item.get(
                        "history",
                        []
                    )

                    history.append(
                        {
                            "value": existing_item.get(
                                "value"
                            ),
                            "updated_at": existing_item.get(
                                "updated_at"
                            )
                        }
                    )

                    record["created_at"] = (
                        existing_item.get(
                            "created_at",
                            record["created_at"]
                        )
                    )

                    record["access_count"] = (
                        existing_item.get(
                            "access_count",
                            0
                        )
                    )

                record["version"] = version
                record["history"] = history
                record["is_permanent"] = (
                    memory["is_permanent"]
                )

                await self.memory_col.update_one(
                    {
                        "key": key,
                        "value": item
                    },
                    {
                        "$set": record,
                        "$setOnInsert": {
                            "expires_at": None
                        }
                    },
                    upsert=True
                )

                self._update_semantic_memory(
                    item_memory
                )

                stored.append(
                    item
                )

            return {
                "success": bool(stored),
                "key": key,
                "value": ", ".join(stored),
                "action": "stored"
            }

        # -----------------------------------------------------
        # SINGLE MEMORY
        # -----------------------------------------------------

        if not self._validate_value(
            str(value)
        ):
            return {
                "success": False
            }

        record = self._build_memory_record(
            memory
        )

        record["version"] = 1
        record["history"] = []
        record["is_permanent"] = (
            memory["is_permanent"]
        )

        # Final record-level security gate.
        if _is_sensitive_memory(
            record
        ):

            logger.warning(
                "[MemorySecurity] Final record gate "
                "blocked sensitive memory."
            )

            return {
                "success": False,
                "action": "blocked_sensitive_memory",
            }

        insert_result = await self.memory_col.insert_one(
            record
        )

        self._update_semantic_memory(
            memory
        )

        logger.info(
            "[MemoryEngine] Stored memory — Key: %s | Value: %s",
            key,
            value
        )

        return {
            "success": True,
            "key": key,
            "value": str(value),
            "action": "stored"
        }

    # =========================================================
    # PUBLIC STORE METHODS
    # =========================================================

    async def deterministic_extract_and_store(
        self,
        user_text: str
    ):

        if (
            self.memory_col is None
            or not self._should_extract(
                user_text
            )
        ):
            return

        memory = self._extract_memory(
            user_text
        )

        if memory:

            # Defense-in-depth.
            if _is_sensitive_memory(
                memory
            ):
                logger.warning(
                    "[MemorySecurity] Deterministic extraction "
                    "blocked sensitive memory."
                )
                return

            await self._store_extracted_memory(
                memory
            )

    async def process_and_store(
        self,
        user_text: str
    ) -> dict:

        if (
            self.memory_col is None
            or not self._should_extract(
                user_text
            )
        ):
            return {
                "success": False
            }

        memory = self._extract_memory(
            user_text
        )

        if memory:

            if _is_sensitive_memory(
                memory
            ):
                logger.warning(
                    "[MemorySecurity] Deterministic memory "
                    "blocked before storage."
                )

                return {
                    "success": False,
                    "action": "blocked_sensitive_memory",
                }

            res = await self._store_extracted_memory(
                memory
            )

            if (
                res.get("success")
                and hasattr(
                    self,
                    "learning_engine"
                )
                and self.learning_engine
            ):
                await self.learning_engine.learn_from_memory(
                    memory
                )

            return res

        # -----------------------------------------------------
        # LLM MEMORY EXTRACTION
        # -----------------------------------------------------

        if (
            self.llm_router is not None
            and hasattr(
                self.llm_router,
                "extract_memories"
            )
        ):

            try:

                memories = await self.llm_router.extract_memories(
                    user_text
                )

                if memories:

                    stored_results = []

                    for extracted in memories:

                        if not isinstance(
                            extracted,
                            dict
                        ):
                            continue

                        memory_data = {
                            "key": extracted.get(
                                "key"
                            ),
                            "value": extracted.get(
                                "value"
                            ),
                            "category": extracted.get(
                                "category",
                                "general"
                            ),
                            "memory_type": extracted.get(
                                "memory_type",
                                "fact"
                            ),
                            "importance": extracted.get(
                                "importance",
                                0.5
                            ),
                            "is_list": False
                        }

                        if (
                            not memory_data["key"]
                            or not memory_data["value"]
                        ):
                            continue

                        # -------------------------------------------------
                        # CRITICAL SECURITY GATE
                        # -------------------------------------------------
                        #
                        # LLMs can produce arbitrary keys. Do not trust
                        # the key alone; inspect both key and value.
                        # -------------------------------------------------

                        if _is_sensitive_memory(
                            memory_data
                        ):

                            logger.warning(
                                "[MemorySecurity] LLM extraction "
                                "blocked sensitive memory: %s",
                                _normalized_memory_key(
                                    memory_data.get("key")
                                )
                            )

                            continue

                        result = await self._store_extracted_memory(
                            memory_data
                        )

                        if result.get(
                            "success"
                        ):

                            stored_results.append(
                                result
                            )

                            if (
                                hasattr(
                                    self,
                                    "learning_engine"
                                )
                                and self.learning_engine
                            ):

                                await self.learning_engine.learn_from_memory(
                                    memory_data
                                )

                    if stored_results:

                        logger.info(
                            "[MemoryEngine] Intelligent memory stored %d memories.",
                            len(stored_results)
                        )

                        return {
                            "success": True,
                            "action": "intelligent_store",
                            "memories": stored_results
                        }

            except Exception:

                logger.exception(
                    "[MemoryEngine] Intelligent memory extraction failed."
                )

        return {
            "success": False
        }

    # =========================================================
    # MEMORY SCORING
    # =========================================================

    def _calculate_score(
        self,
        memory,
        semantic_score
    ):

        importance = memory.get(
            "importance",
            0.5
        )

        if isinstance(
            importance,
            str
        ):

            importance = {
                "low": 0.25,
                "medium": 0.5,
                "high": 0.75,
                "critical": 1.0,
            }.get(
                importance.lower(),
                0.5
            )

        try:
            importance = float(
                importance
            )

        except (
            TypeError,
            ValueError
        ):
            importance = 0.5

        confidence = memory.get(
            "confidence",
            1
        )

        accesses = memory.get(
            "access_count",
            0
        )

        capped_accesses = min(
            accesses,
            10
        )

        return (
            semantic_score
            +
            importance * 0.15
            +
            confidence * 5
            +
            capped_accesses * 0.08
        )

    # =========================================================
    # BROAD MEMORY CONSOLIDATION
    # =========================================================

    def _consolidate_broad_memories(
        self,
        memories
    ):
        """
        Consolidate semantically duplicate memories for broad
        personal-memory queries.
        """

        canonical_groups = {
            "postgraduate_degree": {
                "planned_postgraduate_degree",
                "intended_degree",
            },
            "postgraduate_location": {
                "planned_postgraduate_location",
                "study_destination",
            },
            "backup_country": {
                "backup_plan_country",
                "alternative_country",
            },
        }

        key_to_group = {}

        for canonical, keys in canonical_groups.items():

            for key in keys:
                key_to_group[key] = canonical

        consolidated = {}
        output = []

        for memory in memories:

            # Never allow sensitive memories into consolidation.
            if _is_sensitive_memory(
                memory
            ):
                continue

            key = memory.get(
                "key"
            )

            if not key:
                continue

            group = key_to_group.get(
                key
            )

            if group is None:

                if key not in consolidated:

                    consolidated[key] = memory
                    output.append(
                        memory
                    )

                continue

            existing = consolidated.get(
                group
            )

            if existing is None:

                consolidated[group] = memory
                output.append(
                    memory
                )

                continue

            existing_updated = str(
                existing.get(
                    "updated_at"
                ) or ""
            )

            current_updated = str(
                memory.get(
                    "updated_at"
                ) or ""
            )

            if current_updated > existing_updated:

                index = output.index(
                    existing
                )

                output[index] = memory

                consolidated[group] = memory

        return output

    # =========================================================
    # MEMORY RELEVANCE
    # =========================================================

    def _memory_relevance_score(
        self,
        memory: Dict[str, Any],
        query: str,
        conversation_state: Optional[
            Dict[str, Any]
        ] = None,
    ):

        # Sensitive records must never participate in ranking.
        if _is_sensitive_memory(
            memory
        ):
            return -999999.0

        text_parts = [
            memory.get(
                "key",
                ""
            ),
            memory.get(
                "value",
                ""
            ),
            memory.get(
                "summary",
                ""
            ),
            " ".join(
                memory.get(
                    "topics",
                    []
                ) or []
            ),
            " ".join(
                memory.get(
                    "entities",
                    []
                ) or []
            ),
            " ".join(
                memory.get(
                    "tags",
                    []
                ) or []
            ),
        ]

        memory_text = " ".join(
            str(part)
            for part in text_parts
            if part
        ).lower()

        query_text = str(
            query or ""
        ).lower()

        query_tokens = {
            token
            for token in re.findall(
                r"\b[a-z0-9_]+\b",
                query_text,
            )
            if len(token) > 2
        }

        memory_tokens = {
            token
            for token in re.findall(
                r"\b[a-z0-9_]+\b",
                memory_text,
            )
            if len(token) > 2
        }

        overlap = len(
            query_tokens
            &
            memory_tokens
        )

        score = overlap * 0.20

        if conversation_state:

            active_topic = str(
                conversation_state.get(
                    "active_topic",
                    ""
                )
            ).lower()

            active_subject = str(
                conversation_state.get(
                    "active_subject",
                    ""
                )
            ).lower()

            entities = conversation_state.get(
                "active_entities",
                [],
            )

            compared = conversation_state.get(
                "compared_entities",
                [],
            )

            current_entities = [
                str(entity).lower()
                for entity in (
                    entities + compared
                    if isinstance(
                        entities,
                        list
                    )
                    and isinstance(
                        compared,
                        list
                    )
                    else []
                )
            ]

            if (
                active_topic
                and active_topic in memory_text
            ):
                score += 0.40

            if (
                active_subject
                and active_subject in memory_text
            ):
                score += 0.35

            for entity in current_entities:

                if (
                    entity
                    and entity in memory_text
                ):
                    score += 0.25

        importance = memory.get(
            "importance",
            0.5,
        )

        confidence = memory.get(
            "confidence",
            0.5,
        )

        try:
            importance = float(
                importance
            )

        except (
            TypeError,
            ValueError
        ):
            importance = 0.5

        try:
            confidence = float(
                confidence
            )

        except (
            TypeError,
            ValueError
        ):
            confidence = 0.5

        score += importance * 0.10
        score += confidence * 0.10

        return score

    # =========================================================
    # MEMORY RETRIEVAL
    # =========================================================

    async def get_relevant_memories(
        self,
        query: str,
        limit: int = 50,
        conversation_state: Optional[
            Dict[str, Any]
        ] = None,
    ) -> list[dict]:

        if self.memory_col is None:
            return []

        try:

            lower = str(
                query or ""
            ).lower().strip()

            # =================================================
            # SENSITIVE QUERY PROTECTION
            # =================================================
            #
            # Do this BEFORE any MongoDB retrieval.
            #
            # This prevents queries such as:
            #
            #   "Give me my Aadhaar number"
            #   "Which number is linked to my Aadhaar?"
            #   "What is my PAN number?"
            #
            # from accidentally retrieving an unrelated memory.
            # =================================================

            if _contains_sensitive_query(
                lower
            ):

                logger.warning(
                    "[MemorySecurity] Sensitive-memory query blocked: %s",
                    lower
                )

                return []

            filter_query = None

            # ---------------------------------------------------------
            # BROAD PERSONAL MEMORY QUERY
            # ---------------------------------------------------------

            broad_memory_query = bool(
                re.search(
                    r"\b(?:what\s+do\s+you\s+remember\s+about\s+me|"
                    r"what\s+do\s+you\s+know\s+about\s+me|"
                    r"what\s+have\s+i\s+told\s+you\s+about\s+me|"
                    r"tell\s+me\s+(?:everything|all)\s+you\s+remember\s+about\s+me|"
                    r"what\s+do\s+you\s+remember\s+about\s+myself)\b",
                    lower,
                    re.IGNORECASE
                )
            )

            if re.search(
                r"\b(?:what(?:'s| is) my name|"
                r"who am i|"
                r"do you know my name|"
                r"tell me my name|"
                r"remember my name|"
                r"what's my name again|"
                r"say my name)\b",
                lower
            ):

                filter_query = {
                    "key": "name"
                }

            elif "preferred name" in lower:

                filter_query = {
                    "key": "preferred_name"
                }

            elif any(
                token in lower
                for token in (
                    "birthday",
                    "date of birth",
                    "dob",
                    "when was i born"
                )
            ):

                filter_query = {
                    "key": "birthday"
                }

            elif any(
                token in lower
                for token in (
                    "what do i study",
                    "what am i studying",
                    "field of study"
                )
            ):

                filter_query = {
                    "key": "field_of_study"
                }

            elif any(
                token in lower
                for token in (
                    "what do i like",
                    "things i like",
                    "my likes"
                )
            ):

                filter_query = {
                    "key": "user_likes"
                }

            if (
                filter_query is None
                and not broad_memory_query
            ):

                favorite_match = re.search(
                    r"(?:what(?:'s| is)|remember|recall)\s+"
                    r"(?:my\s+)?(?:favorite|favourite)\s+"
                    r"([a-zA-Z0-9\s]+)",
                    lower
                )

                if favorite_match:

                    subject = (
                        favorite_match.group(
                            1
                        ).strip()
                    )

                    filter_query = {
                        "key": self._normalize_key(
                            subject
                        )
                    }

            # =========================================================
            # BROAD PERSONAL MEMORY
            # =========================================================

            if broad_memory_query:

                cursor = self.memory_col.find(
                    {
                        "category": {
                            "$nin": [
                                "document",
                                "document_chunk"
                            ]
                        }
                    }
                )

                memories = await cursor.to_list(
                    length=limit
                )

                # Defense-in-depth against old sensitive records.
                memories = [
                    memory
                    for memory in memories
                    if not _is_sensitive_memory(
                        memory
                    )
                ]

                deduplicated = {}

                for memory in memories:

                    key = str(
                        memory.get(
                            "key",
                            ""
                        )
                    ).strip()

                    value = memory.get(
                        "value"
                    )

                    if (
                        not key
                        or value in (
                            None,
                            ""
                        )
                    ):
                        continue

                    existing = deduplicated.get(
                        key
                    )

                    if existing is None:

                        deduplicated[key] = memory

                        continue

                    existing_updated = (
                        existing.get(
                            "updated_at",
                            ""
                        )
                    )

                    current_updated = (
                        memory.get(
                            "updated_at",
                            ""
                        )
                    )

                    if (
                        current_updated
                        >
                        existing_updated
                    ):

                        deduplicated[key] = memory

                memories = list(
                    deduplicated.values()
                )

                def _importance_score(
                    memory
                ):

                    value = memory.get(
                        "importance",
                        0.5
                    )

                    if isinstance(
                        value,
                        (int, float)
                    ):
                        return float(
                            value
                        )

                    if isinstance(
                        value,
                        str
                    ):

                        normalized = (
                            value.strip().lower()
                        )

                        importance_map = {
                            "critical": 1.0,
                            "very_high": 0.9,
                            "high": 0.8,
                            "medium": 0.6,
                            "normal": 0.5,
                            "low": 0.3,
                            "very_low": 0.1,
                        }

                        if normalized in importance_map:

                            return importance_map[
                                normalized
                            ]

                        try:
                            return float(
                                normalized
                            )

                        except (
                            ValueError,
                            TypeError
                        ):
                            return 0.5

                    return 0.5

                memories.sort(
                    key=lambda m: (
                        _importance_score(m),
                        str(
                            m.get(
                                "updated_at",
                                ""
                            )
                        )
                    ),
                    reverse=True
                )

                now_iso = datetime.now(
                    timezone.utc
                ).isoformat()

                matched_ids = [
                    m["_id"]
                    for m in memories
                    if m.get("_id")
                ]

                if matched_ids:

                    await self.memory_col.update_many(
                        {
                            "_id": {
                                "$in": matched_ids
                            }
                        },
                        {
                            "$inc": {
                                "access_count": 1
                            },
                            "$set": {
                                "last_accessed": now_iso
                            }
                        }
                    )

                memories = (
                    self._consolidate_broad_memories(
                        memories
                    )
                )

                conversation_state = (
                    conversation_state
                    if isinstance(
                        conversation_state,
                        dict
                    )
                    else {}
                )

                memories.sort(
                    key=lambda memory:
                        self._memory_relevance_score(
                            memory,
                            query,
                            conversation_state,
                        ),
                    reverse=True,
                )

                memories = memories[:limit]

                logger.info(
                    "[MemoryEngine] Broad personal-memory "
                    "query retrieved %d consolidated memories.",
                    len(memories)
                )

                return memories

            # =========================================================
            # DIRECT KEY FILTER
            # =========================================================

            if filter_query is not None:

                cursor = self.memory_col.find(
                    filter_query
                ).limit(
                    limit
                )

                memories = await cursor.to_list(
                    length=limit
                )

                # Never return sensitive records.
                memories = [
                    memory
                    for memory in memories
                    if not _is_sensitive_memory(
                        memory
                    )
                ]

                if memories:

                    now_iso = datetime.now(
                        timezone.utc
                    ).isoformat()

                    matched_ids = [
                        m["_id"]
                        for m in memories
                        if m.get("_id")
                    ]

                    if matched_ids:

                        await self.memory_col.update_many(
                            {
                                "_id": {
                                    "$in": matched_ids
                                }
                            },
                            {
                                "$inc": {
                                    "access_count": 1
                                },
                                "$set": {
                                    "last_accessed": now_iso
                                }
                            }
                        )

                    filtered_memories = [
                        {
                            "key": m.get(
                                "key"
                            ),
                            "value": m.get(
                                "value"
                            ),
                            "category": m.get(
                                "category",
                                "general"
                            ),
                            "memory_type": m.get(
                                "memory_type",
                                "fact"
                            ),
                            "importance": m.get(
                                "importance",
                                0.5
                            ),
                            "confidence": m.get(
                                "confidence",
                                1.0
                            ),
                            "retrieval_score": 1.0,
                            "updated_at": m.get(
                                "updated_at"
                            ),
                            "_id": m.get(
                                "_id"
                            )
                        }
                        for m in memories
                        if (
                            m.get("key")
                            and m.get("value")
                            and not _is_sensitive_memory(
                                m
                            )
                        )
                    ]

                    conversation_state = (
                        conversation_state
                        if isinstance(
                            conversation_state,
                            dict
                        )
                        else {}
                    )

                    filtered_memories.sort(
                        key=lambda memory:
                            self._memory_relevance_score(
                                memory,
                                query,
                                conversation_state,
                            ),
                        reverse=True,
                    )

                    return filtered_memories[:limit]

            # =========================================================
            # GENERAL MEMORY RETRIEVAL
            # =========================================================

            cursor = self.memory_col.find(
                {
                    "category": {
                        "$nin": [
                            "document",
                            "document_chunk"
                        ]
                    }
                }
            )

            all_memories = await cursor.to_list(
                length=200
            )

            # Critical defense-in-depth filter.
            all_memories = [
                memory
                for memory in all_memories
                if not _is_sensitive_memory(
                    memory
                )
            ]

            if not all_memories:
                return []

            stop_words = {
                "what",
                "whats",
                "what's",
                "where",
                "when",
                "why",
                "how",
                "who",
                "which",
                "did",
                "does",
                "do",
                "am",
                "is",
                "are",
                "was",
                "were",
                "the",
                "a",
                "an",
                "my",
                "me",
                "i",
                "you",
                "your",
                "about",
                "know",
                "remember",
                "recall",
                "tell",
                "please"
            }

            query_words = {
                word
                for word in re.findall(
                    r"[a-zA-Z0-9]+",
                    lower
                )
                if (
                    len(word) > 1
                    and word not in stop_words
                )
            }

            aliases = {

                "plan": {
                    "plan",
                    "planned",
                    "planning",
                    "goal",
                    "future",
                    "postgraduate",
                    "masters",
                    "master",
                    "education",
                    "study"
                },

                "future": {
                    "future",
                    "plan",
                    "planned",
                    "planning",
                    "goal",
                    "career",
                    "postgraduate"
                },

                "btech": {
                    "btech",
                    "degree",
                    "undergraduate",
                    "postgraduate",
                    "masters",
                    "education"
                },

                "master": {
                    "master",
                    "masters",
                    "postgraduate",
                    "degree",
                    "study"
                },

                "masters": {
                    "master",
                    "masters",
                    "postgraduate",
                    "degree",
                    "study"
                },

                "study": {
                    "study",
                    "education",
                    "degree",
                    "university",
                    "college",
                    "postgraduate"
                },

                "italy": {
                    "italy",
                    "europe",
                    "european"
                },

                "education": {
                    "education",
                    "study",
                    "degree",
                    "university",
                    "college"
                },

                "career": {
                    "career",
                    "job",
                    "work",
                    "future",
                    "goal",
                    "plan"
                },

                "preference": {
                    "preference",
                    "prefer",
                    "favorite",
                    "favourite",
                    "love"
                }
            }

            expanded_query_words = set(
                query_words
            )

            for word in list(
                query_words
            ):

                if word in aliases:

                    expanded_query_words.update(
                        aliases[word]
                    )

            scored = []

            for memory in all_memories:

                # Additional safety check.
                if _is_sensitive_memory(
                    memory
                ):
                    continue

                key = str(
                    memory.get(
                        "key",
                        ""
                    )
                ).lower()

                value = str(
                    memory.get(
                        "value",
                        ""
                    )
                ).lower()

                category = str(
                    memory.get(
                        "category",
                        ""
                    )
                ).lower()

                memory_type = str(
                    memory.get(
                        "memory_type",
                        ""
                    )
                ).lower()

                searchable = (
                    key.replace(
                        "_",
                        " "
                    )
                    + " "
                    + value
                    + " "
                    + category
                    + " "
                    + memory_type
                )

                memory_words = set(
                    re.findall(
                        r"[a-zA-Z0-9]+",
                        searchable
                    )
                )

                semantic_score = 0.0

                direct_matches = (
                    query_words
                    &
                    memory_words
                )

                semantic_score += (
                    len(direct_matches)
                    * 3.0
                )

                semantic_matches = (
                    expanded_query_words
                    &
                    memory_words
                )

                semantic_score += (
                    len(semantic_matches)
                    * 1.5
                )

                key_words = set(
                    re.findall(
                        r"[a-zA-Z0-9]+",
                        key.replace(
                            "_",
                            " "
                        )
                    )
                )

                key_matches = (
                    expanded_query_words
                    &
                    key_words
                )

                semantic_score += (
                    len(key_matches)
                    * 2.5
                )

                score = self._calculate_score(
                    memory,
                    semantic_score
                )

                if semantic_score > 0:

                    scored.append(
                        (
                            score,
                            memory
                        )
                    )

            scored.sort(
                key=lambda item: item[0],
                reverse=True
            )

            # =========================================================
            # LLM MEMORY SELECTION
            # =========================================================

            if (
                self.llm_router is not None
                and hasattr(
                    self.llm_router,
                    "select_relevant_memories"
                )
            ):

                try:

                    candidates = [
                        {
                            "key": m.get(
                                "key"
                            ),
                            "value": m.get(
                                "value"
                            ),
                            "category": m.get(
                                "category",
                                "general"
                            )
                        }
                        for m in all_memories
                        if (
                            m.get("key")
                            and m.get("value")
                            and not _is_sensitive_memory(
                                m
                            )
                        )
                    ]

                    selected_keys = (
                        await self.llm_router.select_relevant_memories(
                            query,
                            candidates
                        )
                    )

                    if selected_keys:

                        selected_key_set = set(
                            selected_keys
                        )

                        llm_selected = [
                            m
                            for m in all_memories
                            if (
                                m.get("key")
                                in selected_key_set
                                and not _is_sensitive_memory(
                                    m
                                )
                            )
                        ]

                        existing_keys = {
                            m.get("key")
                            for _, m in scored
                        }

                        for memory in llm_selected:

                            if (
                                memory.get("key")
                                not in existing_keys
                            ):

                                scored.append(
                                    (
                                        self._calculate_score(
                                            memory,
                                            2.0
                                        ),
                                        memory
                                    )
                                )

                except Exception:

                    logger.exception(
                        "[MemoryEngine] Semantic memory "
                        "selection failed."
                    )

            if not scored:
                return []

            scored.sort(
                key=lambda item: item[0],
                reverse=True
            )

            final_memories = []
            seen_keys = set()

            for score, memory in scored:

                if _is_sensitive_memory(
                    memory
                ):
                    continue

                key = memory.get(
                    "key"
                )

                value = memory.get(
                    "value"
                )

                if (
                    not key
                    or not value
                ):
                    continue

                if key in seen_keys:
                    continue

                seen_keys.add(
                    key
                )

                final_memories.append(
                    {
                        "key": key,
                        "value": value,
                        "category": memory.get(
                            "category",
                            "general"
                        ),
                        "memory_type": memory.get(
                            "memory_type",
                            "fact"
                        ),
                        "importance": memory.get(
                            "importance",
                            0.5
                        ),
                        "confidence": memory.get(
                            "confidence",
                            1.0
                        ),
                        "retrieval_score": round(
                            float(score),
                            3
                        ),
                        "updated_at": memory.get(
                            "updated_at"
                        ),
                        # Preserve ID so access tracking works.
                        "_id": memory.get(
                            "_id"
                        )
                    }
                )

                if len(
                    final_memories
                ) >= limit:
                    break

            conversation_state = (
                conversation_state
                if isinstance(
                    conversation_state,
                    dict
                )
                else {}
            )

            final_memories.sort(
                key=lambda memory:
                    self._memory_relevance_score(
                        memory,
                        query,
                        conversation_state,
                    ),
                reverse=True,
            )

            final_memories = [
                memory
                for memory in final_memories
                if not _is_sensitive_memory(
                    memory
                )
            ]

            final_memories = final_memories[
                :limit
            ]

            # Record access for every memory actually used.
            for memory in final_memories:

                memory_id = memory.get(
                    "_id"
                )

                if not memory_id:
                    continue

                try:

                    await self.record_access(
                        memory_id
                    )

                except Exception:

                    logger.exception(
                        "[MemoryEngine] Failed to record "
                        "memory access: %s",
                        memory_id,
                    )

            logger.info(
                "[MemoryEngine] Retrieved %d relevant "
                "memories for query: %s",
                len(final_memories),
                query
            )

            return final_memories

        except Exception:

            logger.exception(
                "[Memory Retrieval Error]"
            )

            traceback.print_exc()

            return []

    # =========================================================
    # PUBLIC RETRIEVE
    # =========================================================

    async def retrieve(
        self,
        query: str,
        conversation_state: Optional[
            Dict[str, Any]
        ] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Public memory-retrieval entry point.
        """

        return await self.get_relevant_memories(
            query=query,
            limit=limit,
            conversation_state=conversation_state,
        )

    # =========================================================
    # DELETE MEMORY
    # =========================================================

    async def delete_memory(
        self,
        query_or_key: str
    ) -> bool:

        if self.memory_col is None:
            return False

        try:

            cleaned = query_or_key.lower().strip()

            cleaned = re.sub(
                r"^(forget|delete|clear|remove)\s+",
                "",
                cleaned,
                flags=re.IGNORECASE
            )

            cleaned = re.sub(
                r"\bmy\b",
                "",
                cleaned,
                flags=re.IGNORECASE
            ).strip()

            # Never process a sensitive deletion query as an
            # ordinary memory lookup.
            if _contains_sensitive_query(
                cleaned
            ):

                logger.warning(
                    "[MemorySecurity] Sensitive memory "
                    "operation blocked."
                )

                return False

            target_key = (
                self._normalize_key(
                    cleaned
                )
                if cleaned
                else ""
            )

            if target_key:

                # Do not delete sensitive records through
                # generalized matching.
                if _is_sensitive_memory_key(
                    target_key
                ):
                    return False

                res = await self.memory_col.delete_one(
                    {
                        "key": target_key
                    }
                )

                if res.deleted_count > 0:
                    return True

            res_direct = await self.memory_col.delete_one(
                {
                    "key": query_or_key
                }
            )

            if res_direct.deleted_count > 0:
                return True

            res_regex = await self.memory_col.delete_one(
                {
                    "key": {
                        "$regex": cleaned,
                        "$options": "i"
                    }
                }
            )

            if res_regex.deleted_count > 0:
                return True

            return False

        except Exception:

            logger.exception(
                "[MemoryEngine Delete Error]"
            )

            return False

    # =========================================================
    # ADDITIONAL ROUTER METHODS
    # =========================================================

    async def store_chat(
        self,
        chat
    ):
        return await self.process_and_store(
            chat
        )

    async def store_profile(
        self,
        profile
    ):

        if self.profile_col is None:
            return

        if not isinstance(
            profile,
            dict
        ):
            return

        # Filter sensitive profile fields before persistence.
        safe_profile = {}

        for key, value in profile.items():

            if _is_sensitive_memory_key(
                key
            ):
                logger.warning(
                    "[MemorySecurity] Blocked sensitive "
                    "profile field: %s",
                    key
                )
                continue

            if _contains_sensitive_value(
                value
            ):
                logger.warning(
                    "[MemorySecurity] Blocked sensitive "
                    "profile value."
                )
                continue

            safe_profile[key] = value

        if not safe_profile:
            return

        await self.profile_col.update_one(
            {},
            {
                "$set": safe_profile
            },
            upsert=True
        )

    async def update_memory(
        self,
        memory_id,
        data
    ):

        if self.memory_col is None:
            return False

        if not isinstance(
            data,
            dict
        ):
            return False

        # Never allow an update to introduce sensitive data.
        if _is_sensitive_memory(
            data
        ):

            logger.warning(
                "[MemorySecurity] Blocked sensitive "
                "memory update."
            )

            return False

        await self.memory_col.update_one(
            {
                "_id": memory_id
            },
            {
                "$set": data
            }
        )

        return True

    async def memory_exists(
        self,
        query
    ):

        if self.memory_col is None:
            return False

        # Sensitive information must not be checked through
        # the general memory existence API.
        if _contains_sensitive_query(
            query
        ):
            return False

        if _contains_sensitive_value(
            query
        ):
            return False

        memory = await self.memory_col.find_one(
            {
                "$or": [
                    {
                        "key": query
                    },
                    {
                        "value": query
                    }
                ]
            }
        )

        if _is_sensitive_memory(
            memory
        ):
            return False

        return memory is not None

    # =========================================================
    # MEMORY ACCESS TRACKING
    # =========================================================

    async def record_access(
        self,
        memory_id
    ):
        """
        Record that a memory was actually used.

        Sensitive records are not eligible for access tracking
        through this general method.
        """

        if (
            self.memory_col is None
            or memory_id is None
        ):
            return False

        try:

            memory = await self.memory_col.find_one(
                {
                    "_id": memory_id
                }
            )

            if _is_sensitive_memory(
                memory
            ):
                logger.warning(
                    "[MemorySecurity] Blocked access tracking "
                    "for sensitive memory."
                )
                return False

            await self.memory_col.update_one(
                {
                    "_id": memory_id
                },
                {
                    "$inc": {
                        "access_count": 1
                    },
                    "$set": {
                        "last_accessed": datetime.now(
                            timezone.utc
                        ).isoformat()
                    }
                }
            )

            return True

        except Exception:

            logger.exception(
                "[MemoryEngine] Failed to record memory access."
            )

            return False