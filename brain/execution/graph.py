from brain.execution.node import ActionNode


class ActionGraph:

    def __init__(self):

        self.nodes = []

    def add(self, node: ActionNode):

        self.nodes.append(node)

    def completed(self):

        return all(
            n.status == "completed"
            for n in self.nodes
        )
