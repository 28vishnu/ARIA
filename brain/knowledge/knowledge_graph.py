import logging
from collections import defaultdict, deque
from typing import Dict, List, Set
from datetime import datetime

logger = logging.getLogger("aria")


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

    def __init__(self):

        self.nodes = {}

        self.edges = defaultdict(list)

        self.reverse_edges = defaultdict(list)

        self.topic_clusters = defaultdict(set)

        self.statistics = {

            "nodes": 0,

            "edges": 0,

            "facts": 0,

        }

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

            return

        self.nodes[name] = {

            "name": name,

            "type": entity_type,

            "created_at": datetime.utcnow(),

            "updated_at": datetime.utcnow(),

            "times_seen": 1,

            "aliases": set(),

            "topics": set(),

        }

        self.statistics["nodes"] += 1

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

        await self.add_entity(subject)
        await self.add_entity(obj)

        edge = {

            "subject": subject,

            "relation": relation,

            "object": obj,

            "confidence": 1.0,

            "importance": 50,

            "source": "knowledge",

            "created_at": datetime.utcnow(),

        }

        self.edges[subject].append(edge)

        self.reverse_edges[obj].append(edge)

        reverse = {

            "subject": obj,

            "relation": f"reverse_{relation}",

            "object": subject,

            "confidence": 1.0,

            "importance": 50,

            "source": "knowledge",

            "created_at": datetime.utcnow(),

        }

        self.edges[obj].append(reverse)

        self.statistics["edges"] += 2
        self.statistics["facts"] += 1

        logger.info(
            "[KnowledgeGraph] %s --%s--> %s",
            subject,
            relation,
            obj,
        )

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

    async def summary(self):

        return {

            "nodes": len(self.nodes),

            "edges": sum(
                len(v)
                for v in self.edges.values()
            ),

            "topics": len(
                self.topic_clusters
            ),

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
