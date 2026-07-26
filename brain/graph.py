class GraphManager:
    def __init__(self, mongo_db):
        self.graph_col = mongo_db["knowledge_graph"] if mongo_db is not None else None

    async def link_concepts(self, entity_a: str, relation: str, entity_b: str, category: str = "general"):
        """Persistently links concepts in the MongoDB knowledge graph."""
        if not self.graph_col: return
        key = entity_a.lower().strip()
        target = entity_b.lower().strip()
        
        edge = {"relation": relation, "target": target, "category": category}
        await self.graph_col.update_one(
            {"entity": key},
            {"$addToSet": {"edges": edge}},
            upsert=True
        )

    async def get_connections(self, entity: str) -> list[dict]:
        """Retrieves persistent graph edges for an entity."""
        if not self.graph_col: return []
        doc = await self.graph_col.find_one({"entity": entity.lower().strip()})
        return doc.get("edges", []) if doc else []
