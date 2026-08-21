from collections import OrderedDict
from typing import Any, Dict, List


class ResponseFusion:
    """
    Combines outputs from multiple specialist agents into one
    coherent response.
    """

    def combine(
        self,
        results,
    ):
        """
        Combine specialist outputs into one coherent response.

        Supports both:
        - legacy result objects exposing .data
        - modern coordinator dictionaries

        The fusion layer does not invent new information.
        It only selects, orders, deduplicates and combines
        available agent outputs.
        """

        if not results:
            return ""

        responses = []

        for result in results:

            if not result:
                continue

            response = self._extract_response(
                result
            )

            if not response:
                continue

            response = str(
                response
            ).strip()

            if response:
                responses.append(
                    response
                )

        # Remove duplicates while preserving order.
        responses = list(
            OrderedDict.fromkeys(
                responses
            )
        )

        if not responses:
            return ""

        return "\n\n".join(
            responses
        )

    def _extract_response(
        self,
        result: Any,
    ):
        """
        Extract a response from either the modern coordinator
        result format or the legacy result-object format.
        """

        # -----------------------------------------------------
        # Modern dictionary result
        # -----------------------------------------------------

        if isinstance(
            result,
            dict,
        ):

            if result.get(
                "success",
                True,
            ) is False:
                return None

            value = result.get(
                "result"
            )

            if value is None:
                value = result.get(
                    "output"
                )

            if isinstance(
                value,
                dict,
            ):
                value = (
                    value.get("response")
                    or value.get("answer")
                    or value.get("output")
                    or value.get("result")
                )

            return value

        # -----------------------------------------------------
        # Legacy result object
        # -----------------------------------------------------

        data = getattr(
            result,
            "data",
            None,
        )

        if isinstance(
            data,
            dict,
        ):
            return (
                data.get("response")
                or data.get("answer")
                or data.get("output")
                or data.get("result")
            )

        # -----------------------------------------------------
        # Plain string compatibility
        # -----------------------------------------------------

        if isinstance(
            result,
            str,
        ):
            return result

        return None

    def fuse(
        self,
        results,
    ) -> Dict[str, Any]:
        """
        Produce structured response-fusion telemetry.

        The existing combine() method remains the simple
        compatibility interface.
        """

        if not results:
            return {
                "response": "",
                "sources": [],
                "confidence": 0.0,
                "successful_agents": [],
                "failed_agents": [],
            }

        responses = []
        sources = []
        successful_agents = []
        failed_agents = []
        confidences = []

        for result in results:

            if not isinstance(
                result,
                dict,
            ):
                response = self._extract_response(
                    result
                )

                if response:
                    responses.append(
                        str(response).strip()
                    )

                continue

            agent = result.get(
                "agent"
            )

            success = result.get(
                "success",
                True,
            )

            confidence = result.get(
                "confidence",
                0.0,
            )

            try:
                confidence = float(
                    confidence
                )
            except (
                TypeError,
                ValueError,
            ):
                confidence = 0.0

            if success:
                if agent:
                    successful_agents.append(
                        agent
                    )

                confidences.append(
                    confidence
                )

                response = self._extract_response(
                    result
                )

                if response:
                    responses.append(
                        str(response).strip()
                    )

                if agent:
                    sources.append(
                        agent
                    )

            else:
                if agent:
                    failed_agents.append(
                        agent
                    )

        responses = list(
            OrderedDict.fromkeys(
                responses
            )
        )

        sources = list(
            OrderedDict.fromkeys(
                sources
            )
        )

        successful_agents = list(
            OrderedDict.fromkeys(
                successful_agents
            )
        )

        failed_agents = list(
            OrderedDict.fromkeys(
                failed_agents
            )
        )

        average_confidence = (
            sum(confidences)
            / len(confidences)
            if confidences
            else 0.0
        )

        return {
            "response": "\n\n".join(
                responses
            ),
            "sources": sources,
            "confidence": round(
                average_confidence,
                3,
            ),
            "successful_agents": successful_agents,
            "failed_agents": failed_agents,
        }
