class ChromaRepository:
    def __init__(self, chroma_client):
        self.client = chroma_client
        self.docs = chroma_client.get_or_create_collection(name="aria_document_metadata") if chroma_client else None
        self.cache = chroma_client.get_or_create_collection(name="aria_brain_cache") if chroma_client else None
      
