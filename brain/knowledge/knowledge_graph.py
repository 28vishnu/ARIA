import logging
from collections import defaultdict, deque
from typing import Dict, List, Set
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger("aria")


VALID_RELATIONS = {

    "friend",

    "studies_at",

    "works_at",

    "faculty",

    "owns",

    "uses",

    "member_of",

    "located_in",

    "capital",

    "depends_on",

}


class KnowledgeGraph:
    """
    ARIA's structured knowledge graph.

    Stores relationships such as:

    Saketh --studies_at--> GVP
    Japan --capital--> Tokyo
    Monday --class--> CN
    CN --faculty--> Arun Kumar

    Retrieval is deterministic and requires no LLM.
    """

    def __init__(
        self,
        mongodb=None,
        vector_db=None,
    ):

        self.nodes = {}

        self.edges = defaultdict(list)

        self.reverse_edges = defaultdict(list)

        self.topic_clusters = defaultdict(set)

        self.statistics = {

            "nodes": 0,

            "edges": 0,

            "facts": 0,

        }

        self.mongodb = mongodb

        self.collection = None

        if mongodb:
            self.collection = mongodb["knowledge_graph"]

        self.vector_db = vector_db

    ############################################################

    async def save_entity(
        self,
        entity,
    ):
        if self.collection is None:
            return

        await self.collection.update_one(
            {
                "id": entity.get("id")
            },
            {
                "$set": entity
            },
            upsert=True,
        )

    ############################################################

    async def add_entity(
        self,
        name,
        entity_type="general",
    ):

        if not name:
            return

        if name in self.nodes:

            self.nodes[name]["times_seen"] += 1
            self.nodes[name]["updated_at"] = datetime.utcnow()

            await self.save_entity(
                self.nodes[name]
            )

            return

        self.nodes[name] = {

            "id": str(uuid4()),

            "name": name,

            "type": entity_type,

            "created_at": datetime.utcnow(),

            "updated_at": datetime.utcnow(),

            "times_seen": 1,

            "aliases": set(),

            "topics": set(),

        }

        self.statistics["nodes"] += 1

        await self.save_entity(
            self.nodes[name]
        )

    ############################################################

    async def save_fact(
        self,
        edge,
    ):
        if self.collection is None:
            return

        await self.collection.update_one(
            {
                "subject": edge["subject"],
                "relation": edge["relation"],
                "object": edge["object"],
            },
            {
                "$set": edge
            },
            upsert=True,
        )

    ############################################################

    async def add_fact(
        self,
        subject: str,
        relation: str,
        obj: str,
    ):

        if not subject or not relation or not obj:
            return

        subject = subject.strip()
        relation = relation.strip().lower()
        obj = obj.strip()

        if relation not in VALID_RELATIONS:

            relation = "related_to"

        await self.add_entity(subject)
        await self.add_entity(obj)

        edge = {

            "subject": subject,

            "relation": relation,

            "object": obj,

            "confidence": 0.60,

            "importance": 50,

            "source": "knowledge",

            "created_at": datetime.utcnow(),

            "history": [],

            "updated_at": datetime.utcnow(),

            "updated_by": "system",

        }

        self.edges[subject].append(edge)

        self.reverse_edges[obj].append(edge)

        await self.save_fact(edge)

        reverse = {

            "subject": obj,

            "relation": f"reverse_{relation}",

            "object": subject,

            "confidence": 0.60,

            "importance": 50,

            "source": "knowledge",

            "created_at": datetime.utcnow(),

            "history": [],

            "updated_at": datetime.utcnow(),

            "updated_by": "system",

        }

        self.edges[obj].append(reverse)

        await self.save_fact(reverse)

        self.statistics["edges"] += 2
        self.statistics["facts"] += 1

        logger.info(
            "[KnowledgeGraph] %s --%s--> %s",
            subject,
            relation,
            obj,
        )

    ############################################################

    async def increase_confidence(
        self,
        subject,
        relation,
        obj,
    ):
        for edge in self.edges.get(subject, []):
            if edge["relation"] == relation and edge["object"] == obj:
                edge["confidence"] = min(1.0, edge["confidence"] + 0.05)
                edge["updated_at"] = datetime.utcnow()
                edge["history"].append({
                    "action": "increase_confidence",
                    "value": edge["confidence"],
                    "timestamp": datetime.utcnow(),
                })
                await self.save_fact(edge)

    ############################################################

    async def decrease_confidence(
        self,
        subject,
        relation,
        obj,
    ):
        for edge in self.edges.get(subject, []):
            if edge["relation"] == relation and edge["object"] == obj:
                edge["confidence"] = max(0.0, edge["confidence"] - 0.10)
                edge["updated_at"] = datetime.utcnow()
                edge["history"].append({
                    "action": "decrease_confidence",
                    "value": edge["confidence"],
                    "timestamp": datetime.utcnow(),
                })
                await self.save_fact(edge)

    ############################################################

    async def load_graph(
        self,
    ):
        if self.collection is None:
            return

        cursor = self.collection.find({})
        async for doc in cursor:
            if "name" in doc:
                # Node entity
                self.nodes[doc["name"]] = doc
                if "aliases" in doc and isinstance(doc["aliases"], list):
                    doc["aliases"] = set(doc["aliases"])
                if "topics" in doc and isinstance(doc["topics"], list):
                    doc["topics"] = set(doc["topics"])
                self.statistics["nodes"] += 1
            elif "subject" in doc and "relation" in doc and "object" in doc:
                # Edge fact
                edge = doc
                self.edges[edge["subject"]].append(edge)
                self.reverse_edges[edge["object"]].append(edge)
                self.statistics["edges"] += 1
                if not edge["relation"].startswith("reverse_"):
                    self.statistics["facts"] += 1

    ############################################################

    async def merge_entities(
        self,
        primary,
        duplicate,
    ):

        if duplicate not in self.nodes:
            return

        self.nodes[primary]["aliases"].add(duplicate)

        del self.nodes[duplicate]
        self.statistics["nodes"] = max(0, self.statistics["nodes"] - 1)

    ############################################################

    async def find_path(
        self,
        start,
        end,
    ):
        if start not in self.nodes or end not in self.nodes:
            return []

        if start == end:
            return [start]

        queue = deque([[start]])
        visited = {start}

        while queue:
            path = queue.popleft()
            current = path[-1]

            if current == end:
                return path

            for edge in self.edges.get(current, []):
                neighbor = edge["object"]
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = list(path)
                    new_path.append(neighbor)
                    queue.append(new_path)

        return []

    ############################################################

    async def add_topic(
        self,
        topic,
        entity,
    ):

        self.topic_clusters[topic].add(entity)

    ############################################################

    async def snapshot(
        self,
    ):
        return {

            "nodes": self.nodes,

            "edges": self.edges,

            "topics": self.topic_clusters,

            "statistics": self.statistics,

        }

    ############################################################

    async def detect_duplicates(
        self,
    ):
        pass

    ############################################################

    async def rebuild(
        self,
    ):
        await self.clear()

        await self.load_graph()

    ############################################################

    async def summary(self):

        all_confidences = []
        entity_types = defaultdict(int)

        for node in self.nodes.values():
            entity_types[node.get("type", "general")] += 1

        for edge_list in self.edges.values():
            for edge in edge_list:
                all_confidences.append(edge.get("confidence", 1.0))

        avg_confidence = (
            sum(all_confidences) / len(all_confidences)
            if all_confidences
            else 1.0
        )

        return {

            "nodes": len(self.nodes),

            "edges": sum(
                len(v)
                for v in self.edges.values()
            ),

            "topics": len(
                self.topic_clusters
            ),

            "confidence_average": avg_confidence,

            "entity_types": dict(entity_types),

            "facts": self.statistics["facts"],

        }

    ############################################################

    async def related_entities(
        self,
        entity,
    ):

        return [

            edge["object"]

            for edge in self.edges.get(
                entity,
                []
            )

        ]

    ############################################################

    async def search(
        self,
        query: str,
    ):

        query = query.lower()

        results = []

        # Search nodes metadata
        for name, data in self.nodes.items():
            if query in name.lower() or any(query in alias.lower() for alias in data["aliases"]):
                results.append({
                    "type": "entity",
                    "name": name,
                    "metadata": data
                })

        # Search edges
        for subject, edge_list in self.edges.items():
            for edge in edge_list:
                if (
                    query in edge["subject"].lower()
                    or query in edge["relation"].lower()
                    or query in edge["object"].lower()
                ):
                    results.append(
                        {
                            "type": "fact",
                            "subject": edge["subject"],
                            "relation": edge["relation"],
                            "object": edge["object"],
                        }
                    )

        return results

    ############################################################

    async def related(
        self,
        subject,
        relation=None,
    ):

        if subject not in self.edges:
            return []

        if relation:

            return [
                edge["object"]
                for edge in self.edges[subject]
                if edge["relation"] == relation
            ]

        output = []

        for edge in self.edges[subject]:
            output.append(
                {
                    "relation": edge["relation"],
                    "object": edge["object"],
                }
            )

        return output

    ############################################################

    async def has_fact(
        self,
        subject,
        relation,
        obj,
    ):

        for edge in self.edges.get(subject, []):
            if edge["relation"] == relation and edge["object"] == obj:
                return True

        return False

    ############################################################

    async def delete_fact(
        self,
        subject,
        relation,
        obj,
    ):

        try:

            original_len = len(self.edges[subject])
            self.edges[subject] = [
                edge for edge in self.edges[subject]
                if not (edge["relation"] == relation and edge["object"] == obj)
            ]

            self.reverse_edges[obj] = [
                edge for edge in self.reverse_edges[obj]
                if not (edge["relation"] == relation and edge["subject"] == subject)
            ]

            if len(self.edges[subject]) < original_len:
                self.statistics["edges"] = max(0, self.statistics["edges"] - 2)
                self.statistics["facts"] = max(0, self.statistics["facts"] - 1)
                return True

            return False

        except Exception:

            return False

    ############################################################

    async def all_facts(self):

        facts = []

        for subject, edge_list in self.edges.items():
            for edge in edge_list:
                # Avoid returning reverse edges in all_facts if preferred, or return main facts
                if not edge["relation"].startswith("reverse_"):
                    facts.append(
                        {
                            "subject": edge["subject"],
                            "relation": edge["relation"],
                            "object": edge["object"],
                        }
                    )

        return facts

    ############################################################

    async def clear(self):

        self.nodes.clear()

        self.edges.clear()

        self.reverse_edges.clear()

        self.topic_clusters.clear()

        self.statistics = {

            "nodes": 0,

            "edges": 0,

            "facts": 0,

        }

        logger.info(
            "[KnowledgeGraph] Cleared."
        )
