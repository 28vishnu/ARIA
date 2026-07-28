class ResponseFormatter:

    def format(self, data: dict) -> str:
        if not data:
            return "Done."

        # Calculator
        if "result" in data:
            return str(data["result"])

        # Python output
        if "output" in data:
            return f"Python Output\n\n{data['output']}"

        # Normal AI response
        if "response" in data:
            return data["response"].strip()

        return str(data)