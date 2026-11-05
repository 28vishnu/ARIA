from typing import Any


class ResponseFormatter:

    def format(self, data: dict) -> str:
        """
        Convert internal ARIA response data into clean
        user-facing text.

        Internal workflow structures such as task_outputs and
        workflow_results must never be exposed to the user.
        """

        if not data:
            return "Done."

        if not isinstance(data, dict):
            return str(data).strip()

        # -----------------------------------------------------
        # 1. USER-FACING AI RESPONSE
        # -----------------------------------------------------

        for key in (
            "message",
            "response",
            "answer",
            "summary",
            "content",
        ):
            value = data.get(key)

            if isinstance(value, str):
                value = value.strip()

                if value:
                    return value

        # -----------------------------------------------------
        # 2. CALCULATOR / SIMPLE RESULT
        # -----------------------------------------------------

        if "result" in data:

            result = data["result"]

            # Some actions return structured result dictionaries.
            # Do not dump them directly to the user.
            if isinstance(result, dict):

                for key in (
                    "message",
                    "response",
                    "answer",
                    "summary",
                    "content",
                    "status",
                ):
                    value = result.get(key)

                    if isinstance(value, str) and value.strip():
                        return value.strip()

            elif result is not None:
                return str(result).strip()

        # -----------------------------------------------------
        # 3. PYTHON / CODE OUTPUT
        # -----------------------------------------------------

        if "output" in data:

            output = data.get("output")

            if output is not None:
                return f"Python Output\n\n{str(output).strip()}"

        # -----------------------------------------------------
        # 4. WORKFLOW COMPLETED BUT NO DISPLAYABLE RESPONSE
        #
        # Never stringify task_outputs/workflow_results.
        # -----------------------------------------------------

        if (
            "task_outputs" in data
            or "workflow_results" in data
        ):
            return "Execution completed successfully."

        return "Done."

    def merge(self, results):
        """
        Merge multiple responses without exposing internal
        execution dictionaries.
        """

        outputs = []

        for result in results:

            if not result:
                continue

            data = (
                result.data
                if hasattr(result, "data")
                else result
            )

            if not data:
                continue

            if isinstance(data, dict):

                text = self.format(data)

            else:

                text = str(data).strip()

            if not text:
                continue

            if text.lower() in {
                "none",
                "done.",
            }:
                continue

            # Avoid duplicate responses.
            if text not in outputs:
                outputs.append(text)

        if not outputs:
            return "Done."

        return "\n\n".join(outputs)