import logging

logger = logging.getLogger("aria")


class ParserRegistry:

    def __init__(self):

        self._parsers = {}

    def register(
        self,
        extension: str,
        parser,
    ):

        extension = extension.lower()

        self._parsers[extension] = parser

        logger.info(
            "[ParserRegistry] Registered parser: %s",
            extension,
        )

    def get_parser(
        self,
        extension: str,
    ):

        return self._parsers.get(
            extension.lower()
        )

    def supported_extensions(self):

        return sorted(
            self._parsers.keys()
        )

    def has_parser(
        self,
        extension: str,
    ):

        return extension.lower() in self._parsers
