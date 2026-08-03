from pathlib import Path
import logging

from .parser_registry import ParserRegistry

logger = logging.getLogger("aria")


class DocumentManager:

    def __init__(self):

        self.registry = ParserRegistry()

    def register_parser(
        self,
        extension,
        parser,
    ):

        self.registry.register(
            extension,
            parser,
        )

        logger.info(
            "[DocumentManager] Registered parser: %s",
            extension,
        )

    async def parse(self, file_path):

        suffix = Path(file_path).suffix.lower()

        parser = self.registry.get_parser(
            suffix
        )

        if parser is None:

            raise ValueError(
                f"No parser registered for '{suffix}'"
            )

        logger.info(
            "[DocumentManager] Parsing %s",
            file_path,
        )

        return await parser.parse(file_path)
