import logging

logger = logging.getLogger("aria")


class DocumentPipeline:

    def __init__(
        self,
        document_manager,
        chunker,
        concept_extractor,
        document_memory,
        semantic_search,
    ):

        self.document_manager = document_manager
        self.chunker = chunker
        self.concept_extractor = concept_extractor
        self.document_memory = document_memory
        self.semantic_search = semantic_search

    async def process(self, file_path):

        logger.info(
            "[DocumentPipeline] Processing %s",
            file_path,
        )

        # Step 1
        document = await self.document_manager.parse(file_path)

        # Step 2
        chunks = self.chunker.chunk_document(document)

        # Step 3
        concepts = self.concept_extractor.extract(document)

        # Step 4
        self.document_memory.store_document(
            document,
            concepts,
        )

        document.indexed = True

        logger.info(
            "[DocumentPipeline] Finished %s",
            document.name,
        )

        return {
            "document": document,
            "chunks": chunks,
            "concepts": concepts,
        }

    def search(
        self,
        query,
        limit=5,
    ):
        return self.semantic_search.search(
            query,
            limit,
        )
