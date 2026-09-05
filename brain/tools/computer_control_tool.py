import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from brain.tools.base_tool import BaseTool

logger = logging.getLogger("aria")


class ComputerControlTool(BaseTool):
    """
    ARIA computer-control execution tool.

    Provides controlled access to:
        - mouse movement
        - mouse clicks
        - keyboard typing
        - key presses
        - keyboard shortcuts
        - screenshots
        - screen information

    The tool intentionally keeps computer actions separate
    from ARIA's reasoning layer.
    """

    def __init__(self):
        super().__init__("computer_control")

        self._pyautogui = None
        self._import_error: Optional[str] = None

        try:
            import pyautogui

            self._pyautogui = pyautogui

            # Prevent PyAutoGUI from failing because of
            # an unavailable graphical display during import.
            self._pyautogui.PAUSE = 0.05

        except Exception as exc:
            self._import_error = str(exc)

            logger.warning(
                "[ComputerControl] PyAutoGUI unavailable: %s",
                exc,
            )

    # =========================================================
    # AVAILABILITY
    # =========================================================

    def _available(self) -> bool:
        return self._pyautogui is not None

    # =========================================================
    # TOOL DETECTION
    # =========================================================

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:

        q = (query or "").lower().strip()

        if not q:
            return 0.0

        computer_terms = (
            "computer",
            "desktop",
            "screen",
            "mouse",
            "cursor",
            "keyboard",
            "click",
            "double click",
            "right click",
            "type",
            "press key",
            "keypress",
            "hotkey",
            "screenshot",
            "take screenshot",
            "move mouse",
            "move cursor",
            "scroll",
            "copy",
            "paste",
        )

        if any(term in q for term in computer_terms):
            return 0.98

        return 0.0

    # =========================================================
    # SAFETY
    # =========================================================

    def _is_enabled(
        self,
        context: Dict[str, Any],
    ) -> bool:

        return bool(
            context.get(
                "computer_control_enabled",
                False,
            )
        )

    def _requires_confirmation(
        self,
        query: str,
    ) -> bool:

        q = (query or "").lower()

        sensitive_terms = (
            "delete",
            "remove",
            "shutdown",
            "restart",
            "format",
            "uninstall",
            "send",
            "submit",
            "purchase",
            "buy",
            "transfer",
            "close all",
        )

        return any(
            term in q
            for term in sensitive_terms
        )

    # =========================================================
    # HELPERS
    # =========================================================

    def _error_response(
        self,
        message: str,
    ) -> Dict[str, Any]:

        return {
            "success": False,
            "tool": self.name,
            "error": message,
        }

    def _success_response(
        self,
        action: str,
        result: Any = None,
    ) -> Dict[str, Any]:

        response = {
            "success": True,
            "tool": self.name,
            "action": action,
        }

        if result is not None:
            response["result"] = result

        return response

    def _parse_coordinates(
        self,
        context: Dict[str, Any],
    ):
        coordinates = context.get("coordinates")

        if (
            isinstance(coordinates, (list, tuple))
            and len(coordinates) == 2
        ):
            try:
                return (
                    int(coordinates[0]),
                    int(coordinates[1]),
                )
            except (
                TypeError,
                ValueError,
            ):
                pass

        x = context.get("x")
        y = context.get("y")

        if x is not None and y is not None:
            try:
                return int(x), int(y)
            except (
                TypeError,
                ValueError,
            ):
                pass

        return None

    # =========================================================
    # SCREEN INFORMATION
    # =========================================================

    async def screen_size(
        self,
    ) -> Dict[str, Any]:

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable. "
                f"PyAutoGUI error: {self._import_error}"
            )

        try:
            width, height = (
                self._pyautogui.size()
            )

            return self._success_response(
                "screen_size",
                {
                    "width": width,
                    "height": height,
                },
            )

        except Exception as exc:
            logger.exception(
                "[ComputerControl] Screen-size detection failed."
            )

            return self._error_response(
                str(exc)
            )

    # =========================================================
    # MOUSE
    # =========================================================

    async def move_mouse(
        self,
        x: int,
        y: int,
    ) -> Dict[str, Any]:

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable."
            )

        try:
            self._pyautogui.moveTo(
                int(x),
                int(y),
                duration=0.15,
            )

            return self._success_response(
                "move_mouse",
                {
                    "x": int(x),
                    "y": int(y),
                },
            )

        except Exception as exc:
            logger.exception(
                "[ComputerControl] Mouse movement failed."
            )

            return self._error_response(
                str(exc)
            )

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> Dict[str, Any]:

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable."
            )

        try:
            self._pyautogui.click(
                x=int(x),
                y=int(y),
                clicks=int(clicks),
                button=button,
                interval=0.1,
            )

            return self._success_response(
                "click",
                {
                    "x": int(x),
                    "y": int(y),
                    "button": button,
                    "clicks": int(clicks),
                },
            )

        except Exception as exc:
            logger.exception(
                "[ComputerControl] Mouse click failed."
            )

            return self._error_response(
                str(exc)
            )

    async def scroll(
        self,
        amount: int,
    ) -> Dict[str, Any]:

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable."
            )

        try:
            self._pyautogui.scroll(
                int(amount)
            )

            return self._success_response(
                "scroll",
                {
                    "amount": int(amount),
                },
            )

        except Exception as exc:
            logger.exception(
                "[ComputerControl] Scroll failed."
            )

            return self._error_response(
                str(exc)
            )

    # =========================================================
    # KEYBOARD
    # =========================================================

    async def type_text(
        self,
        text: str,
    ) -> Dict[str, Any]:

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable."
            )

        if not text:
            return self._error_response(
                "No text was supplied."
            )

        try:
            self._pyautogui.write(
                str(text),
                interval=0.01,
            )

            return self._success_response(
                "type",
                {
                    "characters": len(
                        str(text)
                    ),
                },
            )

        except Exception as exc:
            logger.exception(
                "[ComputerControl] Typing failed."
            )

            return self._error_response(
                str(exc)
            )

    async def press_key(
        self,
        key: str,
    ) -> Dict[str, Any]:

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable."
            )

        if not key:
            return self._error_response(
                "No key was supplied."
            )

        try:
            self._pyautogui.press(
                str(key)
            )

            return self._success_response(
                "press",
                {
                    "key": str(key),
                },
            )

        except Exception as exc:
            logger.exception(
                "[ComputerControl] Key press failed."
            )

            return self._error_response(
                str(exc)
            )

    async def hotkey(
        self,
        keys,
    ) -> Dict[str, Any]:

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable."
            )

        if not keys:
            return self._error_response(
                "No hotkey combination was supplied."
            )

        try:
            normalized_keys = [
                str(key)
                for key in keys
            ]

            self._pyautogui.hotkey(
                *normalized_keys
            )

            return self._success_response(
                "hotkey",
                {
                    "keys": normalized_keys,
                },
            )

        except Exception as exc:
            logger.exception(
                "[ComputerControl] Hotkey failed."
            )

            return self._error_response(
                str(exc)
            )

    # =========================================================
    # SCREENSHOT
    # =========================================================

    async def screenshot(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable."
            )

        output_path = context.get(
            "screenshot_path"
        )

        if not output_path:
            output_path = (
                "aria_screenshot.png"
            )

        try:
            path = Path(
                str(output_path)
            ).expanduser()

            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            image = (
                self._pyautogui.screenshot()
            )

            image.save(path)

            return self._success_response(
                "screenshot",
                {
                    "path": str(
                        path.resolve()
                    ),
                    "width": image.width,
                    "height": image.height,
                },
            )

        except Exception as exc:
            logger.exception(
                "[ComputerControl] Screenshot failed."
            )

            return self._error_response(
                str(exc)
            )

    # =========================================================
    # EXECUTION
    # =========================================================

    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> Any:

        context = context or {}

        if not self._available():
            return self._error_response(
                "Computer-control backend is unavailable. "
                "Install/configure PyAutoGUI on the machine "
                "that should be controlled."
            )

        if not self._is_enabled(context):
            return self._error_response(
                "Computer control is disabled. "
                "Enable it explicitly in the execution context."
            )

        if self._requires_confirmation(query):
            if not context.get(
                "computer_control_confirmed",
                False,
            ):
                return self._error_response(
                    "This computer action requires explicit "
                    "confirmation before execution."
                )

        operation = (
            context.get("computer_operation")
            or context.get("operation")
        )

        # -------------------------------------------------
        # SCREEN
        # -------------------------------------------------

        if operation == "screen_size":
            return await self.screen_size()

        # -------------------------------------------------
        # SCREENSHOT
        # -------------------------------------------------

        if operation == "screenshot":
            return await self.screenshot(
                context
            )

        # -------------------------------------------------
        # MOUSE MOVE
        # -------------------------------------------------

        if operation == "move_mouse":
            coordinates = (
                self._parse_coordinates(
                    context
                )
            )

            if coordinates is None:
                return self._error_response(
                    "Mouse coordinates were not supplied."
                )

            return await self.move_mouse(
                coordinates[0],
                coordinates[1],
            )

        # -------------------------------------------------
        # CLICK
        # -------------------------------------------------

        if operation == "click":
            coordinates = (
                self._parse_coordinates(
                    context
                )
            )

            if coordinates is None:
                return self._error_response(
                    "Click coordinates were not supplied."
                )

            return await self.click(
                coordinates[0],
                coordinates[1],
                button=context.get(
                    "button",
                    "left",
                ),
                clicks=context.get(
                    "clicks",
                    1,
                ),
            )

        # -------------------------------------------------
        # SCROLL
        # -------------------------------------------------

        if operation == "scroll":
            amount = context.get(
                "amount"
            )

            if amount is None:
                return self._error_response(
                    "Scroll amount was not supplied."
                )

            return await self.scroll(
                int(amount)
            )

        # -------------------------------------------------
        # TYPE
        # -------------------------------------------------

        if operation == "type":
            text = context.get(
                "text"
            )

            if text is None:
                text = query

            return await self.type_text(
                str(text)
            )

        # -------------------------------------------------
        # PRESS
        # -------------------------------------------------

        if operation == "press":
            key = context.get(
                "key"
            )

            if not key:
                return self._error_response(
                    "Key was not supplied."
                )

            return await self.press_key(
                str(key)
            )

        # -------------------------------------------------
        # HOTKEY
        # -------------------------------------------------

        if operation == "hotkey":
            keys = context.get(
                "keys"
            )

            return await self.hotkey(
                keys
            )

        return self._error_response(
            "Unknown computer-control operation. "
            "Supported operations: screen_size, "
            "screenshot, move_mouse, click, scroll, "
            "type, press, hotkey."
        )