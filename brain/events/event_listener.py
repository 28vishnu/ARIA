class EventListener:
    """
    Base class for every event listener.
    """

    async def handle(
        self,
        event,
    ):
        """
        Override in subclasses.
        """
        raise NotImplementedError