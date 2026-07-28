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

            if isinstance(data, dict):

                if "response" in data:
                    outputs.append(str(data["response"]))

                elif "message" in data:
                    outputs.append(str(data["message"]))

                elif "result" in data:
                    outputs.append(str(data["result"]))

            else:
                outputs.append(str(data))

        return "\n\n".join(outputs)
