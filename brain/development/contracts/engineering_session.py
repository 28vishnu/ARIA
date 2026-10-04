    def set_knowledge_context(
        self,
        knowledge_context: dict[str, Any],
    ) -> None:
        """Record the knowledge context used by this engineering run."""

        if not isinstance(
            knowledge_context,
            dict,
        ):
            raise TypeError(
                "knowledge_context must be a dictionary."
            )

        with self._lock:
            self._state.knowledge_context = deepcopy(
                knowledge_context
            )
            self._touch()

    def knowledge_context(
        self,
    ) -> dict[str, Any]:
        """Return a defensive copy of the current knowledge context."""

        with self._lock:
            return deepcopy(
                self._state.knowledge_context
            )