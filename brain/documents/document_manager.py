from pathlib import Path
import logging

logger = logging.getLogger("aria")


class DocumentManager:

    def __init__(self):

        self.parsers = {}

    def register_parser(
        self,
        extension,
        parser,
    ):

        self.parsers[extension.lower()] = parser

        logger.info(
            "[DocumentManager] Registered parser: %s",
            extension,
        )

    async def parse(self, file_path):

        suffix = Path(file_path).suffix.lower()

        parser = self.parsers.get(suffix)

        if parser is None:

            raise ValueError(
                f"No parser registered for '{suffix}'"
            )

        logger.info(
            "[DocumentManager] Parsing %s",
            file_path,
        )

        return await parser.parse(file_path)
