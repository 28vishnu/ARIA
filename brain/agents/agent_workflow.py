class AgentWorkflow:
    """
    Represents a workflow of multiple specialised agents.
    """

    def __init__(self):
        self.agents = []

    def add(self, agent):
        self.agents.append(agent)

    def __iter__(self):
        return iter(self.agents)

    def __len__(self):
        return len(self.agents)