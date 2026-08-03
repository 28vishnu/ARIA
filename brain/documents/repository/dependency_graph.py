import logging
from collections import defaultdict

logger = logging.getLogger("aria")


class DependencyGraph:

    def __init__(self):

        self.graph = defaultdict(set)

    def add_dependencies(
        self,
        file_name,
        imports,
    ):

        for imported in imports:

            if imported:

                self.graph[file_name].add(imported)

    def get_dependencies(
        self,
        file_name,
    ):

        return sorted(
            self.graph.get(file_name, [])
        )

    def get_dependents(
        self,
        module_name,
    ):

        dependents = []

        for file_name, imports in self.graph.items():

            if module_name in imports:

                dependents.append(file_name)

        return sorted(dependents)

    def all_modules(self):

        return sorted(
            self.graph.keys()
        )

    def clear(self):

        self.graph.clear()

        logger.info(
            "[DependencyGraph] Cleared dependency graph"
        )

    def summary(self):

        total_edges = sum(
            len(v)
            for v in self.graph.values()
        )

        return {
            "modules": len(self.graph),
            "dependencies": total_edges,
        }
