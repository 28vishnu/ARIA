class MongoRepository:
    def __init__(self, db):
        self.db = db
        self.docs = db["document_metadata"] if db is not None else None
        self.graph = db["knowledge_graph"] if db is not None else None
        self.profile = db["user_profile"] if db is not None else None
      
