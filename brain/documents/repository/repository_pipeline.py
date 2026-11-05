import logging

logger = logging.getLogger("aria")


class RepositoryPipeline:

    def __init__(
        self,
        zip_parser,
        repository_analyzer,
        code_parser,
        dependency_graph,
        repository_memory,
    ):

        self.zip_parser = zip_parser
        self.repository_analyzer = repository_analyzer
        self.code_parser = code_parser
        self.dependency_graph = dependency_graph
        self.repository_memory = repository_memory

    async def process(
        self,
        zip_file,
    ):

        document = await self.zip_parser.parse(
            zip_file
        )

        repository = self.repository_analyzer.analyze(
            document.path
        )

        parsed_files = []

        from pathlib import Path

        root = Path(document.path)

        for relative in repository["python_files"]:

            file_path = root / relative

            parsed = self.code_parser.parse(
                file_path
            )

            parsed_files.append(parsed)

            self.dependency_graph.add_dependencies(
                parsed["file"],
                parsed["imports"],
            )

        self.repository_memory.store(
            document.name,
            parsed_files,
        )

        self.zip_parser.cleanup(
            document
        )

        logger.info(
            "[RepositoryPipeline] Repository processed successfully."
        )

        return repository
