from pathlib import Path
import logging

logger = logging.getLogger("aria")


class RepositoryAnalyzer:

    def __init__(self):

        self.supported_extensions = {
            ".py",
            ".js",
            ".ts",
            ".java",
            ".cpp",
            ".c",
            ".cs",
            ".go",
            ".rs",
            ".html",
            ".css",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".md",
        }

    def analyze(self, repository_path):

        repository = Path(repository_path)

        result = {
            "directories": [],
            "files": [],
            "languages": set(),
            "configs": [],
            "entry_points": [],
        }

        for path in repository.rglob("*"):

            if path.is_dir():

                result["directories"].append(
                    str(path.relative_to(repository))
                )

                continue

            suffix = path.suffix.lower()

            if suffix in self.supported_extensions:

                result["files"].append(
                    str(path.relative_to(repository))
                )

                if suffix:
                    result["languages"].add(suffix)

            if path.name in {
                "requirements.txt",
                "pyproject.toml",
                "package.json",
                "dockerfile",
                "Dockerfile",
                "docker-compose.yml",
                ".env",
                "README.md",
            }:

                result["configs"].append(
                    str(path.relative_to(repository))
                )

            if path.name in {
                "main.py",
                "app.py",
                "run.py",
                "manage.py",
                "index.js",
                "server.py",
            }:

                result["entry_points"].append(
                    str(path.relative_to(repository))
                )

        result["languages"] = sorted(result["languages"])

        logger.info(
            "[RepositoryAnalyzer] %d files, %d directories",
            len(result["files"]),
            len(result["directories"]),
        )

        return result
