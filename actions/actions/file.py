import os
import aiofiles
from typing import Dict, Any
from actions.base import BaseAction, ActionResult

# All FileAction operations are restricted to this directory.
FILE_WORKSPACE = os.path.abspath(
    os.getenv("ARIA_FILE_WORKSPACE", "/tmp/aria_workspace")
)

ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
}

MAX_WRITE_BYTES = 1_000_000  # 1 MB
MAX_READ_BYTES = 1_000_000  # 1 MB

os.makedirs(FILE_WORKSPACE, exist_ok=True)


class FileAction(BaseAction):
    name = "file_action"
    description = "Safely reads or writes text files on disk."
    permission_level = "confirm"

    def _resolve_safe_path(self, requested_path: str) -> str | None:
        """
        Resolve a user-supplied path inside ARIA's file workspace.

        Returns None if the path attempts to escape the sandbox.
        """
        if not requested_path:
            return None

        requested_path = str(requested_path).strip()

        # Treat user paths as relative to the workspace.
        requested_path = requested_path.lstrip("/\\")

        resolved = os.path.abspath(
            os.path.join(FILE_WORKSPACE, requested_path)
        )

        try:
            if os.path.commonpath(
                [FILE_WORKSPACE, resolved]
            ) != FILE_WORKSPACE:
                return None
        except ValueError:
            return None

        return resolved

    async def validate(self, params: Dict[str, Any]) -> bool:
        mode = params.get("mode")
        path = params.get("path")

        if mode not in ("read", "write"):
            return False

        if not path:
            return False

        safe_path = self._resolve_safe_path(path)

        if safe_path is None:
            return False

        extension = os.path.splitext(safe_path)[1].lower()

        if extension not in ALLOWED_EXTENSIONS:
            return False

        if mode == "write":
            content = str(params.get("content", ""))

            if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
                return False

        return True

    async def execute(self, params: Dict[str, Any]) -> ActionResult:
        mode = params.get("mode")
        requested_path = params.get("path")
        content = params.get("content", "")

        path = self._resolve_safe_path(requested_path)

        if path is None:
            return ActionResult(
                success=False,
                action_name=self.name,
                error="Unsafe file path."
            )

        try:
            if mode == "read":
                if not os.path.exists(path):
                    return ActionResult(
                        success=False,
                        action_name=self.name,
                        error="File not found."
                    )

                if os.path.getsize(path) > MAX_READ_BYTES:
                    return ActionResult(
                        success=False,
                        action_name=self.name,
                        error="File exceeds maximum readable size."
                    )

                async with aiofiles.open(
                    path,
                    mode="r",
                    encoding="utf-8"
                ) as f:
                    data = await f.read()

                return ActionResult(
                    success=True,
                    action_name=self.name,
                    data={"content": data}
                )

            elif mode == "write":
                parent_dir = os.path.dirname(path)

                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

                async with aiofiles.open(
                    path,
                    mode="w",
                    encoding="utf-8"
                ) as f:
                    await f.write(content)

                return ActionResult(
                    success=True,
                    action_name=self.name,
                    data={"status": "written successfully"}
                )

            return ActionResult(
                success=False,
                action_name=self.name,
                error="Invalid file mode."
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action_name=self.name,
                error=str(e)
            )
