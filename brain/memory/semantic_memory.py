from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
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

    def __init__(self, storage_path="storage"):

        self.nodes = {}

        self.edges = []

        self.graph = defaultdict(list)

        self.semantic_graph_path = (
            Path(storage_path)
            / "semantic_graph.json"
        )

    def save_semantic_graph(self):

        data = {
            "nodes": {},
            "edges": [],
        }

        for node_id, node in self.nodes.items():

            data["nodes"][node_id] = {
                "node_type": node.node_type,
                "value": node.value,
                "metadata": node.metadata,
            }

        for edge in self.edges:

            data["edges"].append({
                "source": edge.source,
                "relation": edge.relation,
                "target": edge.target,
                "created_at": edge.created_at.isoformat(),
            })

        self.semantic_graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(
            self.semantic_graph_path,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                data,
                f,
                indent=2,
            )

        logger.info(
            "[SemanticMemory] Graph persisted successfully."
        )

    def load_semantic_graph(self):

        if not self.semantic_graph_path.exists():

            return None

        with open(
            self.semantic_graph_path,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)
            logger.info(
                "[SemanticMemory] Graph restored."
            )
            return data

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
