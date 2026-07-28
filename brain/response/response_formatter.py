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

    def merge(self, results):

        outputs = []

        for result in results:

            if not result:
                continue

            data = result.data if hasattr(result, "data") else result

            if not data:
                continue

            if isinstance(data, dict):

                value = (
                    data.get("response")
                    or data.get("message")
                    or data.get("result")
                )

                if value is None:
                    continue

                text = str(value).strip()

                if text and text.lower() != "none":
                    outputs.append(text)

            else:

                text = str(data).strip()

                if text and text.lower() != "none":
                    outputs.append(text)

        return "\n\n".join(outputs)
