import re
import logging

from ..models import DocumentConcept

logger = logging.getLogger("aria")


class ConceptExtractor:

    def __init__(self):

        self.heading_pattern = re.compile(
            r"^(#{1,6}\s.*|[A-Z][A-Za-z0-9\s]{3,60}:?)$"
        )

        self.definition_pattern = re.compile(
            r"(.+?)\s+(is|are|refers to|defined as)\s+(.+)",
            re.IGNORECASE,
        )

    def extract(self, document):

        concepts = []

        for page in document.pages:

            concepts.extend(
                self.extract_from_page(
                    page.text,
                    page.number,
                )
            )

        logger.info(
            "[ConceptExtractor] Extracted %d concepts",
            len(concepts),
        )

        return concepts

    def extract_from_page(
        self,
        text,
        page_number,
    ):

        concepts = []

        lines = text.splitlines()

        for line in lines:

            line = line.strip()

            if not line:
                continue

            if self.heading_pattern.match(line):

                concepts.append(
                    DocumentConcept(
                        name=line,
                        importance=0.8,
                        pages=[page_number],
                    )
                )

                continue

            match = self.definition_pattern.match(line)

            if match:

                concepts.append(
                    DocumentConcept(
                        name=match.group(1).strip(),
                        description=match.group(3).strip(),
                        importance=1.0,
                        pages=[page_number],
                    )
                )

        return concepts
