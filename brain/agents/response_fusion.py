class ResponseFusion:
    """
    Combines outputs from multiple agents into one response.
    """

    def combine(self, results):

        if not results:
            return ""

        if len(results) == 1:
            return results[0].data.get("response", "")

        responses = []

        for result in results:

            if not result:
                continue

            response = result.data.get("response")

            if response:
                responses.append(str(response))

        return "\n\n".join(responses)