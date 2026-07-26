import chromadb

class KnowledgeGraph:
    def __init__(self, chroma_client=None):
        self.client = chroma_client if chroma_client else chromadb.PersistentClient(path="./aria_vectors")
        self.graph_col = self.client.get_or_create_collection(name="brain_knowledge_graph")

    def add_relation(self, entity: str, relation: str, target: str, category: str = "general"):
        """Stores a directional relationship triple: Entity -> Relation -> Target."""
        try:
            doc_id = f"rel_{entity.lower()}_{relation.lower()}_{target.lower()}"
            document = f"{entity} {relation} {target}"
            metadata = {
                "entity": entity.lower(),
                "relation": relation.lower(),
                "target": target.lower(),
                "category": category.lower()
            }
            self.graph_col.upsert(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata]
            )
            print(f"[Knowledge Graph]: Linked '{entity}' --[{relation}]--> '{target}'")
        except Exception as e:
            print(f"[Graph Add Error]: {e}")

    def query_relations(self, entity: str) -> list[dict]:
        """Retrieves all connected nodes for a given entity."""
        try:
            results = self.graph_col.get(
                where={"entity": entity.lower()}
            )
            if results and results.get("metadatas"):
                return results["metadatas"]
        except Exception as e:
            print(f"[Graph Query Error]: {e}")
        return []
