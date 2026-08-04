from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
import logging

logger = logging.getLogger("aria")


@dataclass
class SemanticNode:
    id: str
    node_type: str
    value: str
    metadata: dict = field(default_factory=dict)


@dataclass
class SemanticEdge:
    source: str
    relation: str
    target: str
    created_at: datetime = field(default_factory=datetime.utcnow)


class SemanticMemory:

    def __init__(self):

        self.nodes = {}

        self.edges = []

        self.graph = defaultdict(list)

    def add_node(
        self,
        node_id,
        node_type,
        value,
        metadata=None,
    ):

        if node_id in self.nodes:
            return self.nodes[node_id]

        node = SemanticNode(
            id=node_id,
            node_type=node_type,
            value=value,
            metadata=metadata or {},
        )

        self.nodes[node_id] = node

        logger.info(
            "[SemanticMemory] Added node: %s",
            node_id,
        )

        return node

    def add_relation(
        self,
        source,
        relation,
        target,
    ):

        edge = SemanticEdge(
            source=source,
            relation=relation,
            target=target,
        )

        self.edges.append(edge)

        self.graph[source].append(edge)

        logger.info(
            "[SemanticMemory] %s --%s--> %s",
            source,
            relation,
            target,
        )

    def related(self, node_id):

        return self.graph.get(node_id, [])

    def summary(self):

        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
        }