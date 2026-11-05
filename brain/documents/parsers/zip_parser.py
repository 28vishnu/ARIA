import zipfile
import tempfile
import shutil
import logging
from pathlib import Path

from ..models import Document

logger = logging.getLogger("aria")


class ZIPParser:

    async def parse(self, file_path: str) -> Document:

        extract_dir = Path(
            tempfile.mkdtemp(prefix="aria_zip_")
        )

        with zipfile.ZipFile(file_path, "r") as archive:
            archive.extractall(extract_dir)

        files = []

        for path in extract_dir.rglob("*"):

            if path.is_file():

                files.append(
                    str(path.relative_to(extract_dir))
                )

        document = Document(
            name=Path(file_path).name,
            path=str(extract_dir),
            extension=".zip",
            size=Path(file_path).stat().st_size,
            metadata={
                "file_count": len(files),
                "files": files,
            },
        )

        logger.info(
            "[ZIPParser] Extracted %d files from %s",
            len(files),
            document.name,
        )

        return document

    def cleanup(self, document):

        try:

            shutil.rmtree(document.path)

            logger.info(
                "[ZIPParser] Cleaned up %s",
                document.path,
            )

        except Exception:

            logger.exception(
                "[ZIPParser] Cleanup failed"
            )
