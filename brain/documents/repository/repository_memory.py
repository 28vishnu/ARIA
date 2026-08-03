from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging

logger = logging.getLogger("aria")


@dataclass
class RepositoryKnowledge:

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    repository: str = ""

    file: str = ""

    classes: list = field(default_factory=list)

    functions: list = field(default_factory=list)

    imports: list = field(default_factory=list)

    created_at: datetime = field(default_factory=datetime.utcnow)


class RepositoryMemory:

    def __init__(self):

        self.repositories = {}

    def store(
        self,
        repository_name,
        parsed_files,
    ):

        self.repositories[repository_name] = parsed_files

        logger.info(
            "[RepositoryMemory] Stored repository %s (%d files)",
            repository_name,
            len(parsed_files),
        )

    def get_repository(
        self,
        repository_name,
    ):

        return self.repositories.get(
            repository_name
        )

    def find_class(
        self,
        class_name,
    ):

        results = []

        for repo, files in self.repositories.items():

            for file in files:

                for cls in file.get("classes", []):

                    if cls["name"].lower() == class_name.lower():

                        results.append({
                            "repository": repo,
                            "file": file["file"],
                            "line": cls["line"],
                        })

        return results

    def find_function(
        self,
        function_name,
    ):

        results = []

        for repo, files in self.repositories.items():

            for file in files:

                for fn in file.get("functions", []):

                    if fn["name"].lower() == function_name.lower():

                        results.append({
                            "repository": repo,
                            "file": file["file"],
                            "line": fn["line"],
                        })

        return results
