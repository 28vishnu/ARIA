import logging
from typing import List, Dict, Optional
from uuid import uuid4

logger = logging.getLogger("aria")


class KnowledgeDatabase:

    def __init__(self):
        self.knowledge = {}

    ############################################################
    # Store Knowledge
    ############################################################

    async def store(
        self,
        title: str,
        content: str,
        source: str = "conversation",
        metadata: Optional[Dict] = None,
    ):

        knowledge_id = str(uuid4())

        self.knowledge[knowledge_id] = {

            "id": knowledge_id,

            "title": title,

            "content": content,

            "source": source,

            "metadata": metadata or {},

        }

        logger.info(
            "[KnowledgeDB] Stored knowledge: %s",
            title,
        )

        return knowledge_id

    ############################################################
    # Search
    ############################################################

    async def search(
        self,
        query: str,
        limit: int = 5,
    ):

        query = query.lower()

        matches = []

        for item in self.knowledge.values():

            text = (
                item["title"]
                + " "
                + item["content"]
            ).lower()

            if query in text:

                matches.append(item)

        matches = matches[:limit]

        if not matches:
            return None

        return "\n\n".join(
            x["content"]
            for x in matches
        )

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

    ############################################################
    # Get All
    ############################################################

    async def get_all(self):

        return list(
            self.knowledge.values()
        )

    ############################################################
    # Delete
    ############################################################

    async def delete(
        self,
        knowledge_id,
    ):

        if knowledge_id in self.knowledge:

            del self.knowledge[
                knowledge_id
            ]

            return True

        return False

    ############################################################
    # Clear
    ############################################################

    async def clear(self):

        self.knowledge.clear()

        logger.info(
            "[KnowledgeDB] Cleared."
        )