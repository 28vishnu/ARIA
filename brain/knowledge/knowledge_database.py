import logging
from typing import List, Dict, Optional
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger("aria")


class KnowledgeDatabase:

    def __init__(
        self,
        mongo_collection=None,
        vector_db=None,
    ):

        self.collection = mongo_collection
        self.vector_db = vector_db

    ############################################################
    # Store Knowledge
    ############################################################

    async def store(
        self,
        title,
        content,
        source="conversation",
        metadata=None,
    ):

        record = {

            "_id": str(uuid4()),

            "title": title,

            "content": content,

            "summary": content[:250],

            "source": source,

            "metadata": metadata or {},

            "importance": 50,

            "confidence": 1.0,

            "entities": [],

            "relationships": [],

            "topics": [],

            "created_at": datetime.utcnow(),

            "updated_at": datetime.utcnow(),

            "access_count": 0,

        }

        if self.collection:

            await self.collection.update_one(
                {
                    "title": title,
                    "content": content,
                },
                {
                    "$set": record,
                },
                upsert=True,
            )

        logger.info(
            "[KnowledgeDB] Stored knowledge: %s",
            title,
        )

        return record

    ############################################################
    # Search
    ############################################################

    async def search(
        self,
        query,
        limit=5,
    ):

        if self.collection is None:
            return []

        cursor = self.collection.find(
            {
                "$text": {
                    "$search": query
                }
            }
        ).limit(limit)

        return await cursor.to_list(limit)

    ############################################################
    # Semantic Search
    ############################################################

    async def semantic_search(
        self,
        embedding,
        limit=5,
    ):

        if self.vector_db is None:
            return []

        return self.vector_db.query(
            query_embeddings=[embedding],
            n_results=limit,
        )

    ############################################################
    # Exists
    ############################################################

    async def exists(
        self,
        text,
    ):

        if self.collection is None:
            return False

        doc = await self.collection.find_one(
            {
                "content": text
            }
        )

        return doc is not None

    ############################################################
    # Update
    ############################################################

    async def update(
        self,
        knowledge_id,
        data,
    ):

        if self.collection is None:
            return

        await self.collection.update_one(
            {
                "_id": knowledge_id
            },
            {
                "$set": data
            }
        )

    ############################################################
    # Increment Access
    ############################################################

    async def increment_access(
        self,
        knowledge_id,
    ):

        if self.collection is None:
            return

        await self.collection.update_one(
            {
                "_id": knowledge_id
            },
            {
                "$inc": {
                    "access_count": 1
                }
            }
        )

    ############################################################
    # Search by Topic
    ############################################################

    async def search_by_topic(
        self,
        topic,
    ):

        if self.collection is None:
            return []

        cursor = self.collection.find(
            {
                "topics": topic
            }
        )

        return await cursor.to_list(100)

    ############################################################
    # Search by Entity
    ############################################################

    async def search_by_entity(
        self,
        entity,
    ):

        if self.collection is None:
            return []

        cursor = self.collection.find(
            {
                "entities": entity
            }
        )

        return await cursor.to_list(100)

    ############################################################
    # Related Knowledge
    ############################################################

    async def related_knowledge(
        self,
        entity,
    ):

        if self.collection is None:
            return []

        cursor = self.collection.find(
            {
                "$or": [
                    {
                        "entities": entity
                    },
                    {
                        "topics": entity
                    }
                ]
            }
        )

        return await cursor.to_list(20)

    ############################################################
    # Store Fact
    ############################################################

    async def store_fact(
        self,
        subject,
        fact,
    ):

        return await self.store(
            title=subject,
            content=fact,
            source="fact",
        )
