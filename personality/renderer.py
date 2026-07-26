import logging
from personality.response import SystemResponse
from personality.formatter import ResponseFormatter

logger = logging.getLogger("aria")

class ResponseRenderer:
    def __init__(self, formatter: ResponseFormatter = ResponseFormatter()):
        self.formatter = formatter

    def render_to_natural_language(self, response: SystemResponse, styled_message: str) -> str:
        """Converts structured SystemResponses and styled text into final render-ready output."""
        if not response.success:
            error_msg = response.error or "Unknown error occurred."
            return f"Execution failed, Sir. Details: {error_msg}"
        
        return self.formatter.to_markdown(styled_message)
