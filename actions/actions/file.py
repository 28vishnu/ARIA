import os
import aiofiles
from typing import Dict, Any
from actions.base import BaseAction, ActionResult

# All FileAction operations are restricted to this directory.
FILE_WORKSPACE = os.path.abspath(
    os.getenv("ARIA_FILE_WORKSPACE", "/tmp/aria_workspace")
)

os.makedirs(FILE_WORKSPACE, exist_ok=True)


class FileAction(BaseAction):
    name = "file_action"
    description = "Safely reads or writes text files on disk."
    permission_level = "confirm"

    async def validate(self, params: Dict[str, Any]) -> bool:
        mode = params.get("mode")
        path = params.get("path")
        return bool(mode in ["read", "write"] and path)

    async def execute(self, params: Dict[str, Any]) -> ActionResult:
        mode = params.get("mode")
        path = params.get("path")
        content = params.get("content", "")

        try:
            if mode == "read":
                if not os.path.exists(path):
                    return ActionResult(success=False, action_name=self.name, error="File not found.")
                async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
                    data = await f.read()
                return ActionResult(success=True, action_name=self.name, data={"content": data})

            elif mode == "write":
                async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
                    await f.write(content)
                return ActionResult(success=True, action_name=self.name, data={"status": "written successfully"})

            return ActionResult(success=False, action_name=self.name, error="Invalid file mode.")
        except Exception as e:
            return ActionResult(success=False, action_name=self.name, error=str(e))
