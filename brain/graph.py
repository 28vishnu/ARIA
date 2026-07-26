class GraphManager:
    def __init__(self, mongo_repo):
        self.mongo = mongo_repo

    async def link(self, entity_a: str, relation: str, target: str):
        if self.mongo.graph:
            await self.mongo.graph.update_one(
                {"entity": entity_a.lower()},
                {"$addToSet": {"edges": {"relation": relation, "target": target.lower()}}},
                upsert=True
            )
