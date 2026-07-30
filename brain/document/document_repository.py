import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("aria")


class DocumentRepository:
    """
    Persistent catalogue for documents uploaded to ARIA.

    MongoDB stores document metadata and references.
    The actual document content/vector embeddings remain handled
    by DocumentIntelligence/ChromaDB.

    For Telegram uploads, telegram_file_id allows ARIA to send
    the original file back to the user later without storing
    the complete PDF binary in MongoDB.
    """

    def __init__(
        self,
        db: AsyncIOMotorDatabase
    ):
        self.db = db
        self.collection = db["documents"]

    # =========================================================
    # SAVE / UPDATE DOCUMENT
    # =========================================================

    async def save_document(
        self,
        user_id: str,
        filename: str,
        telegram_file_id: Optional[str] = None,
        telegram_file_unique_id: Optional[str] = None,
        mime_type: Optional[str] = None,
        size: Optional[int] = None,
        summary: Optional[str] = None,
        text_preview: Optional[str] = None,
        vector_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Save or update a document record.

        Documents are matched primarily using:
            user_id + telegram_file_unique_id

        If Telegram's unique ID is unavailable, ARIA falls back to:
            user_id + filename
        """

        now = datetime.now(timezone.utc)

        user_id = str(user_id)
        filename = str(filename).strip()

        if not user_id:
            raise ValueError("user_id is required.")

        if not filename:
            raise ValueError("filename is required.")

        document_data = {
            "user_id": user_id,
            "filename": filename,
            "filename_normalized": self._normalize_filename(filename),

            "telegram_file_id": telegram_file_id,
            "telegram_file_unique_id": telegram_file_unique_id,

            "mime_type": mime_type,
            "size": size,

            "summary": summary,
            "text_preview": text_preview,

            "vector_ids": vector_ids or [],
            "metadata": metadata or {},

            "updated_at": now,
        }

        # -----------------------------------------------------
        # Determine unique lookup
        # -----------------------------------------------------

        if telegram_file_unique_id:

            lookup = {
                "user_id": user_id,
                "telegram_file_unique_id": telegram_file_unique_id,
            }

        else:

            lookup = {
                "user_id": user_id,
                "filename_normalized": self._normalize_filename(
                    filename
                ),
            }

        try:

            result = await self.collection.update_one(
                lookup,
                {
                    "$set": document_data,
                    "$setOnInsert": {
                        "created_at": now,
                    },
                },
                upsert=True,
            )

            document = await self.collection.find_one(
                lookup
            )

            if not document:
                raise RuntimeError(
                    "Document was saved but could not be retrieved."
                )

            logger.info(
                "[DocumentRepository] Saved document '%s' for user %s.",
                filename,
                user_id,
            )

            return self._serialize_document(document)

        except Exception:

            logger.exception(
                "[DocumentRepository] Failed to save document '%s'.",
                filename,
            )

            raise

    # =========================================================
    # FIND BY FILENAME
    # =========================================================

    async def find_by_filename(
        self,
        user_id: str,
        filename: str,
    ) -> Optional[Dict[str, Any]]:

        normalized = self._normalize_filename(
            filename
        )

        document = await self.collection.find_one(
            {
                "user_id": str(user_id),
                "filename_normalized": normalized,
            }
        )

        if not document:
            return None

        return self._serialize_document(document)

    # =========================================================
    # SEARCH DOCUMENTS
    # =========================================================

    async def search_documents(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search a user's documents by filename.

        Example:

            "resume"
                -> Saketh_Resume.pdf

            "project"
                -> final_year_project.pdf
        """

        user_id = str(user_id)
        search_text = str(query or "").strip()

        if not search_text:
            return await self.list_documents(
                user_id=user_id,
                limit=limit,
            )

        escaped = self._escape_regex(
            search_text
        )

        cursor = (
            self.collection
            .find(
                {
                    "user_id": user_id,
                    "$or": [
                        {
                            "filename": {
                                "$regex": escaped,
                                "$options": "i",
                            }
                        },
                        {
                            "filename_normalized": {
                                "$regex": escaped,
                                "$options": "i",
                            }
                        },
                    ],
                }
            )
            .sort("updated_at", -1)
            .limit(limit)
        )

        documents = await cursor.to_list(
            length=limit
        )

        return [
            self._serialize_document(document)
            for document in documents
        ]

    # =========================================================
    # LIST DOCUMENTS
    # =========================================================

    async def list_documents(
        self,
        user_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:

        cursor = (
            self.collection
            .find(
                {
                    "user_id": str(user_id)
                }
            )
            .sort("updated_at", -1)
            .limit(limit)
        )

        documents = await cursor.to_list(
            length=limit
        )

        return [
            self._serialize_document(document)
            for document in documents
        ]

    # =========================================================
    # GET DOCUMENT
    # =========================================================

    async def get_document(
        self,
        document_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:

        try:

            from bson import ObjectId

            lookup = {
                "_id": ObjectId(document_id)
            }

            if user_id is not None:
                lookup["user_id"] = str(user_id)

            document = await self.collection.find_one(
                lookup
            )

            if not document:
                return None

            return self._serialize_document(
                document
            )

        except Exception:

            logger.warning(
                "[DocumentRepository] Invalid document ID: %s",
                document_id,
            )

            return None

    # =========================================================
    # FIND BY TELEGRAM UNIQUE ID
    # =========================================================

    async def find_by_telegram_file(
        self,
        user_id: str,
        telegram_file_unique_id: str,
    ) -> Optional[Dict[str, Any]]:

        document = await self.collection.find_one(
            {
                "user_id": str(user_id),
                "telegram_file_unique_id": str(
                    telegram_file_unique_id
                ),
            }
        )

        if not document:
            return None

        return self._serialize_document(
            document
        )

    # =========================================================
    # GET MOST RECENT DOCUMENT
    # =========================================================

    async def get_latest_document(
        self,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:

        document = await self.collection.find_one(
            {
                "user_id": str(user_id)
            },
            sort=[
                (
                    "updated_at",
                    -1
                )
            ],
        )

        if not document:
            return None

        return self._serialize_document(
            document
        )

    # =========================================================
    # UPDATE SUMMARY
    # =========================================================

    async def update_summary(
        self,
        document_id: str,
        summary: str,
    ) -> bool:

        try:

            from bson import ObjectId

            result = await self.collection.update_one(
                {
                    "_id": ObjectId(document_id)
                },
                {
                    "$set": {
                        "summary": str(summary),
                        "updated_at": datetime.now(
                            timezone.utc
                        ),
                    }
                },
            )

            return result.matched_count > 0

        except Exception:

            logger.exception(
                "[DocumentRepository] Failed to update summary."
            )

            return False

    # =========================================================
    # UPDATE VECTOR IDS
    # =========================================================

    async def update_vector_ids(
        self,
        document_id: str,
        vector_ids: List[str],
    ) -> bool:

        try:

            from bson import ObjectId

            result = await self.collection.update_one(
                {
                    "_id": ObjectId(document_id)
                },
                {
                    "$set": {
                        "vector_ids": vector_ids,
                        "updated_at": datetime.now(
                            timezone.utc
                        ),
                    }
                },
            )

            return result.matched_count > 0

        except Exception:

            logger.exception(
                "[DocumentRepository] Failed to update vector IDs."
            )

            return False

    # =========================================================
    # DELETE DOCUMENT
    # =========================================================

    async def delete_document(
        self,
        document_id: str,
        user_id: Optional[str] = None,
    ) -> bool:

        try:

            from bson import ObjectId

            lookup = {
                "_id": ObjectId(document_id)
            }

            if user_id is not None:
                lookup["user_id"] = str(user_id)

            result = await self.collection.delete_one(
                lookup
            )

            if result.deleted_count:

                logger.info(
                    "[DocumentRepository] Deleted document %s.",
                    document_id,
                )

                return True

            return False

        except Exception:

            logger.exception(
                "[DocumentRepository] Failed to delete document."
            )

            return False

    # =========================================================
    # DELETE ALL USER DOCUMENTS
    # =========================================================

    async def delete_all_user_documents(
        self,
        user_id: str,
    ) -> int:

        result = await self.collection.delete_many(
            {
                "user_id": str(user_id)
            }
        )

        logger.info(
            "[DocumentRepository] Deleted %d documents for user %s.",
            result.deleted_count,
            user_id,
        )

        return result.deleted_count

    # =========================================================
    # COUNT DOCUMENTS
    # =========================================================

    async def count_documents(
        self,
        user_id: str,
    ) -> int:

        return await self.collection.count_documents(
            {
                "user_id": str(user_id)
            }
        )

    # =========================================================
    # HELPERS
    # =========================================================

    def _normalize_filename(
        self,
        filename: str,
    ) -> str:

        filename = str(filename).lower().strip()

        # Remove PDF extension for easier matching.
        if filename.endswith(".pdf"):
            filename = filename[:-4]

        # Convert separators into spaces.
        filename = filename.replace(
            "_",
            " "
        )

        filename = filename.replace(
            "-",
            " "
        )

        # Collapse whitespace.
        filename = re.sub(
            r"\s+",
            " ",
            filename
        )

        return filename.strip()

    def _escape_regex(
        self,
        text: str,
    ) -> str:

        return re.escape(
            str(text)
        )

    def _serialize_document(
        self,
        document: Dict[str, Any],
    ) -> Dict[str, Any]:

        result = dict(document)

        if "_id" in result:
            result["document_id"] = str(
                result.pop("_id")
            )

        for field in (
            "created_at",
            "updated_at",
        ):

            value = result.get(field)

            if isinstance(value, datetime):
                result[field] = value.isoformat()

        return result