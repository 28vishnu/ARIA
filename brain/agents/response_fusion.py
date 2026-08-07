from collections import OrderedDict


class ResponseFusion:
    """
    Combines outputs from multiple specialist agents into one
    coherent response.
    """

    def combine(self, results):

        if not results:
            return ""

        if len(results) == 1:
            return results[0].data.get(
                "response",
                "",
            )

        responses = []

        for result in results:

            if not result:
                continue

            response = result.data.get("response")

            if response:
                responses.append(
                    str(response).strip()
                )

        # Remove duplicates while preserving order
        responses = list(
            OrderedDict.fromkeys(responses)
        )

        # Remove empty responses
        responses = [
            r
            for r in responses
            if r
        ]

        return "\n\n".join(responses)

